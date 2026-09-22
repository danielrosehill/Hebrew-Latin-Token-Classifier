---
title: Hebrew-in-Latin Span Review
emoji: 🔤
colorFrom: blue
colorTo: indigo
sdk: static
app_file: index.html
pinned: false
license: mit
---

# Hebrew-in-Latin span review

The manual review stage of
[danielrosehill/Hebrew-Latin-Token-Classifier](https://github.com/danielrosehill/Hebrew-Latin-Token-Classifier).

Two models propose spans — a generator that seeds each sentence with a Hebrew term,
and a blind annotator from a different model family that never sees the seed. Where
they agree, the span is accepted automatically. This page is for the cases they
disagree on, plus a random audit sample of the ones they agreed on.

**Round 2 — 614 candidate terms**, grouped by category.

Round 1's span review is complete. This pass judges TERMS directly, before any
sentences are generated for them: one keystroke each, and nothing is spent on a
term until it survives. It targets the categories round 1 barely attempted —
government, legal, military, education, vehicles, real estate, telecoms,
emergency — plus domains the inventory never had.

The only test: **would an English TTS voice mispronounce it, the way every model
mangles *makolet*?** If an English speaker with no Hebrew would read it correctly,
exclude it.

**Include** means the classifier flags the span, so the TTS gets a Hebrew segment
for it. **Exclude** means leave it as English. Most terms here are Hebrew either
way — the question is whether flagging one is worth the sentence split, the extra
speech call and the audio stitching it costs.

**Everything runs in your browser.** The queue is fetched as a static file, decisions
are held in `localStorage`, and nothing is sent anywhere. Export `decisions.json` when
you are done and run `scripts/build_splits.py` in the repo.

## Keys

| Key | Action |
| --- | --- |
| <kbd>y</kbd> | Include — or, on a boundary task, keep the full span |
| <kbd>n</kbd> | Exclude — or, on a boundary task, use the shorter span |
| <kbd>x</kbd> | Neither — boundary tasks only; tag nothing here |
| <kbd>n</kbd> | On a boundary task: the parts, which may be several |
| <kbd>d</kbd> | Can't decide — records that you looked, and never asks again |
| <kbd>Enter</kbd> | Submit typed terms (record tasks) |
| <kbd>s</kbd> | Skip |
| <kbd>u</kbd> | Undo the previous decision |

## The rule

The test is **pronunciation, not etymology**: would an English TTS voice mispronounce
this word, and would treating it as Hebrew fix that?

- *kosher*, *Shabbat*, *kashrut*, *hummus*, *rabbi* — **no**. English says them
  acceptably, and they are filtered out automatically before you see them.
- **When unsure, say no.** A flagged span splits the sentence, adds a separate speech
  call and needs the audio stitched back together. A miss costs nothing; a false
  positive does all that work to make the output worse.
- *makolet*, *mashkanta*, *challah*, *dud* — **yes**.
- Israeli brand names — **yes** by default. *Yad2* is pronounced as Hebrew.
- A string that only appears inside a longer English word — **no**. "think" does not
  contain *hi*.

Full policy: [annotation-policy.md](https://github.com/danielrosehill/Hebrew-Latin-Token-Classifier/blob/main/docs/annotation-policy.md)
