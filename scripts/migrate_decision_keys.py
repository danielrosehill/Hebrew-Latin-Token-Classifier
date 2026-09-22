#!/usr/bin/env python3
"""Rewrite span-task keys in review/decisions.json after the key-scheme fix.

adjudicate.py used to number span tasks by their rank among the PENDING spans of
a sentence, while build_splits.py looks them up by index in the full span list.
Those differ in any sentence that also has an agreed span, so answered spans were
looked up under keys that did not exist and silently dropped as unreviewed.

This maps each old key to the correct one using the same adjudicated.jsonl the
queue was built from, so review work done under the old scheme is preserved
rather than thrown away. Idempotent: keys already correct are left alone.

    python3 scripts/migrate_decision_keys.py --write

Writes a .bak alongside before touching anything.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADJ = ROOT / "data" / "generated" / "adjudicated.jsonl"
DECISIONS = ROOT / "review" / "decisions.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="apply; otherwise dry run")
    args = ap.parse_args()

    rows = [json.loads(l) for l in ADJ.read_text().splitlines() if l.strip()]
    decisions = json.loads(DECISIONS.read_text())

    remap: dict[str, str] = {}
    for r in rows:
        pending = [i for i, s in enumerate(r["spans"]) if s["status"] == "pending"]
        for rank, idx in enumerate(pending):
            if rank != idx:
                remap[f"{r['id']}:{rank}"] = f"{r['id']}:{idx}"

    changed, collided, untouched = {}, [], 0
    for key, value in decisions.items():
        new = remap.get(key)
        if new and new != key:
            if new in decisions and new not in changed:
                collided.append((key, new))   # both keys answered; keep the correct one
                continue
            changed[key] = new
        else:
            untouched += 1

    print(f"decisions {len(decisions)}  remappable {len(remap)}  "
          f"rewritten {len(changed)}  unchanged {untouched}  collisions {len(collided)}")
    for old, new in list(changed.items())[:5]:
        print(f"  {old} -> {new}")

    if not args.write:
        print("\ndry run — pass --write to apply")
        return

    shutil.copy(DECISIONS, DECISIONS.with_suffix(".json.bak"))
    out = {}
    for key, value in decisions.items():
        out[changed.get(key, key)] = value
    DECISIONS.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"\nwrote {DECISIONS.relative_to(ROOT)} (backup at decisions.json.bak)")


if __name__ == "__main__":
    main()
