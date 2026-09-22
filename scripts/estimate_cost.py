#!/usr/bin/env python3
"""Project full-corpus cost from measured pilot usage.

Reads data/usage.jsonl, which every LLM call appends to, and extrapolates to a
target corpus size. Measured rather than guessed: reasoning tokens in particular
are billed as output and are roughly two thirds of completion tokens on this
workload, which a back-of-envelope estimate misses entirely.

    python3 scripts/estimate_cost.py --sentences 2600
    python3 scripts/estimate_cost.py --compare

Prices are USD per 1M tokens, from scripts/lib/llm.py. DeepSeek figures are
OFF-PEAK; peak is double. Peak is only 01:00-04:00 and 06:00-10:00 UTC on
weekdays, so an evening or weekend run in Israel is always off-peak.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib import corpus, llm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
USAGE = ROOT / "data" / "usage.jsonl"


def per_stage(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for stage in sorted({r["stage"] for r in rows}):
        items = [r for r in rows if r["stage"] == stage]
        out[stage] = {
            "calls": len(items),
            "model": collections.Counter(r["model"] for r in items).most_common(1)[0][0],
            "prompt_tokens": sum(r["prompt_tokens"] for r in items),
            "completion_tokens": sum(r["completion_tokens"] for r in items),
            "reasoning_tokens": sum(r["reasoning_tokens"] for r in items),
        }
    return out


def cost(model: str, prompt: int, completion: int) -> float | None:
    price = llm.PRICES.get(model)
    if not price:
        return None
    return prompt / 1e6 * price["input"] + completion / 1e6 * price["output"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sentences", type=int, default=2600, help="target corpus size")
    p.add_argument("--per-term", type=int, default=3)
    p.add_argument("--compare", action="store_true", help="price the same job on every model")
    args = p.parse_args()

    rows = corpus.read_jsonl(USAGE)
    if not rows:
        raise SystemExit("no data/usage.jsonl yet — run a pilot first")

    sentences = corpus.read_jsonl(ROOT / "data" / "generated" / "sentences.jsonl",
                                  dedupe_on="text")
    n_pilot = len(sentences) or 1
    scale = args.sentences / n_pilot
    stages = per_stage(rows)

    print(f"measured pilot: {n_pilot} sentences, {len(rows)} calls")
    print(f"projecting to {args.sentences} sentences (x{scale:.0f})\n")

    total = 0.0
    unpriced = []
    for stage, s in stages.items():
        prompt = round(s["prompt_tokens"] * scale)
        completion = round(s["completion_tokens"] * scale)
        c = cost(s["model"], prompt, completion)
        reasoning_share = (s["reasoning_tokens"] / s["completion_tokens"]
                           if s["completion_tokens"] else 0)
        print(f"{stage:<14} {s['model']}")
        print(f"  {s['calls']:>4} calls  ->  {round(s['calls'] * scale):>6} calls")
        print(f"  in  {prompt:>9,} tok   out {completion:>9,} tok "
              f"(reasoning {reasoning_share:.0%} of output)")
        if c is None:
            unpriced.append(s["model"])
            print("  cost  unknown — no price for this model in lib/llm.py\n")
        else:
            total += c
            print(f"  cost  ${c:,.2f}\n")

    print(f"TOTAL  ${total:,.2f}" + ("  (+ unpriced models)" if unpriced else ""))
    if unpriced:
        print(f"unpriced: {', '.join(sorted(set(unpriced)))}")

    if args.compare:
        gen = stages.get("generate") or next(iter(stages.values()))
        ann = stages.get("annotate") or gen
        prompt = round((gen["prompt_tokens"] + ann["prompt_tokens"]) * scale)
        completion = round((gen["completion_tokens"] + ann["completion_tokens"]) * scale)
        print(f"\nsame job ({prompt:,} in / {completion:,} out), both passes, per model:")
        priced = sorted(
            ((m, cost(m, prompt, completion)) for m in llm.PRICES),
            key=lambda kv: kv[1])
        for model, c in priced:
            print(f"  {model:<34} ${c:>8,.2f}")
        print("\nDeepSeek figures are off-peak. Peak (01:00-04:00, 06:00-10:00 UTC,")
        print("weekdays) doubles them. Reasoning tokens are billed as output.")


if __name__ == "__main__":
    main()
