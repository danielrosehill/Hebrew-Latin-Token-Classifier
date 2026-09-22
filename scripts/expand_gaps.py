#!/usr/bin/env python3
"""Round 2 — generate candidate terms for the categories round 1 barely attempted.

Terms first, sentences second. Round 1 showed that a junk term is expensive: it
costs three generated sentences, a blind annotation pass and a review decision
before it is removed. Judging terms directly is far cheaper, so this produces
candidates for review and nothing else. Sentences are generated only for
survivors.

Two corrections to round 1 are built in. Categories with a 0% drop rate and a
handful of terms were not high quality, they were barely attempted, so they get
the budget. Categories with 50-57% drop rates keep their register but get a
higher bar and are seeded with their own survivors as few-shot examples.

    python3 scripts/expand_gaps.py
    python3 scripts/expand_gaps.py --per-category 30

Output: data/terms-round2.csv (candidates only, nothing merged yet)
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
STAGE = "expand_gaps"

from lib import llm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
TERMS = ROOT / "data" / "terms.csv"
CORPUS = ROOT / "data" / "corpus"
EXCLUSIONS = ROOT / "data" / "exclusions.csv"
OUT = ROOT / "data" / "terms-round2.csv"

# Categories round 1 left nearly empty, plus domains it never had at all.
GAPS = {
    "government": "government ministries, authorities and the offices people deal with",
    "finance": "banking, tax, pensions, insurance and money admin",
    "shopping": "shops, chains, checkouts and the mechanics of buying things",
    "religious": "religious life, life-cycle events and observance",
    "education": "schools, kindergartens, university, exams and teachers",
    "military": "army service, reserves, units, ranks and the draft",
    "documents": "forms, permits, certificates and official paperwork",
    "work": "employment, payslips, contracts, hiring and firing",
    "family": "family relationships, life events and how people refer to relatives",
    "immigration": "aliyah, absorption, visas and new-immigrant bureaucracy",
    "childcare": "nurseries, childminders, after-school care and parenting logistics",
    "emergency": "emergencies, sirens, shelters, ambulances and first response",
    "legal": "lawyers, courts, contracts, disputes and legal process",
    "real_estate": "renting and buying property, landlords, agents and leases",
    "vehicles": "cars, the annual test, garages, licensing, fuel and parking fines",
    "telecoms": "phone, internet, cable and the companies that sell them",
    "municipality": "the local council, rates, permits, rubbish and neighbourhood services",
    "pharmacy_post": "pharmacies, prescriptions, the post office and deliveries",
    "time_weather": "times of day, days of the week, seasons and weather",
    "leisure": "sport, holidays, going out, beaches and the outdoors",
}

# Kept, with a higher bar and their own survivors as few-shot.
REFINE = {
    "colloquial": "everyday slang and conversational filler",
    "food_shopping": "food, markets and eating",
}

SYSTEM = """You list Hebrew words that English-speakers living in Israel use \
untranslated when speaking English, written in Latin characters using the spelling \
Israelis actually use.

The only test that matters: would an English text-to-speech voice MISPRONOUNCE this \
word? The canonical example is "makolet" — a corner shop, said constantly, in no \
English corpus, and every model gets it wrong.

Exclude, without exception:
- Words English has absorbed and says acceptably: kosher, shabbat, kashrut, challah, \
hummus, tahini, falafel, pita, bagel, rabbi, yeshiva, kibbutz, chutzpah, torah, \
seder, hanukkah, sukkot, shiva, menorah, mitzvah, knesset, shekel, aliyah.
- Foreign foods that are not Hebrew: merguez, taramosalata, ful medames, baklava.
- Place names, street names and people's names.
- Hebrew particles and pronouns: od, po, ma, mi, lo, ken, at, ani, ach.
- Greetings and interjections unless they are genuinely said untranslated in \
English sentences.

