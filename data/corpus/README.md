---
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
| `train` | 12 | 4 |
| `validation` | 3 | 1 |
| `test` | 3 | 1 |

## Format

```json
{
 "id": "g00000",
 "text": "I'm meeting Dana in tel aviv on Thursday for coffee near the beach.",
 "spans": [],
 "tokens": [
  [
   "I'm",
   "O"
  ],
  [
   "meeting",
   "O"
  ],
  [
   "Dana",
   "O"
  ],
  [
   "in",
   "O"
  ],
  [
   "tel",
   "O"
  ],
  [
   "aviv",
   "O"
  ],
  [
   "on",
   "O"
  ],
  [
   "Thursday",
   "O"
  ],
  [
   "...",
   "..."
  ]
 ]
}
```

`tokens` is `[token, tag]` pairs, tags in `O` / `B-HE` / `I-HE`. Multi-token terms
such as *bituach leumi* are `B-HE I-HE`, which is why the scheme is not a binary flag.

## How it was built

- **generator**: see repo
- **annotator**: see repo
- **sentences**: 18
- **model agreement**: 83.3%
- **human-reviewed tasks**: 6
- **built**: 2026-09-22

Generation was term-seeded: the model was given one Hebrew term and asked for
sentences using it, and any generation where the term did not word-boundary match was
rejected. Annotation was a second, **blind** pass by a different model family that was
not told the seed term. Agreements were auto-accepted, disagreements were reviewed by
a human, and a random 10% sample of the agreements was also human-audited.

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
