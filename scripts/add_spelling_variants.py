#!/usr/bin/env python3
"""Teach the classifier spelling robustness, without generating a single token.

There is no settled romanization of Hebrew, and the spelling people type is
rarely the careful one: "ma'alit" is more correct, almost everyone writes
"maalit". A corpus containing only one spelling trains a model that misses the
other.

The fix needs no model. Take a sentence already in the corpus, substitute a
variant spelling into the span, and keep everything else identical. The sentence
was already good and the span offsets are recomputed exactly, so the result is as
clean as the original and costs nothing.

Two rules keep it honest:

  Variant copies stay in the SOURCE SENTENCE'S SPLIT. A near-duplicate across the
  train/test boundary would let the model score on a sentence it had memorised.

  No variant that collides with a real term in the inventory is used. If two
  words are genuinely ambiguous in writing, guessing between them is worse than
  not matching.

    python3 scripts/add_spelling_variants.py --write

Rewrites data/corpus/{train,validation,test}.jsonl in place (backups alongside).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib
import random
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib import corpus  # noqa: E402
from lib.orthography import variants as spelling_variants  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
TERMS = ROOT / "data" / "terms.csv"
SPLITS = ("train", "validation", "test")


def load_variant_map() -> dict[str, list[str]]:
    rows = list(csv.DictReader(TERMS.open()))
    canonical = {r["term"].strip().lower() for r in rows}
    out: dict[str, list[str]] = {}
    for r in rows:
        term = r["term"].strip().lower()
        listed = [v for v in (r.get("variants") or "").split("|") if v]
        for v in listed + spelling_variants(term):
            if v in canonical or v == term:
                continue          # genuinely ambiguous, or not a variant at all
            out.setdefault(term, [])
            if v not in out[term]:
                out[term].append(v)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-term", type=int, default=1,
                    help="variant copies to add per term per split")
    ap.add_argument("--seed", type=int, default=20260922)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    vmap = load_variant_map()
    rng = random.Random(args.seed)
    stats: collections.Counter[str] = collections.Counter()
    added_terms: collections.Counter[str] = collections.Counter()
    output: dict[str, list[dict]] = {}

    for split in SPLITS:
        path = CORPUS / f"{split}.jsonl"
        if not path.exists():
            continue
        rows = corpus.read_jsonl(path)
        existing = {r["text"] for r in rows}
        # group candidate sentences by the term whose spelling we could vary
        by_term: dict[str, list[dict]] = collections.defaultdict(list)
        for r in rows:
            for s in r["spans"]:
                if s["term"].lower() in vmap:
                    by_term[s["term"].lower()].append(r)

        new_rows = []
        for term, candidates in sorted(by_term.items()):
            forms = vmap[term]
            picks = rng.sample(candidates, min(args.per_term, len(candidates)))
            for n, src in enumerate(picks):
                form = forms[n % len(forms)]
                target = next((s for s in src["spans"] if s["term"].lower() == term), None)
                if target is None:
                    continue
                text = (src["text"][:target["start"]] + form
                        + src["text"][target["end"]:])
                if text in existing:
                    stats["skipped_duplicate"] += 1
                    continue
                shift = len(form) - (target["end"] - target["start"])
                spans = []
                ok = True
                for s in src["spans"]:
                    if s is target:
                        spans.append({"start": s["start"],
                                      "end": s["start"] + len(form),
                                      "surface": form, "term": term})
                    elif s["start"] >= target["end"]:
                        spans.append({**s, "start": s["start"] + shift,
                                      "end": s["end"] + shift})
                    elif s["end"] <= target["start"]:
                        spans.append(dict(s))
                    else:
                        ok = False          # overlaps the edit; do not guess
                        break
                if not ok:
                    stats["skipped_overlap"] += 1
                    continue
                # verify every span still lands on its surface after the edit
                if any(text[s["start"]:s["end"]].lower() != s["surface"].lower()
                       for s in spans):
                    stats["skipped_misaligned"] += 1
                    continue
                spans.sort(key=lambda s: s["start"])
                existing.add(text)
                new_rows.append({
                    "id": f"{src['id']}v{n}", "text": text,
                    "seed_term": src["seed_term"], "category": src["category"],
                    "spans": spans, "tokens": corpus.bio_tags(text, spans),
                    "spelling_variant_of": src["id"],
                })
                stats[f"added_{split}"] += 1
                added_terms[term] += 1

        output[split] = rows + new_rows

    print(json.dumps({
        "terms_with_usable_variants": len(vmap),
        "sentences_added": {s: stats[f"added_{s}"] for s in SPLITS},
        "total_added": sum(stats[f"added_{s}"] for s in SPLITS),
        "distinct_terms_covered": len(added_terms),
        "skipped": {k: v for k, v in stats.items() if k.startswith("skipped")},
        "new_totals": {s: len(v) for s, v in output.items()},
    }, indent=1))

    if not args.write:
        print("\ndry run — pass --write to apply")
        return
    for split, rows in output.items():
        path = CORPUS / f"{split}.jsonl"
        shutil.copy(path, path.with_suffix(".jsonl.bak"))
        corpus.write_jsonl(path, rows)
    print(f"\nrewrote {', '.join(SPLITS)} (backups alongside)")


if __name__ == "__main__":
    main()
