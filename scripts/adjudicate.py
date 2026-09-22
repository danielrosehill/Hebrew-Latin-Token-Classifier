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
import csv
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib import corpus  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "generated"
REVIEW = ROOT / "review"
EXCLUSIONS = ROOT / "data" / "exclusions.csv"
RISK_ORDER = {"term": 0, "boundary": 1, "annotator_only": 2, "seed_only": 3,
              "audit": 4}


def key(span: dict) -> tuple[int, int]:
    return (span["start"], span["end"])


def load_exclusions(posture: str) -> tuple[set[str], dict[str, str]]:
    """Terms that are never a positive span, and why.

    Daniel's rule, 2026-09-22: every flagged span triggers downstream work -- a
    segment split, a separate TTS call, a concatenation. A miss leaves current
    behaviour unchanged; a false positive gets an English word spoken in Hebrew
    AND pays that cost. So the default posture is conservative.

    Two dispositions, per docs/taxonomy.md:

      always        excluded under every posture. Anglicised Hebrew that English
                    genuinely says fine, and function words that only entered the
                    term list as substring artefacts.
      conservative  excluded by default, reinstated with --posture expansive.
                    Toponyms, Israel-English vocabulary, and words current ASR is
                    observed to handle. These are judgement calls, held out now
                    and recoverable later without regenerating anything.

    A deterministic list rather than a model judgement: the class is known and
    finite, and a list is auditable where a fuzzy instruction is not. The file is
    meant to be edited -- a term moved or deleted changes the corpus on the next
    run, with no new inference.
    """
    if not EXCLUSIONS.exists():
        return set(), {}
    with EXCLUSIONS.open() as fh:
        rows = [r for r in csv.DictReader(fh) if r["term"].strip()]
    active = {r["term"].strip().lower(): r["category"] for r in rows
              if r["disposition"] == "always"
              or (posture == "conservative" and r["disposition"] == "conservative")}
    return set(active), active


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--audit-rate", type=float, default=0.10)
    p.add_argument("--seed", type=int, default=20260922)
    p.add_argument("--posture", choices=["conservative", "expansive"],
                   default="conservative",
                   help="conservative (default) also drops the judgement-call "
                        "exclusions: toponyms, Israel-English, ASR-handled terms")
    p.add_argument("--term-threshold", type=float, default=0.67,
                   help="refuse rate above which a term is queued once, not per span")
    args = p.parse_args()

    sentences = corpus.read_jsonl(GEN / "sentences.jsonl")
    annotations = {r["text"]: r for r in corpus.read_jsonl(GEN / "annotations.jsonl")}
    sentences = list({s["text"]: s for s in sentences}.values())
    if not sentences:
        raise SystemExit("no generated sentences; run scripts/generate_samples.py")
    if not annotations:
        raise SystemExit("no annotations; run scripts/auto_annotate.py")

    anglicised, excluded_category = load_exclusions(args.posture)
    rng = random.Random(args.seed)
    rows, queue = [], []
    boundary_pairs: dict[tuple[str, str], list] = {}
    dropped_anglicised: collections.Counter[str] = collections.Counter()
    dropped_by_category: collections.Counter[str] = collections.Counter()
    stats: collections.Counter[str] = collections.Counter()

    # First pass: how often does the annotator refuse the generator's seed term?
    # A term refused nearly every time is a bad TERM, not a set of bad sentences --
    # the inventory was model-generated and contains anglicised loanwords and
    # misused words. Rolling those up turns N span decisions into one term decision.
    seed_seen: collections.Counter[str] = collections.Counter()
    seed_refused: collections.Counter[str] = collections.Counter()
    for s_ in sentences:
        ann_ = annotations.get(s_["text"])
        if ann_ is None or not s_["seed_term"]:
            continue
        seed_seen[s_["seed_term"]] += 1
        auto_keys = {key(x) for x in ann_["spans"]}
        if any(key(x) in auto_keys for x in s_["seed_spans"]):
            continue
        # Not matching the seed span is not the same as rejecting the term. If the
        # annotator proposed an OVERLAPPING shorter span, it kept the Hebrew and
        # moved the boundary -- "tofes 1311" -> "tofes". That is a boundary
        # question, and asking it as a yes/no about the term has no right answer:
        # include keeps the numeral in a Hebrew segment, exclude throws away a
        # genuinely Hebrew word. Only a span the annotator replaced with NOTHING
        # counts as a refusal.
        narrowed = any(x["start"] < sp["end"] and sp["start"] < x["end"]
                       for sp in s_["seed_spans"] for x in ann_["spans"])
        if not narrowed:
            seed_refused[s_["seed_term"]] += 1

    systematic = {t for t, n in seed_refused.items()
                  if seed_seen[t] >= 2 and n / seed_seen[t] >= args.term_threshold}
    stats["terms_systematically_refused"] = len(systematic)

    for i, s in enumerate(sentences):
        ann = annotations.get(s["text"])
        if ann is None:
            stats["not_yet_annotated"] += 1
            continue

        # Drop anglicised spans before anything else sees them: they are not a
        # disagreement to resolve, they are a settled negative.
        def _keep(x: dict) -> bool:
            t = x["term"].lower()
            if t in anglicised:
                dropped_anglicised[t] += 1
                dropped_by_category[excluded_category[t]] += 1
                return False
            return True

        seed = {key(x): x for x in s["seed_spans"] if _keep(x)}
        auto = {key(x): x for x in ann["spans"] if _keep(x)}
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

        # Where a seed span and an annotator span overlap without matching, the
        # models agree the text is Hebrew and disagree only about where the span
        # ends -- "tofes 1311" against "tofes". That is one question about a pair
        # of terms, not one question per sentence, and it was 190 of 553 tasks
        # before this rollup.
        overlaps = set()
        for ks in seed_only:
            for ka in auto_only:
                if ks[0] < ka[1] and ka[0] < ks[1]:
                    overlaps.add((ks, ka))
                    pair = (seed[ks]["term"], auto[ka]["term"])
                    boundary_pairs.setdefault(pair, []).append(
                        (s["text"], seed[ks]["surface"], auto[ka]["surface"]))
        covered = {k for pairk in overlaps for k in pairk}

        for n, k in enumerate(sorted(seed_only) + sorted(auto_only)):
            span = seed.get(k) or auto[k]
            risk = "seed_only" if k in seed_only else "annotator_only"
            # Covered by a single term-level decision; do not ask N times.
            if risk == "seed_only" and span["term"] in systematic:
                continue
            if k in covered:
                continue
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

    # One task per overlapping term pair, instead of one per sentence.
    for (seed_term, ann_term), examples in sorted(boundary_pairs.items()):
        # A term genuinely refused everywhere does not also need a boundary
        # question -- ruling it out settles its spans either way. Narrowings are
        # no longer counted as refusals, so they reach here and get asked properly.
        if seed_term in systematic:
            continue
        text, long_surface, short_surface = examples[0]
        queue.append({
            "key": f"boundary:{seed_term}|{ann_term}", "kind": "boundary",
            "risk": "boundary", "id": f"boundary:{seed_term}",
            "split": "generated", "text": text,
            "examples": [e[0] for e in examples[:3]],
            "term": seed_term, "surface": long_surface,
            "short_term": ann_term, "short_surface": short_surface,
            "dataset_label": seed_term,
            "note": f"both models agree this is Hebrew and disagree on the span, in "
                    f"{len(examples)} sentence(s). Should the span be the full "
                    f"{long_surface!r}, or just {short_surface!r}?",
        })

    # One task per systematically-refused term, with examples, instead of N spans.
    for term in sorted(systematic):
        examples = [r["text"] for r in rows
                    if r["seed_term"] == term and any(sp["term"] == term
                                                      for sp in r["spans"])][:3]
        if not examples:
            examples = [s_["text"] for s_ in sentences if s_["seed_term"] == term][:3]
        queue.append({
            "key": f"term:{term}", "kind": "term", "risk": "term",
            "id": f"term:{term}", "split": "generated",
            "text": examples[0] if examples else term,
            "examples": examples,
            "term": term,
            "surface": term,
            "dataset_label": term,
            "note": f"the annotator rejected {term!r} in "
                    f"{seed_refused[term]} of {seed_seen[term]} sentences. "
                    f"Is it a Hebrew word an English voice would mispronounce? "
                    f"Answering here decides every span for this term.",
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
        "posture": args.posture,
        "exclusions_active": len(anglicised),
        "excluded_spans_dropped": sum(dropped_anglicised.values()),
        "excluded_terms_hit": len(dropped_anglicised),
        "excluded_by_category": dict(dropped_by_category),
        "terms_systematically_refused": stats["terms_systematically_refused"],
        "boundary_pairs": len(boundary_pairs),
        "boundary_spans_rolled_up": sum(len(v) for v in boundary_pairs.values()),
        "terms_refused_list": sorted(systematic),
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
