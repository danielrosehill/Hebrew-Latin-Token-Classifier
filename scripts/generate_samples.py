#!/usr/bin/env python3
"""Stage 1 — generate term-seeded sentences via OpenRouter.

Term-seeded rather than free-form: the model is given one Hebrew term and asked
for sentences using it. That guarantees term coverage and category balance, and
it makes the span known by construction — a generation in which the seed term
does not word-boundary match is rejected here and never reaches the corpus.

Resumable: output is appended, and terms already present are skipped, so an
interrupted run continues where it stopped.

    python3 scripts/generate_samples.py --terms data/terms.csv --per-term 3
    python3 scripts/generate_samples.py --model anthropic/claude-sonnet-5:batch

`:batch` model variants cost half as much and are the right default for a corpus
build; see docs/data-plan.md.

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
from lib import corpus, openrouter  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "sentences.jsonl"

SYSTEM = """You write natural English sentences that an Israeli English-speaker \
would plausibly say or write, for a speech-technology training corpus.

Rules:
- Each sentence must contain the given Hebrew term, written in Latin characters, \
spelled EXACTLY as given. Do not translate it, gloss it, or put it in quotes.
- The rest of the sentence is ordinary English. Do not explain the term.
- Vary sentence length, register, tense and grammatical role of the term across \
the set. Include at least one question and one short conversational fragment.
- Write how people actually speak, not how a textbook describes a culture."""

USER = """Hebrew term: {term}
Category: {category}
Write {n} different English sentences containing it."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sentences"],
    "properties": {
        "sentences": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
}


def load_terms(path: pathlib.Path) -> list[dict]:
    with path.open() as fh:
        rows = [r for r in csv.DictReader(fh)]
    keep = [r for r in rows if r.get("status", "active") == "active"]
    if not keep:
        raise SystemExit(f"{path} has no active terms")
    return keep


async def one_term(client, term: dict, per_term: int) -> list[dict]:
    result = await client.json_completion(
        SYSTEM,
        USER.format(term=term["term"], category=term.get("category") or "general",
                    n=per_term),
        SCHEMA,
    )
    rows, rejected = [], 0
    for text in result.get("sentences", []):
        text = " ".join(text.split())
        spans = corpus.word_spans(text, term["term"])
        if not spans:
            rejected += 1          # seed term absent: the source dataset's defect
            continue
        rows.append({
            "text": text,
            "seed_term": term["term"],
            "seed_category": term.get("category") or "general",
            "seed_spans": [{"start": s, "end": e, "surface": text[s:e],
                            "term": term["term"]} for s, e in spans],
            "generator": client.model,
        })
    if rejected:
        print(f"  {term['term']}: rejected {rejected} (seed term absent)", file=sys.stderr)
    return rows


async def main_async(args) -> None:
    terms = load_terms(pathlib.Path(args.terms))
    done = collections.Counter(r["seed_term"] for r in corpus.read_jsonl(OUT))
    todo = [t for t in terms if done[t["term"]] < args.per_term]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(terms)} active terms, {len(todo)} to generate, model {args.model}")
    if not todo:
        return

    key = openrouter.api_key(args.api_key)
    written = 0
    async with openrouter.Client(args.model, key, concurrency=args.concurrency) as client:
        tasks = [one_term(client, t, args.per_term) for t in todo]
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            try:
                rows = await coro
            except openrouter.OpenRouterError as e:
                print(f"  failed: {e}", file=sys.stderr)
                continue
            corpus.append_jsonl(OUT, rows)
            written += len(rows)
            if i % 25 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} terms, {written} sentences")

    total = corpus.read_jsonl(OUT)
    print(json.dumps({
        "sentences_total": len(total),
        "distinct_terms": len({r["seed_term"] for r in total}),
        "written_this_run": written,
        "output": str(OUT.relative_to(ROOT)),
    }, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--terms", default=str(ROOT / "data" / "terms.csv"))
    p.add_argument("--model", default="anthropic/claude-sonnet-5:batch")
    p.add_argument("--per-term", type=int, default=3)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--limit", type=int, help="only process the first N pending terms")
    p.add_argument("--api-key", help="override OPENROUTER_API_KEY")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
