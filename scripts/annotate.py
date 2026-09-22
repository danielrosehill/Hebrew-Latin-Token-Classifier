#!/usr/bin/env python3
"""Programmatic span annotation of the source dataset, for human review.

Two independent defects in the source dataset drive this script:

  under-labelling  each record carries exactly one `hebrew_word`, but many
                   sentences contain more than one Hebrew term
  mis-labelling    the label was evidently produced by substring search, so 114
                   of 474 labels point at a string inside an unrelated English
                   word ("hi" inside "think"). In those records the real Hebrew
                   term is not labelled at all

So the dataset's own labels are treated as candidates, not as truth. Every
candidate carries its provenance and a risk grade, and the review queue is
ordered worst-first.

Outputs:
  data/annotations/spans.jsonl   one row per sentence: spans + BIO tokens
  data/annotations/summary.json  counts
  review/queue.json              review tasks, consumed by review/index.html

Nothing here is authoritative. Human decisions land in review/decisions.json;
run scripts/apply_decisions.py to fold them back in.

Usage: python3 scripts/annotate.py
"""
import collections
import csv
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"
LEXICON = ROOT / "data" / "lexicon.csv"
ANNOT = ROOT / "data" / "annotations"
REVIEW = ROOT / "review"

TOKEN_RE = re.compile(r"\w+(?:'\w+)?|[^\w\s]")
RISK_ORDER = {"mislabelled": 0, "unmatched": 1, "quarantined": 2, "medium": 3, "low": 4}


def load_lexicon() -> dict[str, dict]:
    with LEXICON.open() as fh:
        return {row["term"]: row for row in csv.DictReader(fh)}


def load_records() -> list[dict]:
    records = []
    for path in sorted(SOURCE.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                r["split"] = path.stem.replace("whisper_", "")
                records.append(r)
    return records


def build_matcher(terms) -> re.Pattern | None:
    if not terms:
        return None
    ordered = sorted(terms, key=len, reverse=True)   # longest wins: "bituach leumi" over "bituach"
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t in ordered) + r")(?!\w)",
                      re.IGNORECASE)


def bio_tags(text: str, spans: list[dict]) -> list[list[str]]:
    """Token/tag pairs. Only accepted spans are tagged; pending spans stay O
    until a human says otherwise, so the file is never silently wrong."""
    tags = []
    for m in TOKEN_RE.finditer(text):
        tag = "O"
        for s in spans:
            if s["decision"] == "accepted" and m.start() >= s["start"] and m.end() <= s["end"]:
                tag = "B-HE" if m.start() == s["start"] else "I-HE"
                break
        tags.append([m.group(0), tag])
    return tags


def main() -> None:
    ANNOT.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)

    lexicon = load_lexicon()
    records = load_records()
    active = {t for t, e in lexicon.items() if e["status"] == "active"}
    quarantined = set(lexicon) - active
    match_active = build_matcher(active)
    match_quarantined = build_matcher(quarantined)

    annotated, queue = [], []
    counts: collections.Counter[str] = collections.Counter()

    for r in records:
        text, label = r["text"], (r["hebrew_word"] or "").lower()

        # Does the record's own label survive word-boundary matching?
        if not label:
            alignment = "no_label"
        elif re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", text, re.I):
            alignment = "aligned"
        else:
            alignment = "mislabelled"
        counts[f"label_{alignment}"] += 1

        spans = []
        seen = set()
        for matcher, quarantine in ((match_active, False), (match_quarantined, True)):
            if matcher is None:
                continue
            for m in matcher.finditer(text):
                if (m.start(1), m.end(1)) in seen:
                    continue
                seen.add((m.start(1), m.end(1)))
                term = m.group(1).lower()
                entry = lexicon[term]
                is_label = term == label and alignment == "aligned"
                if quarantine:
                    risk = "quarantined"
                elif is_label:
                    risk = "low"
                elif int(entry["tokens"]) == 1:
                    risk = "medium"
                else:
                    risk = "low"
                spans.append({
                    "start": m.start(1),
                    "end": m.end(1),
                    "surface": m.group(1),
                    "term": term,
                    "category": entry["category"],
                    "source": "dataset_label" if is_label else "lexicon_match",
                    "risk": risk,
                    "decision": "accepted" if is_label else "pending",
                })
                counts["span_" + spans[-1]["source"]] += 1

        spans.sort(key=lambda s: s["start"])
        accepted = [s for s in spans if s["decision"] == "accepted"]

        annotated.append({
            "id": r["id"],
            "split": r["split"],
            "text": text,
            "dataset_label": r["hebrew_word"],
            "dataset_category": r["category"],
            "label_alignment": alignment,
            "spans": spans,
            "tokens": bio_tags(text, spans),
        })

        # ---- review tasks ----
        if alignment == "mislabelled":
            queue.append({
                "key": f"{r['id']}:relabel", "kind": "record", "risk": "mislabelled",
                "id": r["id"], "split": r["split"], "text": text,
                "dataset_label": r["hebrew_word"],
                "note": f"dataset label {r['hebrew_word']!r} matches only inside another "
                        f"word; type the real Hebrew term(s), or leave empty if none",
            })
        elif not accepted and not spans:
            counts["records_no_candidate"] += 1
            queue.append({
                "key": f"{r['id']}:none", "kind": "record", "risk": "unmatched",
                "id": r["id"], "split": r["split"], "text": text,
                "dataset_label": r["hebrew_word"],
                "note": "no lexicon term matched; type any Hebrew term(s) present",
            })

        for i, s in enumerate(spans):
            if s["decision"] == "pending":
                queue.append({
                    "key": f"{r['id']}:{i}", "kind": "span", "risk": s["risk"],
                    "id": r["id"], "split": r["split"], "text": text,
                    "start": s["start"], "end": s["end"],
                    "surface": s["surface"], "term": s["term"],
                    "dataset_label": r["hebrew_word"],
                    "note": f"is {s['surface']!r} a Hebrew word written in Latin script?",
                })

    queue.sort(key=lambda c: (RISK_ORDER[c["risk"]], c.get("term") or "", c["id"]))

    with (ANNOT / "spans.jsonl").open("w") as fh:
        for row in annotated:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (REVIEW / "queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=1))

    summary = {
        "records": len(records),
        "lexicon_terms": len(lexicon),
        "lexicon_active": len(active),
        "lexicon_quarantined": len(quarantined),
        "labels_aligned": counts["label_aligned"],
        "labels_mislabelled": counts["label_mislabelled"],
        "labels_absent": counts["label_no_label"],
        "spans_accepted_from_label": counts["span_dataset_label"],
        "spans_pending_from_lexicon": counts["span_lexicon_match"],
        "records_with_no_candidate": counts["records_no_candidate"],
        "review_tasks": len(queue),
        "review_by_risk": dict(collections.Counter(c["risk"] for c in queue)),
        "review_by_kind": dict(collections.Counter(c["kind"] for c in queue)),
    }
    (ANNOT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
