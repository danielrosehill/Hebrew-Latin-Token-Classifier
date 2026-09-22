# Hebrew-Latin-Token-Classifier

A token classifier that identifies **Hebrew words written in Latin characters**
inside English text — *"I'm going to **Bituach Leumi** today"*, *"pick up some
**challah** from the **makolet**"*.

Nothing like it exists. There is no `heb_Latn` label in GlotLID v3, `lid.176` or
`lid218e`; no token-level code-switching model covers Hebrew; and no Hebrew-English
code-switching corpus is published anywhere. Survey:
[Hebrew-Small-Models-Planning/docs/prior-art.md](https://github.com/danielrosehill/Hebrew-Small-Models-Planning/blob/main/docs/prior-art.md).

**Status 2026-09-22: corpus preparation. No model has been trained.** The immediate
deliverable is a reviewed, span-annotated corpus; the model follows it.

Planning, requirements and the downstream use case live in the sibling repo
[**Hebrew-Small-Models-Planning**](https://github.com/danielrosehill/Hebrew-Small-Models-Planning).
This repo is the first of the small models that plan describes.

## Why it exists

The immediate consumer is the *My Weird Prompts* podcast, which is AI-generated,
produced in Israel and voiced by Chatterbox TTS. Hebrew words in its scripts get read
as English grapheme strings — *challah* becomes "chala", the guttural ח collapsing to
an English "ch". Detecting those spans is the first step to synthesising them with a
Hebrew voice.

The classifier is deliberately general-purpose, though. Span detection is useful
anywhere romanized Hebrew appears in English text.

## Source data

[`danielrosehill/English-Hebrew-Mixed-Sentences`](https://huggingface.co/datasets/danielrosehill/English-Hebrew-Mixed-Sentences)
— 516 LLM-generated, human-read sentences each containing at least one Hebrew word in
natural context, MIT licensed. Built for the
[`Whisper-Hebrish`](https://huggingface.co/danielrosehill/Whisper-Hebrish) ASR
fine-tune, reused here.

The three JSONL splits are vendored under `data/source/` so the annotation is
reproducible against a fixed input. The 516 WAV files are **not** copied — this is a
text task.

## Two defects in the source labels, both measured

The dataset carries one `hebrew_word` per record. Treating that as ground truth would
produce a badly wrong corpus.

| | Count | Of 474 labelled |
| --- | --- | --- |
| Label aligns with a word in the sentence | 360 | 76% |
| **Label matches only *inside* another word** | **114** | **24%** |
| No label at all (but Hebrew is present) | 42 | — |

The labels were evidently produced by **substring search**. `hi` was labelled from
*t**hi**nk*; `har` from *P**har**m*; `ma` from *__ma__shav*; `gan` from *maz**gan***;
`ach` from *m**ach**som*; `chool` from *s**chool***. In all 114 of those records the
*real* Hebrew term — *dud*, *mashkanta*, *mirsham*, *tlush*, *maskoret*, *hashmal*,
*chufshat leida* — is not labelled at all.

The same contamination reaches the term list: 12 of the 139 distinct terms
(`ach ani atem ein har hi ken latke lo ma mi supermarket`) **never occur as whole
words anywhere in the corpus**. They exist only as bad labels.

Separately, 17 terms are ordinary English words (`at`, `hi`, `lo`, `ken`, `baby`,
`chicken soup`, `supermarket`, …), so matching them fires on genuine English.

Terms failing either test are **quarantined** — kept with their reason, excluded from
automatic matching until a human rules on them. 117 of 139 remain active.

> Earlier note, corrected: a substring check of labels against their sentences
> returns zero exceptions. That test is worthless here, because passing it is exactly
> what a substring-generated label does. Word-boundary matching is the real test and
> it fails 114 times.

## The annotation pass

Programmatic first pass, human review second. The machine proposes; it does not
decide.

```
data/source/*.jsonl                        516 records, vendored
        │
        ├─ scripts/build_lexicon.py  ───▶  data/lexicon.csv        139 terms, 117 active
        │
        ├─ scripts/annotate.py       ───▶  data/annotations/spans.jsonl
        │                                  review/queue.json       242 tasks, worst first
        │
        ├─ review/index.html         ───▶  review/decisions.json   (you)
        │
        └─ scripts/apply_decisions.py ──▶  data/gold/*.jsonl       BIO corpus
```

Current queue — **242 tasks**, ordered worst-first:

| Risk | Tasks | What you are deciding |
| --- | --- | --- |
| `mislabelled` | 114 | The dataset's label is bogus. Type the real Hebrew term(s) |
| `unmatched` | 42 | No lexicon term matched. Type any Hebrew term(s) present |
| `quarantined` | 55 | A quarantined term matched here. Real, or a false positive? |
| `medium` | 20 | Single-token lexicon match that is not this record's own label |
| `low` | 11 | Multi-token lexicon match, probably right |

360 spans are pre-accepted because they come from an aligned dataset label and are
not queued. Every span that has not been positively accepted stays `O` in the BIO
output, so the corpus is never silently wrong.

## Running the review

```bash
python3 scripts/build_lexicon.py     # 139 terms -> data/lexicon.csv
python3 scripts/annotate.py          # -> data/annotations/, review/queue.json
python3 scripts/serve_review.py      # opens http://127.0.0.1:8765/index.html
```

The UI is one HTML file, no dependencies, no build step. Keyboard: <kbd>y</kbd>
Hebrew, <kbd>n</kbd> not Hebrew, <kbd>Enter</kbd> submit typed terms, <kbd>s</kbd>
skip, <kbd>u</kbd> undo. Progress is kept in `localStorage`, so you can close the tab
and pick up where you left off. **Download decisions.json** saves it to
`review/decisions.json`, then:

```bash
python3 scripts/apply_decisions.py   # -> data/gold/*.jsonl + report.json
```

Terms you type that cannot be found on a word boundary are listed in
`data/gold/report.json` rather than dropped.

Serving over HTTP is required — browsers block `fetch()` from `file://`, so opening
`review/index.html` directly will show a message saying so.

## Output format

`data/gold/{train,validation,test}.jsonl`, splits preserved from the source so they
stay comparable with the Whisper fine-tune:

```json
{"id": "1_3",
 "text": "... including a passport and a teudat zehut.",
 "spans": [{"start": 86, "end": 98, "surface": "teudat zehut", "term": "teudat zehut"}],
 "tokens": [["Opening", "O"], ["a", "O"], ..., ["teudat", "B-HE"], ["zehut", "I-HE"], [".", "O"]]}
```

Two labels plus `O`, CoNLL-style BIO. Multi-token terms are `B-HE I-HE`, which is why
the tag scheme is not a plain binary flag — 51 of 139 terms are multi-token.

## Planned model

`xlm-roberta-base` fine-tuned for token classification, following the **EnTaCs**
English-Tamil code-switching recipe (arXiv 2603.26587) — the closest published
template, and deliberately small: ~500 utterances, three labels, CoNLL format.

EnTaCs reports macro-F1 **0.844** with the romanized class at **F1 0.638**. Plan for
roughly that on the romanized class, not 0.9. An imperfect classifier is still
useful here: it is paired with a lexicon that carries the high-frequency terms, and
precision is weighted over recall — a miss changes nothing, a false positive makes an
English word be read in Hebrew.

## Layout

| Path | Contents |
| --- | --- |
| `data/source/` | Vendored source splits — do not edit |
| `data/lexicon.csv` | Term list with quarantine status and reason |
| `data/annotations/` | Machine-proposed spans, BIO tokens, summary counts |
| `data/gold/` | Reviewed corpus (generated; absent until review is applied) |
| `review/` | Single-file review UI and its queue |
| `scripts/` | The four steps above |
| `docs/` | Annotation policy and decisions |

## Licence

Code MIT. `data/source/` is redistributed from `English-Hebrew-Mixed-Sentences`, MIT,
by the same author.