NEVER invent numbered series. Do not produce "tofes 1311", "tofes 1312" or any \
family of form numbers, channel numbers or code numbers. One generic term is right; \
a numbered family is fabrication.

Prefer concrete nouns and fixed phrases people actually say over abstract or \
literary vocabulary. Multi-word terms are welcome where the phrase is the unit."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["terms"],
    "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
}


def survivors_by_category() -> dict[str, list[str]]:
    """Terms that made it into the final corpus — the best available few-shot."""
    if not (CORPUS / "train.jsonl").exists():
        return {}
    terms = {r["term"]: r for r in csv.DictReader(TERMS.open())}
    out = collections.defaultdict(set)
    for split in ("train", "validation", "test"):
        path = CORPUS / f"{split}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            for s in json.loads(line)["spans"]:
                cat = (terms.get(s["term"].lower()) or {}).get("category")
                if cat:
                    out[cat].add(s["term"].lower())
    return {k: sorted(v) for k, v in out.items()}


def known_terms() -> set[str]:
    have = {r["term"].strip().lower() for r in csv.DictReader(TERMS.open())}
    if EXCLUSIONS.exists():
        have |= {r["term"].strip().lower() for r in csv.DictReader(EXCLUSIONS.open())}
    if OUT.exists():
        have |= {r["term"].strip().lower() for r in csv.DictReader(OUT.open())}
    return have


async def main_async(args) -> None:
    have = known_terms()
    survivors = survivors_by_category()
    jobs = [(c, d, False) for c, d in GAPS.items()] + \
           [(c, d, True) for c, d in REFINE.items()]
    print(f"{len(have)} terms already known; asking for {args.per_category} "
          f"each across {len(jobs)} categories")

    key = llm.api_key(llm.provider_for(args.model, args.provider), args.api_key)
    async with llm.Client(args.model, provider=args.provider, key=key,
                          concurrency=args.concurrency, stage=STAGE) as client:
        async def ask(category: str, guidance: str, refine: bool):
            shots = survivors.get(category, [])[:25]
            msg = [f"Domain: {guidance}."]
            if shots:
                msg.append("Terms of exactly the right kind, already collected — "
                           "match this calibre and do NOT repeat them: "
                           + ", ".join(shots))
            if refine:
                msg.append("Half of an earlier attempt at this domain was rejected "
                           "as too obvious, anglicised or not really a word people "
                           "say. Be stricter than you would otherwise be.")
            msg.append(f"List {args.per_category + 15} terms.")
            return await client.json_completion(SYSTEM, "\n\n".join(msg), SCHEMA)

        results = await asyncio.gather(
            *[ask(c, d, r) for c, d, r in jobs], return_exceptions=True)

    rows, added = [], 0
    for (category, _, _), result in zip(jobs, results):
        if isinstance(result, Exception):
            print(f"  {category}: failed — {result}", file=sys.stderr)
            continue
        kept = 0
        for raw in result.get("terms", []):
            term = " ".join(str(raw).split()).lower()
            if not term or term in have:
                continue
            have.add(term)
            rows.append({"term": term, "category": category, "status": "candidate",
                         "quarantine_reason": "", "hebrew_script": "",
                         "source": f"round2:{args.model}"})
            kept += 1
            added += 1
        print(f"  {category:<16} +{kept}")

    if not rows:
        print("nothing new")
        return
    existing = list(csv.DictReader(OUT.open())) if OUT.exists() else []
    allrows = existing + rows
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(allrows[0]))
        w.writeheader()
        w.writerows(sorted(allrows, key=lambda r: (r["category"], r["term"])))
    print(json.dumps({"new_candidates": added, "total_in_file": len(allrows),
                      "output": str(OUT.relative_to(ROOT))}, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--per-category", type=int, default=28)
    p.add_argument("--model", default="deepseek-flash")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--provider", choices=["deepseek", "openrouter"])
    p.add_argument("--api-key")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
