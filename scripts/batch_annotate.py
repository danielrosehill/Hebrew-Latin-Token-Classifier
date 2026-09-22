#!/usr/bin/env python3
"""Annotate via a real async Batch API instead of live calls.

Why this exists. Measured on this workload, a live single-sentence annotation call
spends 604 of 615 completion tokens on reasoning -- about 11 tokens of actual
answer -- and 2,733 of them took roughly three hours. A batch API halves the price
and removes the per-call latency entirely: you submit one file and collect the
results later.

Provider: **Together AI**, which has a genuine batch job queue (upload -> job ->
poll -> download), not merely a discounted model tier. Checked 2026-09-22; of the
platforms with keys on this machine it was the only usable one. OpenAI's key
authenticates but the account has no credits, and Mistral returns 429 on every
call.

Credential: TOGETHER_API_KEY, or 1Password item "Together AI API Key" in the
"API Keys & Programmatic" vault, read at run time. Never stored in this repo.

    python3 scripts/batch_annotate.py submit
    python3 scripts/batch_annotate.py status
    python3 scripts/batch_annotate.py fetch

State lives in data/generated/batch-job.json, so submit and fetch can be days
apart. fetch is idempotent and merges into the same annotations.jsonl the live
path writes, so the two are interchangeable downstream.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib import corpus  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "generated"
SENTENCES = GEN / "sentences.jsonl"
OUT = GEN / "annotations.jsonl"
JOB = GEN / "batch-job.json"
REQUESTS = GEN / "batch-requests.jsonl"

BASE = "https://api.together.xyz/v1"
OP_ITEM = ("Together AI API Key", "API Keys & Programmatic")

# Kept identical to scripts/auto_annotate.py: the two paths must be interchangeable.
SYSTEM = """You identify Hebrew words written in Latin characters inside English text.

The test is pronunciation, not etymology: would an English text-to-speech voice \
mispronounce this word, and would treating it as Hebrew fix that?

Label as Hebrew:
- Hebrew words an English speaker would not know: bituach leumi, makolet, mashkanta, \
mazgan, arnona, tlush, dud, balagan, beseder.
- Multi-word Hebrew terms, as ONE item: "bituach leumi", "teudat zehut", "osek patur".
- Words with Hebrew gutturals that English spelling cannot carry: challah, chagim, \
machsom, hashmal.
- Hebrew stems carrying an English affix: latkes, chagim. Give the full surface form.
- Israeli brand and company names that are said in Hebrew: Yad2, Galgalatz, Mako, Ynet.

Do NOT label:
- Hebrew words English has absorbed and pronounces acceptably: kosher, Shabbat, \
hummus, rabbi, kibbutz, chutzpah, bagel, falafel.
- Ordinary English words, even if they look like a Hebrew word: at, hi, lo, ken, ma, mi.
- An English word used in its English sense, even when the same string is also \
Hebrew: "the battery was a dud", "a salon appointment", "Layla phoned".
- Strings that only appear INSIDE a longer English word. "think" does not contain \
Hebrew "hi"; "Pharm" does not contain "har"; "school" does not contain "chool".
- Well-known place names and people: Tel Aviv, Jerusalem, Netanyahu.
- Brands whose names are ordinary English said in English: Fox Home, Max Stock.

Copy each term EXACTLY as it appears in the sentence, preserving case. If there are \
no Hebrew words, return an empty list. Do not explain."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["terms"],
    "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
}


def api_key(override: str | None = None) -> str:
    if override:
        return override
    import os
    key = os.environ.get("TOGETHER_API_KEY")
    if key:
        return key
    item, vault = OP_ITEM
    try:
        out = subprocess.run(
            ["op", "item", "get", item, "--vault", vault,
             "--fields", "credential", "--reveal"],
            capture_output=True, text=True, timeout=30, check=True)
        return out.stdout.strip()
    except Exception as e:
        raise SystemExit(
            f"no TOGETHER_API_KEY and could not read 1Password item {item!r} "
            f"in vault {vault!r}: {e}")


