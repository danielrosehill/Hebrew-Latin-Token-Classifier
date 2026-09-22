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
from lib import corpus, openrouter  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
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
    "required": ["terms"],
    "properties": {
        "terms": {"type": "array", "items": {"type": "string"}},
    },
}


def row_key(row: dict) -> str:
    return row["text"]


async def one_row(client, row: dict) -> dict:
    result = await client.json_completion(
        SYSTEM, f"Sentence: {row['text']}", SCHEMA, temperature=0.0)
    spans, unmatched = [], []
    for term in result.get("terms", []):
        found = corpus.word_spans(row["text"], term)
        if not found:
            unmatched.append(term)      # hallucinated or paraphrased: never silently kept
            continue
        s, e = found[0]
        spans.append({"start": s, "end": e, "surface": row["text"][s:e],
                      "term": term.lower()})
    spans.sort(key=lambda s: s["start"])
    return {
        "text": row["text"],
        "annotator": client.model,
        "spans": spans,
        "unmatched_terms": unmatched,
    }


async def main_async(args) -> None:
    rows = corpus.read_jsonl(SENTENCES)
    if not rows:
        raise SystemExit(f"no sentences at {SENTENCES.relative_to(ROOT)} — run "
                         f"scripts/generate_samples.py first")
    done = {row_key(r) for r in corpus.read_jsonl(OUT)}
    todo = [r for r in rows if row_key(r) not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(rows)} sentences, {len(todo)} to annotate, model {args.model}")
    if not todo:
        return

    key = openrouter.api_key(args.api_key)
    written = 0
    async with openrouter.Client(args.model, key, concurrency=args.concurrency) as client:
        tasks = [one_row(client, r) for r in todo]
        batch = []
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            try:
                batch.append(await coro)
            except openrouter.OpenRouterError as e:
                print(f"  failed: {e}", file=sys.stderr)
                continue
            if len(batch) >= 20 or i == len(tasks):
                corpus.append_jsonl(OUT, batch)
                written += len(batch)
                batch = []
                print(f"  {i}/{len(tasks)} annotated")

    all_rows = corpus.read_jsonl(OUT)
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
    p.add_argument("--model", default="google/gemini-3.8-flash",
                   help="MUST differ in family from the generator")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--limit", type=int)
    p.add_argument("--api-key")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
