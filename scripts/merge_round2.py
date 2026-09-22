#!/usr/bin/env python3
"""Merge the round-2 term decisions into data/terms.csv, collapsing spellings.

Two jobs:

1. Add the terms Daniel kept, drop the ones he rejected.

2. Collapse spelling variants onto one canonical form. The inventory already
   carried the same word twice under different spellings -- "ba'al bayit" and
   "baal bayit", "choze" and "chozeh", "do'ach" and "doach" -- which would have
   trained the classifier on two unrelated-looking terms and split their
   examples. Terms that normalise to the same key become one entry, with the
   others recorded in a `variants` column.

The canonical spelling is the one WITHOUT an apostrophe where a choice exists:
it is what people actually type, so it is what the classifier will mostly see.
The careful spelling is kept as a variant, not discarded.

    python3 scripts/merge_round2.py --write

Writes data/terms.csv (backup at terms.csv.bak).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib.orthography import APOSTROPHES, normalise, variants  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
TERMS = ROOT / "data" / "terms.csv"
ROUND2 = ROOT / "data" / "terms-round2.csv"
DECISIONS = ROOT / "review" / "decisions-terms.json"
EXCLUSIONS = ROOT / "data" / "exclusions.csv"

FIELDS = ["term", "category", "status", "quarantine_reason", "hebrew_script",
          "source", "variants"]


def canonical_of(group: list[dict]) -> dict:
    """Prefer no apostrophe, then the shorter form, then alphabetical."""
    return sorted(group, key=lambda r: (any(c in r["term"] for c in APOSTROPHES),
                                        len(r["term"]), r["term"]))[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    existing = list(csv.DictReader(TERMS.open()))
    cands = {r["term"]: r for r in csv.DictReader(ROUND2.open())}
    decisions = json.loads(DECISIONS.read_text())
    excluded = ({r["term"].strip().lower() for r in csv.DictReader(EXCLUSIONS.open())}
                if EXCLUSIONS.exists() else set())

    kept, rejected = [], 0
    for key, value in decisions.items():
        term = key[3:]
        if value.get("deferred") or not value.get("include", value.get("hebrew")):
            rejected += 1
            continue
        row = cands.get(term)
        if not row or term in excluded:
            continue
        kept.append({"term": term, "category": row["category"], "status": "active",
                     "quarantine_reason": "", "hebrew_script": "",
                     "source": row["source"], "variants": ""})

    pool = [{**r, "variants": r.get("variants", "")} for r in existing] + kept
    pool = [r for r in pool if r["term"].strip().lower() not in excluded]

    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for r in pool:
        groups[normalise(r["term"])].append(r)

    merged, collapsed = [], 0
    for _, group in sorted(groups.items()):
        uniq = {r["term"]: r for r in group}
        chosen = canonical_of(list(uniq.values()))
        others = sorted(t for t in uniq if t != chosen["term"])
        # generated variants are written too, so the lexicon can match what people
        # type rather than only what was collected
        generated = [v for v in variants(chosen["term"]) if v not in uniq]
        chosen = {**chosen, "variants": "|".join(others + generated)}
        if others:
            collapsed += len(others)
        merged.append(chosen)

    merged.sort(key=lambda r: (r["category"], r["term"]))
    active = sum(1 for r in merged if r["status"] == "active")
    with_variants = sum(1 for r in merged if r["variants"])

    print(json.dumps({
        "round2_kept": len(kept), "round2_rejected": rejected,
        "before": len(existing), "after": len(merged),
        "spellings_collapsed": collapsed,
        "active": active,
        "terms_with_variants": with_variants,
        "variant_forms": sum(len(r["variants"].split("|")) for r in merged if r["variants"]),
    }, indent=1))

    if not args.write:
        print("\ndry run — pass --write to apply")
        return
    shutil.copy(TERMS, TERMS.with_suffix(".csv.bak"))
    with TERMS.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(merged)
    print(f"\nwrote {TERMS.relative_to(ROOT)} (backup at terms.csv.bak)")


if __name__ == "__main__":
    main()
