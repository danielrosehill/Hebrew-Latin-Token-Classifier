#!/usr/bin/env python3
"""Stage 3 — compare the seed against the blind annotation and queue what a human
must decide.

  agree     -> auto-accepted, no human time spent
  disagree  -> review queue
  audit     -> 10% random sample of the agreements also goes to the queue

The audit is not optional. Without it the only number available is how often two
models disagree, which says nothing about how wrong the agreeing majority is.

    python3 scripts/adjudicate.py --audit-rate 0.10

Outputs:
  data/generated/adjudicated.jsonl   per sentence: spans + status
  review/queue.json                  human tasks, worst first
  data/generated/agreement.json      the diagnostic numbers
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib import corpus  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "generated"
REVIEW = ROOT / "review"
RISK_ORDER = {"annotator_only": 0, "seed_only": 1, "audit": 2}


def key(span: dict) -> tuple[int, int]:
    return (span["start"], span["end"])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--audit-rate", type=float, default=0.10)
    p.add_argument("--seed", type=int, default=20260922)
    args = p.parse_args()

    sentences = corpus.read_jsonl(GEN / "sentences.jsonl")
    annotations = {r["text"]: r for r in corpus.read_jsonl(GEN / "annotations.jsonl")}
    sentences = list({s["text"]: s for s in sentences}.values())
    if not sentences:
        raise SystemExit("no generated sentences; run scripts/generate_samples.py")
    if not annotations:
        raise SystemExit("no annotations; run scripts/auto_annotate.py")

    rng = random.Random(args.seed)
    rows, queue = [], []
    stats: collections.Counter[str] = collections.Counter()

    for i, s in enumerate(sentences):
        ann = annotations.get(s["text"])
        if ann is None:
            stats["not_yet_annotated"] += 1
            continue

        seed = {key(x): x for x in s["seed_spans"]}
        auto = {key(x): x for x in ann["spans"]}
        agreed = seed.keys() & auto.keys()
        seed_only = seed.keys() - auto.keys()
        auto_only = auto.keys() - seed.keys()

        spans = []
        for k in sorted(agreed):
            spans.append({**seed[k], "status": "agreed"})
            stats["span_agreed"] += 1
        for k in sorted(seed_only):
            spans.append({**seed[k], "status": "pending"})
            stats["span_seed_only"] += 1
        for k in sorted(auto_only):
            spans.append({**auto[k], "status": "pending"})
            stats["span_annotator_only"] += 1

        sentence_agrees = not seed_only and not auto_only
        stats["sentence_full_agreement" if sentence_agrees else "sentence_disagreement"] += 1

        sid = f"g{i:05d}"
        rows.append({
            "id": sid,
            "text": s["text"],
            "seed_term": s["seed_term"],
            "seed_category": s["seed_category"],
            "generator": s["generator"],
            "annotator": ann["annotator"],
            "spans": sorted(spans, key=lambda x: x["start"]),
            "agreement": "full" if sentence_agrees else "partial",
        })

        for n, k in enumerate(sorted(seed_only) + sorted(auto_only)):
            span = seed.get(k) or auto[k]
            risk = "seed_only" if k in seed_only else "annotator_only"
            queue.append({
                "key": f"{sid}:{n}", "kind": "span", "risk": risk,
                "id": sid, "split": "generated", "text": s["text"],
                "start": span["start"], "end": span["end"],
                "surface": span["surface"], "term": span["term"],
                "dataset_label": s["seed_term"],
                "note": ("the generator seeded this term but the annotator did not mark it"
                         if risk == "seed_only" else
                         "the annotator marked this but it was not the seeded term") +
                        f" — is {span['surface']!r} a Hebrew word written in Latin script?",
            })

        if sentence_agrees and rng.random() < args.audit_rate:
            stats["audited"] += 1
            if spans:
                for n, span in enumerate(spans):
                    queue.append({
                        "key": f"{sid}:a{n}", "kind": "span", "risk": "audit",
                        "id": sid, "split": "generated", "text": s["text"],
                        "start": span["start"], "end": span["end"],
                        "surface": span["surface"], "term": span["term"],
                        "dataset_label": s["seed_term"],
                        "note": f"audit — both models agree {span['surface']!r} is Hebrew. "
                                f"Are they right?",
                    })
            else:
                queue.append({
                    "key": f"{sid}:a", "kind": "record", "risk": "audit",
                    "id": sid, "split": "generated", "text": s["text"],
                    "dataset_label": s["seed_term"],
                    "note": "audit — both models found no Hebrew here. Type any term "
                            "they missed, or submit empty to confirm.",
                })

    queue.sort(key=lambda c: (RISK_ORDER[c["risk"]], c["id"]))
    corpus.write_jsonl(GEN / "adjudicated.jsonl", rows)
    REVIEW.mkdir(exist_ok=True)
    (REVIEW / "queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=1))

    judged = stats["sentence_full_agreement"] + stats["sentence_disagreement"]
    rate = stats["sentence_disagreement"] / judged if judged else 0.0
    report = {
        "sentences": judged,
        "full_agreement": stats["sentence_full_agreement"],
        "disagreement": stats["sentence_disagreement"],
        "disagreement_rate": round(rate, 4),
        "spans_agreed": stats["span_agreed"],
        "spans_seed_only": stats["span_seed_only"],
        "spans_annotator_only": stats["span_annotator_only"],
        "audited_sentences": stats["audited"],
        "review_tasks": len(queue),
        "not_yet_annotated": stats["not_yet_annotated"],
    }
    if judged:
        if rate < 0.05:
            report["warning"] = ("disagreement under 5% — the annotator is agreeing too "
                                 "easily; change the prompt or the model before trusting it")
        elif rate > 0.25:
            report["warning"] = ("disagreement over 25% — the annotation policy is "
                                 "underspecified; settle docs/annotation-policy.md first")
    (GEN / "agreement.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
