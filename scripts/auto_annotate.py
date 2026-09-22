#!/usr/bin/env python3
"""Stage 2 — annotate every Hebrew span, blind, with a second model.

The annotator is NOT told the seed term, and SHOULD be a different model family
from the generator. Two passes from one model agreeing proves the model is
consistent, not that it is right; agreement only counts as evidence when the
second pass is independent.

This pass is also what catches incidental terms the seeding did not intend: a
sentence seeded with "arnona" that happens to also contain "iriyah" comes back
with both, and the disagreement goes to a human.

Resumable: rows already annotated are skipped.

    python3 scripts/auto_annotate.py --model google/gemini-2.5-flash

Output: data/generated/annotations.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib import corpus, llm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAGE = "annotate"
SENTENCES = ROOT / "data" / "generated" / "sentences.jsonl"
OUT = ROOT / "data" / "generated" / "annotations.jsonl"

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

Do NOT label:
- Hebrew words English has absorbed and pronounces acceptably: kosher, Shabbat, \
hummus, rabbi, kibbutz, chutzpah, bagel, falafel.
- Ordinary English words, even if they look like a Hebrew word: at, hi, lo, ken, ma, mi.
- Strings that only appear INSIDE a longer English word. "think" does not contain \
Hebrew "hi"; "Pharm" does not contain "har"; "school" does not contain "chool".
- Well-known place names and people: Tel Aviv, Jerusalem, Netanyahu.

Copy each term EXACTLY as it appears in the sentence, preserving case. If there are \
no Hebrew words, return an empty list. Do not explain."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["results"],
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "terms"],
                "properties": {
                    "index": {"type": "integer"},
                    "terms": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

BATCH_INSTRUCTION = """You will be given several numbered sentences. Return one \
result per sentence, echoing its index. Every index must appear exactly once, \
including sentences with no Hebrew words (return an empty list for those)."""


def row_key(row: dict) -> str:
    return row["text"]


def _spans_for(text: str, terms: list[str]) -> tuple[list[dict], list[str]]:
    spans, unmatched = [], []
    for term in terms:
        found = corpus.word_spans(text, term)
        if not found:
            unmatched.append(term)   # hallucinated or paraphrased: never silently kept
            continue
        s, e = found[0]
        spans.append({"start": s, "end": e, "surface": text[s:e], "term": term.lower()})
    spans.sort(key=lambda s: s["start"])
    return spans, unmatched


async def one_batch(client, rows: list[dict], *, depth: int = 0) -> list[dict]:
    """Annotate several sentences in one call.

    Reasoning tokens dominate this workload -- measured at 604 of 615 completion
    tokens per single-sentence call, i.e. ~11 tokens of actual answer. Batching
    amortises one reasoning preamble over N sentences and cuts both wall time and
    cost by roughly an order of magnitude.

    The risk batching introduces is misalignment: a result attached to the wrong
    sentence. Two guards. The model must echo each index, and any index it drops is
    retried rather than assumed empty. And every returned term must word-boundary
    match the sentence it was assigned to -- a misaligned batch fails that test
    loudly, so if most of a batch's terms do not match, the batch is split and
    retried instead of being written.
    """
    numbered = "\n".join(f"{i}. {r['text']}" for i, r in enumerate(rows))
    result = await client.json_completion(
        SYSTEM + "\n\n" + BATCH_INSTRUCTION, numbered, SCHEMA, temperature=0.0)

    by_index = {}
    for item in result.get("results", []):
        idx = item.get("index")
        if isinstance(idx, int) and 0 <= idx < len(rows):
            by_index[idx] = item.get("terms") or []

    missing = [i for i in range(len(rows)) if i not in by_index]

    out, proposed, unmatched_total = [], 0, 0
    for i, row in enumerate(rows):
        if i in missing:
            continue
        spans, unmatched = _spans_for(row["text"], by_index[i])
        proposed += len(spans) + len(unmatched)
        unmatched_total += len(unmatched)
        out.append({
            "text": row["text"],
            "annotator": client.model,
            "spans": spans,
            "unmatched_terms": unmatched,
            "batch_size": len(rows),
        })

    # A misaligned batch shows up as terms that do not occur in their sentence.
    misaligned = len(rows) > 1 and proposed >= 4 and unmatched_total / proposed > 0.4
    if misaligned and depth < 2:
        print(f"  batch looked misaligned ({unmatched_total}/{proposed} terms not in "
              f"their sentence) — splitting", file=sys.stderr)
        half = len(rows) // 2
        left, right = await asyncio.gather(
            one_batch(client, rows[:half], depth=depth + 1),
            one_batch(client, rows[half:], depth=depth + 1))
        return left + right

    if missing and depth < 2:
        out += await one_batch(client, [rows[i] for i in missing], depth=depth + 1)
    elif missing:
        print(f"  {len(missing)} sentences dropped by the model after retries",
              file=sys.stderr)
    return out


async def main_async(args) -> None:
    rows = corpus.read_jsonl(SENTENCES)
    if not rows:
        raise SystemExit(f"no sentences at {SENTENCES.relative_to(ROOT)} — run "
                         f"scripts/generate_samples.py first")
    done = {row_key(r) for r in corpus.read_jsonl(OUT, dedupe_on="text")}
    todo = [r for r in rows if row_key(r) not in done]
    if args.limit:
        todo = todo[: args.limit]
    generators = {r.get("generator", "") for r in rows}
    family = args.model.split("/")[-1].split("-")[0].lower()
    clash = sorted(g for g in generators if family and family in g.lower())
    if clash and not args.allow_same_family:
        raise SystemExit(
            f"annotator {args.model!r} shares a family with generator(s) {clash}.\n"
            f"Agreement between two passes of one model measures consistency, not "
            f"correctness. Pick another model, or pass --allow-same-family.")

    print(f"{len(rows)} sentences, {len(todo)} to annotate, model {args.model}")
    if not todo:
        return

    batches = [todo[i:i + args.batch_size] for i in range(0, len(todo), args.batch_size)]
    print(f"  {len(batches)} batches of up to {args.batch_size}")

    key = llm.api_key(llm.provider_for(args.model, args.provider), args.api_key)
    written = 0
    async with llm.Client(args.model, provider=args.provider, key=key,
                          concurrency=args.concurrency, stage=STAGE) as client:
        tasks = [one_batch(client, b) for b in batches]
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            try:
                results = await coro
            except llm.LLMError as e:
                print(f"  failed: {e}", file=sys.stderr)
                continue
            corpus.append_jsonl(OUT, results)
            written += len(results)
            if i % 10 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} batches, {written} sentences")

    all_rows = corpus.read_jsonl(OUT, dedupe_on="text")
    hallucinated = sum(len(r["unmatched_terms"]) for r in all_rows)
    print(json.dumps({
        "annotated_total": len(all_rows),
        "written_this_run": written,
        "terms_not_found_in_text": hallucinated,
        "output": str(OUT.relative_to(ROOT)),
    }, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="qwen/qwen3.8-flash",
                   help="MUST differ in model family from the generator")
    p.add_argument("--allow-same-family", action="store_true",
                   help="override the independence check (it exists for a reason)")
    p.add_argument("--batch-size", type=int, default=12,
                   help="sentences per call; reasoning tokens dominate, so batching "
                        "cuts cost and wall time by roughly an order of magnitude")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--limit", type=int)
    p.add_argument("--provider", choices=["deepseek", "openrouter"],
                   help="inferred from the model name if omitted")
    p.add_argument("--api-key")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
