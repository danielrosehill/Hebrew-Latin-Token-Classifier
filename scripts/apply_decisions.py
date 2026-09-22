#!/usr/bin/env python3
"""Fold review decisions back into a gold token-classification corpus.

Reads review/decisions.json (exported from the review UI) and rewrites the
annotation as CoNLL-style BIO data, split the same way as the source dataset so
the splits stay comparable with the Whisper fine-tune.

Span decisions accept or reject a candidate. Record decisions supply terms the
lexicon did not have; those are matched back into the sentence, and any term
that cannot be found on a word boundary is reported rather than silently dropped.

Outputs:
  data/gold/{train,validation,test}.jsonl   tokens + BIO tags
  data/gold/new_terms.csv                   terms supplied during review
  data/gold/report.json                     what changed, and what failed to apply

Usage: python3 scripts/apply_decisions.py
"""
import collections
import csv
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
ANNOT = ROOT / "data" / "annotations" / "spans.jsonl"
DECISIONS = ROOT / "review" / "decisions.json"
GOLD = ROOT / "data" / "gold"

TOKEN_RE = re.compile(r"\w+(?:'\w+)?|[^\w\s]")


def word_span(text: str, term: str) -> tuple[int, int] | None:
    m = re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE)
    return (m.start(), m.end()) if m else None


def bio_tags(text: str, spans: list[dict]) -> list[list[str]]:
    tags = []
    for m in TOKEN_RE.finditer(text):
        tag = "O"
        for s in spans:
            if m.start() >= s["start"] and m.end() <= s["end"]:
                tag = "B-HE" if m.start() == s["start"] else "I-HE"
                break
        tags.append([m.group(0), tag])
    return tags


def main() -> None:
    if not DECISIONS.exists():
        raise SystemExit(f"no decisions yet — export decisions.json from the review UI "
                         f"into {DECISIONS.relative_to(ROOT)}")
    GOLD.mkdir(parents=True, exist_ok=True)

    decisions = json.loads(DECISIONS.read_text())
    records = [json.loads(line) for line in ANNOT.read_text().splitlines() if line.strip()]

    stats: collections.Counter[str] = collections.Counter()
    unapplied, new_terms = [], collections.Counter()
    by_split = collections.defaultdict(list)

    for r in records:
        text = r["text"]
        spans = []
        for i, s in enumerate(r["spans"]):
            d = decisions.get(f"{r['id']}:{i}")
            if d is None:
                keep = s["decision"] == "accepted"      # unreviewed: trust only the aligned label
                stats["span_unreviewed_kept" if keep else "span_unreviewed_dropped"] += 1
            else:
                keep = bool(d.get("include", d.get("hebrew")))
                stats["span_accepted" if keep else "span_rejected"] += 1
            if keep:
                spans.append({"start": s["start"], "end": s["end"],
                              "surface": s["surface"], "term": s["term"]})

        for suffix in ("relabel", "none"):
            d = decisions.get(f"{r['id']}:{suffix}")
            if not d:
                continue
            for term in d.get("terms", []):
                found = word_span(text, term)
                if not found:
                    unapplied.append({"id": r["id"], "term": term, "text": text})
                    stats["term_not_found"] += 1
                    continue
                if any(s["start"] == found[0] for s in spans):
                    continue
                spans.append({"start": found[0], "end": found[1],
                              "surface": text[found[0]:found[1]], "term": term.lower()})
                new_terms[term.lower()] += 1
                stats["term_added"] += 1

        spans.sort(key=lambda s: s["start"])
        by_split[r["split"]].append({
            "id": r["id"],
            "text": text,
            "spans": spans,
            "tokens": bio_tags(text, spans),
        })

    for split, rows in by_split.items():
        with (GOLD / f"{split}.jsonl").open("w") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    with (GOLD / "new_terms.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["term", "occurrences"])
        w.writerows(sorted(new_terms.items(), key=lambda kv: (-kv[1], kv[0])))

    tagged = sum(1 for rows in by_split.values() for r in rows if r["spans"])
    total = sum(len(rows) for rows in by_split.values())
    report = {
        "records": total,
        "records_with_at_least_one_span": tagged,
        "records_with_no_span": total - tagged,
        "decisions_applied": len(decisions),
        "new_terms": len(new_terms),
        "counts": dict(stats),
        "unapplied_terms": unapplied,
        "splits": {k: len(v) for k, v in sorted(by_split.items())},
    }
    (GOLD / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "unapplied_terms"}, indent=1))
    if unapplied:
        print(f"\n{len(unapplied)} supplied terms did not match on a word boundary — "
              f"see data/gold/report.json")


if __name__ == "__main__":
    main()
