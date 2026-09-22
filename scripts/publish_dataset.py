#!/usr/bin/env python3
"""Stage 6 — push the corpus to Hugging Face.

Uploads data/corpus/*.jsonl plus the term inventory and a dataset card. Reads
HUGGINGFACE_TOKEN from the environment (needs `write` role).

Dry run by default. Nothing is uploaded until --push is passed, because this
publishes to a public URL.

    python3 scripts/publish_dataset.py                    # show what would happen
    python3 scripts/publish_dataset.py --push
    python3 scripts/publish_dataset.py --push --private
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
TERMS = ROOT / "data" / "terms.csv"

CARD = """---
license: mit
language:
  - en
  - he
task_categories:
  - token-classification
tags:
  - code-switching
  - hebrew
  - transliteration
  - romanization
  - named-entity-recognition
size_categories:
  - 1K<n<10K
---

# Hebrew-in-Latin code-switching corpus

English sentences containing **Hebrew words written in Latin characters**, with
token-level BIO spans marking them.

*"I'm going to **Bituach Leumi** today"* · *"pick up some **challah** from the
**makolet**"*

No corpus like this was published when this was built. There is no `heb_Latn` label
in GlotLID v3, `lid.176` or `lid218e`, no token-level code-switching model covering
Hebrew, and no Hebrew-English code-switching corpus of any kind.

## What it is for

Training a classifier that finds Hebrew words in English text so a text-to-speech
system can pronounce them as Hebrew. The labelling test is **pronunciation, not
etymology**: would an English voice mispronounce this word, and would treating it as
Hebrew fix that? So *kosher*, *Shabbat* and *hummus* are negatives — English says them
acceptably — while *makolet*, *mashkanta* and *challah* are positives.

## Splits are term-disjoint

**No seed term appears in more than one split.** Splitting by sentence rather than by
term would let a model memorise a term in training and be scored on it at test time.
Evaluate generalisation to unseen terms, which is what this is for.

| Split | Sentences | Terms |
| --- | --- | --- |
{split_table}

## Format

```json
{example}
```

`tokens` is `[token, tag]` pairs, tags in `O` / `B-HE` / `I-HE`. Multi-token terms
such as *bituach leumi* are `B-HE I-HE`, which is why the scheme is not a binary flag.

## How it was built

{provenance}

Generation was term-seeded: the model was given one Hebrew term and asked for
sentences using it, and any generation where the term did not word-boundary match was
rejected. Annotation was a second, **blind** pass by a different model family that was
not told the seed term. Agreements were auto-accepted, disagreements were reviewed by
a human, and a random {audit_pct}% sample of the agreements was also human-audited.

**This corpus is largely synthetic.** Sentences were model-generated and
model-annotated, with human review concentrated on disagreements and a random audit
rather than spread over every row. Treat the audit result as the quality estimate.

## Provenance and licence

MIT. Built in
[danielrosehill/Hebrew-Latin-Token-Classifier](https://github.com/danielrosehill/Hebrew-Latin-Token-Classifier),
which holds the generation, annotation and review code, and the annotation policy.

Related: [`danielrosehill/English-Hebrew-Mixed-Sentences`](https://huggingface.co/datasets/danielrosehill/English-Hebrew-Mixed-Sentences)
(human-read audio, the predecessor) and
[`danielrosehill/Whisper-Hebrish`](https://huggingface.co/danielrosehill/Whisper-Hebrish).
"""


def build_card(agreement: dict) -> str:
    rows, example = [], {}
    for split in ("train", "validation", "test"):
        path = CORPUS / f"{split}.jsonl"
        if not path.exists():
            continue
        items = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        rows.append(f"| `{split}` | {len(items)} | {len({i['seed_term'] for i in items})} |")
        if not example and items:
            example = {k: items[0][k] for k in ("id", "text", "spans", "tokens")}
            example["tokens"] = example["tokens"][:8] + [["...", "..."]]

    provenance = "\n".join(
        f"- **{k}**: {v}" for k, v in {
            "generator": agreement.get("generator", "see repo"),
            "annotator": agreement.get("annotator", "see repo"),
            "sentences": agreement.get("sentences", "—"),
            "model agreement": f"{100 * (1 - agreement.get('disagreement_rate', 0)):.1f}%",
            "human-reviewed tasks": agreement.get("review_tasks", "—"),
            "built": datetime.date.today().isoformat(),
        }.items())

    return CARD.format(
        split_table="\n".join(rows) or "| — | — | — |",
        example=json.dumps(example, ensure_ascii=False, indent=1),
        provenance=provenance,
        audit_pct=int(100 * agreement.get("audit_rate", 0.10)),
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default="danielrosehill/hebrew-latin-code-switching")
    p.add_argument("--private", action="store_true")
    p.add_argument("--push", action="store_true", help="actually upload")
    args = p.parse_args()

    if not (CORPUS / "train.jsonl").exists():
        raise SystemExit("no corpus; run scripts/build_splits.py")

    agreement_path = ROOT / "data" / "generated" / "agreement.json"
    agreement = json.loads(agreement_path.read_text()) if agreement_path.exists() else {}
    card = build_card(agreement)
    (CORPUS / "README.md").write_text(card)

    files = sorted(CORPUS.glob("*.jsonl")) + [CORPUS / "README.md"]
    if TERMS.exists():
        files.append(TERMS)

    print(f"repo      {args.repo} ({'private' if args.private else 'public'})")
    print(f"card      {(CORPUS / 'README.md').relative_to(ROOT)}")
    for f in files:
        print(f"  upload  {f.relative_to(ROOT)}  ({f.stat().st_size:,} bytes)")

    if not args.push:
        print("\ndry run — pass --push to upload. This publishes to a public URL.")
        return

    token = os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        raise SystemExit("HUGGINGFACE_TOKEN not set")
    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise SystemExit("pip install huggingface_hub")

    api = HfApi(token=token)
    api.create_repo(args.repo, repo_type="dataset", private=args.private, exist_ok=True)
    for f in files:
        api.upload_file(
            path_or_fileobj=str(f),
            path_in_repo="README.md" if f.name == "README.md" else f"data/{f.name}",
            repo_id=args.repo,
            repo_type="dataset",
        )
        print(f"  pushed  {f.name}")
    print(f"\nhttps://huggingface.co/datasets/{args.repo}")


if __name__ == "__main__":
    main()
