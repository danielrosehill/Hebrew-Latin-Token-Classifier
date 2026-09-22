#!/usr/bin/env python3
"""Build data/lexicon.csv from the source dataset's `hebrew_word` labels.

The dataset's labels cannot be taken at face value: they were evidently produced
by substring search, so a term list built from them contains entries that are
artifacts of matching inside an unrelated English word ("hi" from "think", "har"
from "Pharm", "ma" from "moshav"). Two tests separate those out:

  english_homograph  the term is also an ordinary English word, so matching it
                     will fire on genuine English text
  never_occurs       the term never matches on word boundaries anywhere in the
                     corpus, so it only ever existed as a bad label

Either one quarantines the term: it is kept, with its reason, but excluded from
automatic matching until a human rules on it.

Usage: python3 scripts/build_lexicon.py
"""
import collections
import csv
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"
OUT = ROOT / "data" / "lexicon.csv"
WORDLISTS = ["/usr/share/dict/american-english", "/usr/share/dict/words"]


def english_vocabulary() -> set[str]:
    for path in WORDLISTS:
        p = pathlib.Path(path)
        if p.exists():
            return {w.strip().lower() for w in p.read_text(errors="ignore").splitlines()
                    if w.strip() and "'" not in w}
    raise SystemExit("no system wordlist found; install wamerican")


def load_records() -> list[dict]:
    records = []
    for path in sorted(SOURCE.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                r["split"] = path.stem.replace("whisper_", "")
                records.append(r)
    return records


def word_pattern(term: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)


def main() -> None:
    records = load_records()
    english = english_vocabulary()
    corpus = [r["text"] for r in records]

    counts: collections.Counter[str] = collections.Counter()
    categories: dict[str, str] = {}
    for r in records:
        if r["hebrew_word"]:
            key = r["hebrew_word"].lower()
            counts[key] += 1
            categories.setdefault(key, r["category"] or "")

    rows = []
    for term, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        tokens = term.split()
        homograph = all(t in english for t in tokens)
        pattern = word_pattern(term)
        occurs = sum(1 for c in corpus if pattern.search(c))
        reasons = []
        if homograph:
            reasons.append("english_homograph")
        if occurs == 0:
            reasons.append("never_occurs")
        rows.append({
            "term": term,
            "tokens": len(tokens),
            "label_count": count,
            "word_boundary_occurrences": occurs,
            "category": categories[term],
            "status": "quarantined" if reasons else "active",
            "quarantine_reason": "|".join(reasons),
            "hebrew_script": "",   # filled by hand, or by stage 2 of the planning repo
            "source": "english-hebrew-mixed-sentences",
        })

    with OUT.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    quarantined = [r for r in rows if r["status"] == "quarantined"]
    print(f"{len(rows)} terms -> {OUT.relative_to(ROOT)}")
    print(f"  active      {len(rows) - len(quarantined)}")
    print(f"  quarantined {len(quarantined)}")
    for reason in ("english_homograph", "never_occurs"):
        hit = sorted(r["term"] for r in quarantined if reason in r["quarantine_reason"])
        print(f"    {reason}: {', '.join(hit)}")


if __name__ == "__main__":
    main()
