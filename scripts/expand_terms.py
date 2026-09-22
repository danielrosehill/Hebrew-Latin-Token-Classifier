#!/usr/bin/env python3
"""Stage 0 — build data/terms.csv, the term inventory that seeds generation.

Starts from the active terms already in data/lexicon.csv, then asks a model for
more terms per register until the per-category target is met. Category balance is
deliberate: the vendored corpus is skewed to the institutional and religious
register, which is the half an English voice half-copes with. The half that
actually fails is colloquial.

New terms are deduplicated case-insensitively and screened against the system
English wordlist, so a proposal that is also an ordinary English word is recorded
as quarantined rather than silently seeded.

    python3 scripts/expand_terms.py --target 500

Output: data/terms.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib import llm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAGE = "expand_terms"
LEXICON = ROOT / "data" / "lexicon.csv"
OUT = ROOT / "data" / "terms.csv"
WORDLISTS = ["/usr/share/dict/american-english", "/usr/share/dict/words"]

# share of the inventory, per docs/data-plan.md
TARGETS = {
    "colloquial": 0.25,
    "bureaucracy": 0.20,
    "food_shopping": 0.15,
    "home_utilities": 0.10,
    "health": 0.10,
    "religious_calendar": 0.10,
    "transport_geography": 0.10,
}

GUIDANCE = {
    "colloquial": "everyday slang and conversational filler: balagan, beseder, sababa, "
                  "yalla, freier, chevre, stam, achla",
    "bureaucracy": "government, tax, banking and paperwork: bituach leumi, mas hachnasa, "
                   "teudat zehut, osek patur, arnona, mashkanta",
    "food_shopping": "food, shops and markets: makolet, sabich, shuk, cholent, malawach",
    "home_utilities": "the home and its utilities: dud, mazgan, mamad, hashmal, mayim, machsan",
    "health": "health, clinics and medicine: kupat cholim, mirsham, tor, miluim",
    "religious_calendar": "religious life and the calendar: chagim, motzash, brit milah, seudah",
    "transport_geography": "getting around: rakevet, sherut, pkak, machsom, tachana",
}

SYSTEM = """You list Hebrew words that Israeli English-speakers use, untranslated, \
when speaking English — written in Latin characters using the spelling Israelis \
actually use, not an academic romanization.

Only include words an English text-to-speech voice would mispronounce. Exclude words \
English has absorbed and says acceptably: kosher, Shabbat, hummus, rabbi, kibbutz, \
chutzpah, bagel, falafel.

Prefer words in ordinary daily use over literary or liturgical vocabulary. Multi-word \
terms are welcome where the phrase is the unit people say."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["terms"],
    "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
}


def english_vocabulary() -> set[str]:
    for path in WORDLISTS:
        p = pathlib.Path(path)
        if p.exists():
            return {w.strip().lower() for w in p.read_text(errors="ignore").splitlines()
                    if w.strip() and "'" not in w}
    return set()


def load_existing() -> dict[str, dict]:
    if OUT.exists():
        with OUT.open() as fh:
            return {r["term"]: r for r in csv.DictReader(fh)}
    rows = {}
    if LEXICON.exists():
        with LEXICON.open() as fh:
            for r in csv.DictReader(fh):
                if r["status"] != "active":
                    continue
                rows[r["term"]] = {
                    "term": r["term"],
                    "category": r["category"] or "general",
                    "status": "active",
                    "quarantine_reason": "",
                    "hebrew_script": "",
                    "source": "english-hebrew-mixed-sentences",
                }
    return rows


async def main_async(args) -> None:
    english = english_vocabulary()
    terms = load_existing()
    print(f"starting from {len(terms)} terms")

    key = llm.api_key(llm.provider_for(args.model, args.provider), args.api_key)
    async with llm.Client(args.model, provider=args.provider, key=key, concurrency=len(TARGETS), stage="expand_terms") as client:
        async def fill(category: str, want: int) -> list[str]:
            have = [t for t, r in terms.items() if r["category"] == category]
            need = want - len(have)
            if need <= 0:
                return []
            result = await client.json_completion(
                SYSTEM,
                f"Register: {GUIDANCE[category]}\n\n"
                f"List {need + 20} such terms. Do not repeat any of these, which I "
                f"already have: {', '.join(sorted(terms)[:400])}",
                SCHEMA,
            )
            return result.get("terms", [])

        results = await asyncio.gather(*[
            fill(c, round(args.target * share)) for c, share in TARGETS.items()
        ], return_exceptions=True)

    added = 0
    for category, result in zip(TARGETS, results):
        if isinstance(result, Exception):
            print(f"  {category}: failed — {result}", file=sys.stderr)
            continue
        for raw in result:
            term = " ".join(raw.split()).lower()
            if not term or term in terms:
                continue
            homograph = all(w in english for w in term.split())
            terms[term] = {
                "term": term,
                "category": category,
                "status": "quarantined" if homograph else "active",
                "quarantine_reason": "english_homograph" if homograph else "",
                "hebrew_script": "",
                "source": f"generated:{args.model}",
            }
            added += 1

    rows = sorted(terms.values(), key=lambda r: (r["category"], r["term"]))
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    active = sum(1 for r in rows if r["status"] == "active")
    by_cat = {c: sum(1 for r in rows if r["category"] == c) for c in
              sorted({r["category"] for r in rows})}
    print(json.dumps({"total": len(rows), "active": active, "added_this_run": added,
                      "by_category": by_cat,
                      "output": str(OUT.relative_to(ROOT))}, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", type=int, default=500)
    p.add_argument("--model", default="deepseek-flash")
    p.add_argument("--provider", choices=["deepseek", "openrouter"],
                   help="inferred from the model name if omitted")
    p.add_argument("--api-key")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
