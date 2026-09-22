#!/usr/bin/env python3
"""Build a term-only review queue from round-2 candidates.

Judging terms is an order of magnitude cheaper than judging spans: one keystroke,
no sentences generated, no annotation pass, no adjudication. Round 1 spent all
three on terms that were then thrown away.

Keys are prefixed `t2:` so these decisions can live alongside round 1's in the
same file without colliding, and the UI is pointed at a separate localStorage
store so an in-progress span review is not disturbed.

    python3 scripts/build_term_queue.py
    python3 scripts/publish_space.py --queue review/queue-terms.json --push

Output: review/queue-terms.json
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "data" / "terms-round2.csv"
DECISIONS = ROOT / "review" / "decisions-terms.json"
OUT = ROOT / "review" / "queue-terms.json"

NOTE = ("Would an English text-to-speech voice mispronounce this, the way it "
        "mangles 'makolet'? Include only if yes.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", default="heb-latn-terms-v1",
                   help="localStorage namespace for this pass")
    args = p.parse_args()

    if not CANDIDATES.exists():
        raise SystemExit("no data/terms-round2.csv — run scripts/expand_gaps.py")
    rows = list(csv.DictReader(CANDIDATES.open()))
    done = set(json.loads(DECISIONS.read_text())) if DECISIONS.exists() else set()

    queue = []
    for r in rows:
        key = f"t2:{r['term']}"
        if key in done:
            continue
        queue.append({
            "key": key, "kind": "term", "risk": "term",
            "id": key, "split": r["category"],
            "text": r["term"], "term": r["term"],
            "examples": [],
            "dataset_label": r["category"],
            "note": f"{r['category'].replace('_', ' ')} — {NOTE}",
        })

    # Group by category so the reviewer stays in one domain at a time rather than
    # context-switching every keystroke.
    queue.sort(key=lambda t: (t["split"], t["term"]))
    for t in queue:
        t["store"] = args.store

    OUT.write_text(json.dumps(queue, ensure_ascii=False, indent=1))
    by_cat = collections.Counter(t["split"] for t in queue)
    print(json.dumps({
        "candidates": len(rows),
        "already_decided": len(rows) - len(queue),
        "queued": len(queue),
        "by_category": dict(by_cat.most_common()),
        "output": str(OUT.relative_to(ROOT)),
    }, indent=1))


if __name__ == "__main__":
    main()
