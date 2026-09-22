#!/usr/bin/env python3
"""Generate hard negatives — English sentences with no Hebrew span.

Precision is weighted over recall (a miss changes nothing; a false positive makes
an English word be read in Hebrew), so the negative classes get real budget and
are generated deliberately rather than left to chance.

Four kinds, each answering a specific way the classifier will be wrong:

  english_sense   the English meaning of a term that is also Hebrew — "that
                  battery was a dud", "book a salon appointment". Paired with the
                  Hebrew-sense positives from generate_samples.py, these are the
                  only thing that can teach the distinction.
  anglicised      Hebrew words English already says acceptably — kosher, Shabbat,
                  hummus, rabbi, kibbutz, chutzpah. Tagging them would break
                  output that currently works.
  lookalike       words that look Hebrew but are not — chalet, shaman, sheikh,
                  bazaar, cholera.
  substring_trap  sentences containing think, Pharm, moshav, mazgan, machsom,
                  school. These are the exact strings that corrupted the
                  predecessor dataset's labels by substring matching.

Resumable and appends to the same file the positives go to, tagged seed_term null.

    python3 scripts/generate_negatives.py --per-kind 125

Output: data/generated/sentences.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
STAGE = "negatives"

from lib import corpus, llm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "sentences.jsonl"

SYSTEM = """You write natural English sentences for a speech-technology training \
corpus. Every sentence you write must contain NO Hebrew words at all.

Write how people actually speak. Vary length, register and tense."""

PROMPTS = {
    "english_sense": """Use the word "{item}" in its ordinary ENGLISH meaning only. \
This word also exists in Hebrew, and the point of these sentences is the English \
sense, so nothing about them should suggest Israel, Hebrew or Jewish life.

Write {n} sentences.""",

    "anglicised": """Use the word "{item}". It is Hebrew in origin but English has \
fully absorbed it and pronounces it acceptably, so it counts as English here.

Write {n} ordinary English sentences containing it.""",

    "lookalike": """Use the word "{item}". It is not Hebrew, though it may look or \
sound as if it could be.

Write {n} ordinary English sentences containing it.""",

    "substring_trap": """Write {n} ordinary English sentences containing the word \
"{item}". No Hebrew anywhere in them.""",
}

ANGLICISED = ["kosher", "Shabbat", "hummus", "rabbi", "kibbutz", "chutzpah", "bagel",
              "falafel", "matzo", "menorah", "synagogue", "Hanukkah", "Passover",
              "schmooze", "klutz", "bagels", "pita", "tahini"]
LOOKALIKE = ["chalet", "shaman", "sheikh", "bazaar", "cholera", "chalice", "sherbet",
             "safari", "khaki", "mocha", "chai", "chateau", "shallot", "mahogany"]
TRAPS = ["think", "thinking", "pharmacy", "school", "schooling", "harbour", "harmony",
         "machine", "machinery", "supermarket", "supermarkets", "chicken soup",
         "matter", "manager", "mistake", "kennel", "baby", "lobby", "atlas"]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sentences"],
    "properties": {"sentences": {"type": "array", "items": {"type": "string"}}},
}


def ambiguous_terms(path: pathlib.Path) -> list[str]:
    with path.open() as fh:
        return [r["term"] for r in csv.DictReader(fh) if r.get("status") == "ambiguous"]


def build_jobs(terms_path: pathlib.Path, per_kind: int) -> list[tuple[str, str, int]]:
    pools = {
        "english_sense": ambiguous_terms(terms_path),
        "anglicised": ANGLICISED,
        "lookalike": LOOKALIKE,
        "substring_trap": TRAPS,
    }
    jobs = []
    for kind, pool in pools.items():
        if not pool:
            print(f"  {kind}: no items, skipping", file=sys.stderr)
            continue
        per_item = max(1, round(per_kind / len(pool)))
        jobs += [(kind, item, per_item) for item in pool]
    return jobs


async def one_job(client, kind: str, item: str, n: int, lexicon: set[str]) -> list[dict]:
    result = await client.json_completion(
        SYSTEM, PROMPTS[kind].format(item=item, n=n), SCHEMA)
    rows, rejected = [], 0
    for text in result.get("sentences", []):
        text = " ".join(text.split())
        # A "negative" that contains a known Hebrew term is not a negative.
        # Reject rather than mislabel — this is the defect the whole repo exists around.
        if any(corpus.word_spans(text, t) for t in lexicon):
            rejected += 1
            continue
        rows.append({
            "text": text,
            "seed_term": None,
            "seed_category": f"negative:{kind}",
            "seed_spans": [],
            "negative_item": item,
            "generator": client.model,
        })
    if rejected:
        print(f"  {kind}/{item}: rejected {rejected} (contained a lexicon term)",
              file=sys.stderr)
    return rows


async def main_async(args) -> None:
    terms_path = pathlib.Path(args.terms)
    with terms_path.open() as fh:
        lexicon = {r["term"] for r in csv.DictReader(fh)
                   if r.get("status") == "active" and len(r["term"]) > 3}

    existing = corpus.read_jsonl(OUT, dedupe_on="text")
    done = collections.Counter(r.get("negative_item") for r in existing
                               if r.get("seed_term") is None)
    jobs = [(k, i, n) for k, i, n in build_jobs(terms_path, args.per_kind)
            if done[i] < n]
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"{len(jobs)} negative jobs pending, model {args.model}")
    if not jobs:
        return

    key = llm.api_key(llm.provider_for(args.model, args.provider), args.api_key)
    written = 0
    async with llm.Client(args.model, provider=args.provider, key=key,
                          concurrency=args.concurrency, stage=STAGE) as client:
        tasks = [one_job(client, k, i, n, lexicon) for k, i, n in jobs]
        for idx, coro in enumerate(asyncio.as_completed(tasks), 1):
            try:
                rows = await coro
            except llm.LLMError as e:
                print(f"  failed: {e}", file=sys.stderr)
                continue
            corpus.append_jsonl(OUT, rows)
            written += len(rows)
            if idx % 20 == 0 or idx == len(tasks):
                print(f"  {idx}/{len(tasks)} jobs, {written} sentences")

    total = corpus.read_jsonl(OUT, dedupe_on="text")
    negatives = [r for r in total if r.get("seed_term") is None]
    print(json.dumps({
        "sentences_total": len(total),
        "negatives_total": len(negatives),
        "by_kind": dict(collections.Counter(r["seed_category"] for r in negatives)),
        "written_this_run": written,
    }, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--terms", default=str(ROOT / "data" / "terms.csv"))
    p.add_argument("--model", default="deepseek-flash")
    p.add_argument("--per-kind", type=int, default=125)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--limit", type=int)
    p.add_argument("--provider", choices=["deepseek", "openrouter"],
                   help="inferred from the model name if omitted")
    p.add_argument("--api-key")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