def client(key: str) -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=120.0,
                        headers={"Authorization": f"Bearer {key}"})


def custom_id(index: int) -> str:
    return f"s{index:06d}"


def cmd_submit(args) -> None:
    rows = corpus.read_jsonl(SENTENCES, dedupe_on="text")
    if not rows:
        raise SystemExit("no sentences; run scripts/generate_samples.py first")
    done = {r["text"] for r in corpus.read_jsonl(OUT, dedupe_on="text")}
    todo = [r for r in rows if r["text"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("nothing to annotate")
        return

    REQUESTS.parent.mkdir(parents=True, exist_ok=True)
    with REQUESTS.open("w") as fh:
        for i, row in enumerate(todo):
            fh.write(json.dumps({
                "custom_id": custom_id(i),
                "body": {
                    "model": args.model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": f"Sentence: {row['text']}"},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "result", "strict": True,
                                        "schema": SCHEMA},
                    },
                },
            }) + "\n")

    key = api_key(args.api_key)
    with client(key) as c:
        # /v1/files/upload, not /v1/files. file_name is required over REST --
        # only the SDKs infer it from the local path.
        with REQUESTS.open("rb") as fh:
            up = c.post("/files/upload",
                        files={"file": (REQUESTS.name, fh, "application/jsonl")},
                        data={"purpose": "batch-api", "file_name": REQUESTS.name})
        if up.status_code >= 400:
            raise SystemExit(f"upload failed {up.status_code}: {up.text[:400]}")
        file_id = up.json()["id"]

        # completion_window is not a parameter -- it is fixed at 24h best-effort.
        job = c.post("/batches", json={
            "input_file_id": file_id,
            "endpoint": "/v1/chat/completions",
        })
        if job.status_code >= 400:
            raise SystemExit(f"batch create failed {job.status_code}: {job.text[:400]}")
        body = job.json()
    if "job" in body and isinstance(body["job"], dict):
        body = body["job"]          # create() wraps the batch; retrieve() does not

    job_id = body.get("id") or body.get("job_id")
    JOB.write_text(json.dumps({
        "job_id": job_id,
        "input_file_id": file_id,
        "model": args.model,
        "requests": len(todo),
        # custom_id -> sentence text; the API only round-trips the id
        "index": {custom_id(i): r["text"] for i, r in enumerate(todo)},
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, ensure_ascii=False, indent=1))
    print(json.dumps({"job_id": job_id, "requests": len(todo),
                      "status": body.get("status")}, indent=1))
    print("\npoll with: python3 scripts/batch_annotate.py status")


def _job_body(c: httpx.Client, job_id: str) -> dict:
    r = c.get(f"/batches/{job_id}")
    if r.status_code >= 400:
        raise SystemExit(f"status failed {r.status_code}: {r.text[:300]}")
    return r.json()


def cmd_status(args) -> None:
    if not JOB.exists():
        raise SystemExit("no batch-job.json — submit first")
    state = json.loads(JOB.read_text())
    with client(api_key(args.api_key)) as c:
        body = _job_body(c, state["job_id"])
    print(json.dumps({k: body.get(k) for k in
                      ("id", "status", "progress", "request_counts",
                       "output_file_id", "error_file_id", "created_at",
                       "completed_at")
                      if body.get(k) is not None}, indent=1))
    if body.get("status") in ("VALIDATING", "IN_PROGRESS"):
        print("\npoll every 30-60s; most sub-1,000-request batches finish in minutes")


def cmd_fetch(args) -> None:
    if not JOB.exists():
        raise SystemExit("no batch-job.json — submit first")
    state = json.loads(JOB.read_text())
    index = state["index"]

    with client(api_key(args.api_key)) as c:
        body = _job_body(c, state["job_id"])
        status = body.get("status")
        out_id = body.get("output_file_id")
        if not out_id:
            raise SystemExit(f"job status {status!r}, no output file yet")
        content = c.get(f"/files/{out_id}/content")
        if content.status_code >= 400:
            raise SystemExit(f"download failed {content.status_code}: "
                             f"{content.text[:300]}")
        payload = content.text

        # A COMPLETED batch can still carry per-request failures; per-request
        # errors do not change the batch status, so the error file must be read.
        errors = []
        err_id = body.get("error_file_id")
        if err_id:
            er = c.get(f"/files/{err_id}/content")
            if er.status_code < 400:
                errors = [json.loads(l) for l in er.text.splitlines() if l.strip()]

    done = {r["text"] for r in corpus.read_jsonl(OUT, dedupe_on="text")}
    results, failures, unmatched_total = [], 0, 0
    usage_rows, prompt_tok, completion_tok = [], 0, 0

    for line in payload.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        cid = item.get("custom_id")
        text = index.get(cid)
        if text is None or text in done:
            continue
        try:
            body_ = item["response"]["body"]
            raw = body_["choices"][0]["message"]["content"]
            terms = json.loads(raw).get("terms") or []
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            failures += 1
            continue

        u = body_.get("usage") or {}
        prompt_tok += u.get("prompt_tokens", 0)
        completion_tok += u.get("completion_tokens", 0)
        usage_rows.append({
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stage": "annotate-batch", "provider": "together",
            "model": state["model"],
            "prompt_tokens": u.get("prompt_tokens", 0),
            "completion_tokens": u.get("completion_tokens", 0),
            "reasoning_tokens": 0, "cached_tokens": 0, "peak": None,
        })

        spans, unmatched = [], []
        for term in terms:
            found = corpus.word_spans(text, term)
            if not found:
                unmatched.append(term)   # never silently kept
                continue
            s, e = found[0]
            spans.append({"start": s, "end": e, "surface": text[s:e],
                          "term": term.lower()})
        spans.sort(key=lambda x: x["start"])
        unmatched_total += len(unmatched)
        results.append({
            "text": text,
            "annotator": state["model"],
            "spans": spans,
            "unmatched_terms": unmatched,
            "via": "together-batch",
        })

    if results:
        corpus.append_jsonl(OUT, results)
    total = corpus.read_jsonl(OUT, dedupe_on="text")
    if usage_rows:
        corpus.append_jsonl(ROOT / "data" / "usage.jsonl", usage_rows)

    if errors:
        (GEN / "batch-errors.jsonl").write_text(
            "\n".join(json.dumps(e) for e in errors) + "\n")

    print(json.dumps({
        "job_status": status,
        "per_request_errors": len(errors),
        "written_this_run": len(results),
        "unparseable_responses": failures,
        "terms_not_found_in_text": unmatched_total,
        "annotated_total": len(total),
        "sentences_total": len(corpus.read_jsonl(SENTENCES, dedupe_on="text")),
        "prompt_tokens": prompt_tok,
        "completion_tokens": completion_tok,
        "avg_completion_per_sentence": round(completion_tok / max(1, len(results)), 1),
    }, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-key", help="overrides TOGETHER_API_KEY and 1Password")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit", help="upload requests and create the batch job")
    # Llama-3.3-70B is chosen for two reasons, in this order of importance:
    #  1. it is NOT a reasoning model, so it emits ~15 completion tokens per
    #     sentence instead of the ~615 a reasoning model spends (604 of which are
    #     reasoning). That is the dominant cost term on this workload.
    #  2. it is one of only two models Together actually discounts 50% on batch;
    #     everything else runs at standard rates.
    # It is also a different family from the DeepSeek generator, as required.
    s.add_argument("--model", default="meta-llama/Llama-3.3-70B-Instruct-Turbo",
                   help="MUST differ in family from the generator")
    s.add_argument("--limit", type=int)
    s.set_defaults(func=cmd_submit)

    sub.add_parser("status", help="poll the job").set_defaults(func=cmd_status)
    sub.add_parser("fetch", help="download results and merge them").set_defaults(
        func=cmd_fetch)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
