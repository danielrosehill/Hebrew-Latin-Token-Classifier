#!/usr/bin/env python3
"""Stage 5 — apply review decisions and emit term-disjoint BIO splits.

Splits are stratified BY TERM, not by sentence: no seed term appears in more than
one split. Splitting by sentence would let the model memorise a term in training
and be scored on it at test time, which inflates the reported figure by a wide
margin and measures the opposite of what FR-4 asks for — generalisation to terms
never seen.

Review decisions are folded in first. A span is tagged only if it is agreed by
both models or positively accepted by a human; anything still pending stays O, so
an incomplete review under-labels rather than mislabels.

    python3 scripts/build_splits.py

Outputs: data/corpus/{train,validation,test}.jsonl, data/corpus/report.json
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


def decided(d: dict) -> bool:
    """The review UI says `include`; decisions made before that relabel say
    `hebrew`. Accept either, preferring the newer key."""
    return bool(d.get("include", d.get("hebrew")))


def ruled(d: dict | None) -> bool:
    """A decision that actually settles something. `deferred` means the reviewer
    looked and could not rule, so it must NOT be read as a no -- it falls through
    to the same handling as unreviewed, leaving the span untagged."""
    return bool(d) and not d.get("deferred")
GEN = ROOT / "data" / "generated"
DECISIONS = ROOT / "review" / "decisions.json"
OUT = ROOT / "data" / "corpus"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--validation", type=float, default=0.10)
    p.add_argument("--test", type=float, default=0.10)
    p.add_argument("--seed", type=int, default=20260922)
    args = p.parse_args()

    rows = corpus.read_jsonl(GEN / "adjudicated.jsonl")
    if not rows:
        raise SystemExit("no adjudicated rows; run scripts/adjudicate.py")
    decisions = json.loads(DECISIONS.read_text()) if DECISIONS.exists() else {}
    if not decisions:
        print("note: no review/decisions.json — only model-agreed spans will be tagged")

    # Term-level rulings override every span of that term, agreed or not. One
    # decision about "baklava" settles all of its sentences at once.
    term_ruling = {d["term"].lower(): decided(d)
                   for d in decisions.values()
                   if d.get("kind") == "term" and d.get("term") and ruled(d)}

    # Boundary rulings: True keeps the full seeded span, False narrows it to the
    # annotator's shorter one. Keyed by the seeded term.
    boundary_ruling = {d["term"].lower(): (decided(d), d.get("short_term"))
                       for d in decisions.values()
                       if d.get("kind") == "boundary" and d.get("term") and ruled(d)}

    stats: collections.Counter[str] = collections.Counter()
    unapplied = []
    prepared = []

    for row in rows:
        text, spans = row["text"], []
        for n, span in enumerate(row["spans"]):
            b = boundary_ruling.get(span["term"].lower())
            if b is not None:
                keep_full, short_term = b
                if keep_full:
                    stats["boundary_full"] += 1
                    spans.append({k: span[k] for k in
                                  ("start", "end", "surface", "term")})
                elif short_term:
                    found = corpus.word_spans(span["surface"], short_term)
                    if found:
                        o = span["start"] + found[0][0]
                        spans.append({
                            "start": o, "end": o + (found[0][1] - found[0][0]),
                            "surface": text[o:o + (found[0][1] - found[0][0])],
                            "term": short_term.lower()})
                        stats["boundary_narrowed"] += 1
                    else:
                        stats["boundary_narrow_failed"] += 1
                continue
            ruling = term_ruling.get(span["term"].lower())
            if ruling is not None:
                stats["term_ruling_kept" if ruling else "term_ruling_dropped"] += 1
                if ruling:
                    spans.append({k: span[k] for k in
                                  ("start", "end", "surface", "term")})
                continue
            if span["status"] == "agreed":
                d = decisions.get(f"{row['id']}:a{n}")           # audit task, if sampled
                keep = decided(d) if ruled(d) else True
                stats["audit_overturned" if not keep else "agreed_kept"] += 1
            else:
                d = decisions.get(f"{row['id']}:{n}")
                if not ruled(d):
                    keep = False
                    stats["deferred_dropped" if d else
                          "pending_unreviewed_dropped"] += 1
                else:
                    keep = decided(d)
                    stats["human_accepted" if keep else "human_rejected"] += 1
            if keep:
                spans.append({k: span[k] for k in ("start", "end", "surface", "term")})

        d = decisions.get(f"{row['id']}:a")                      # audit of an empty sentence
        for term in (d or {}).get("terms", []):
            found = corpus.word_spans(text, term)
            if not found:
                unapplied.append({"id": row["id"], "term": term, "text": text})
                continue
            s, e = found[0]
            if not any(x["start"] == s for x in spans):
                spans.append({"start": s, "end": e, "surface": text[s:e],
                              "term": term.lower()})
                stats["human_added"] += 1

        spans.sort(key=lambda s: s["start"])
        prepared.append({
            "id": row["id"], "text": text, "seed_term": row["seed_term"],
            "category": row["seed_category"], "spans": spans,
            "tokens": corpus.bio_tags(text, spans),
        })

    # --- term-disjoint split ---
    # Positives are split by TERM so no term appears in two splits. Negatives have
    # no seed term, so they are spread proportionally and stratified by negative
    # kind -- otherwise one split gets all the substring traps and its precision
    # figure means nothing.
    rng = random.Random(args.seed)
    terms = sorted({r["seed_term"] for r in prepared if r["seed_term"]})
    rng.shuffle(terms)
    n_val = max(1, round(len(terms) * args.validation))
    n_test = max(1, round(len(terms) * args.test))
    assign = {}
    for t in terms[:n_test]:
        assign[t] = "test"
    for t in terms[n_test:n_test + n_val]:
        assign[t] = "validation"
    for t in terms[n_test + n_val:]:
        assign[t] = "train"

    by_split = collections.defaultdict(list)
    negatives_by_kind = collections.defaultdict(list)
    for r in prepared:
        if r["seed_term"]:
            by_split[assign[r["seed_term"]]].append(r)
        else:
            negatives_by_kind[r["category"]].append(r)

    for kind, items in sorted(negatives_by_kind.items()):
        rng.shuffle(items)
        n_t = max(1, round(len(items) * args.test))
        n_v = max(1, round(len(items) * args.validation))
        by_split["test"] += items[:n_t]
        by_split["validation"] += items[n_t:n_t + n_v]
        by_split["train"] += items[n_t + n_v:]

    for split, items in by_split.items():
        corpus.write_jsonl(OUT / f"{split}.jsonl", items)

    leaked = {}
    for a in by_split:
        for b in by_split:
            if a >= b:
                continue
            shared = ({r["seed_term"] for r in by_split[a] if r["seed_term"]} &
                      {r["seed_term"] for r in by_split[b] if r["seed_term"]})
            if shared:
                leaked[f"{a}|{b}"] = sorted(shared)

    report = {
        "sentences": len(prepared),
        "with_at_least_one_span": sum(1 for r in prepared if r["spans"]),
        "without_spans": sum(1 for r in prepared if not r["spans"]),
        "distinct_terms": len(terms),
        "negatives": sum(len(v) for v in negatives_by_kind.values()),
        "negatives_by_kind": {k: len(v) for k, v in sorted(negatives_by_kind.items())},
        "splits": {k: len(v) for k, v in sorted(by_split.items())},
        "terms_per_split": {k: len({r["seed_term"] for r in v if r["seed_term"]})
                            for k, v in sorted(by_split.items())},
        "negatives_per_split": {k: sum(1 for r in v if not r["seed_term"])
                                for k, v in sorted(by_split.items())},
        "term_leakage_between_splits": leaked,
        "decisions_applied": len(decisions),
        "term_rulings": len(term_ruling),
        "boundary_rulings": len(boundary_ruling),
        "counts": dict(stats),
        "unapplied_terms": unapplied,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "unapplied_terms"}, indent=1))
    if leaked:
        raise SystemExit("term leakage between splits — this must be zero")


if __name__ == "__main__":
    main()
