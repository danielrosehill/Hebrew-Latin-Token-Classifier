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

**591 tasks**, ordered worst-first: 50 term rulings, 97 span-boundary questions,
the spans one model found and the other did not, and a 242-sentence random audit
of cases both models agreed on.

**Everything runs in your browser.** The queue is fetched as a static file, decisions
are held in `localStorage`, and nothing is sent anywhere. Export `decisions.json` when
you are done and run `scripts/build_splits.py` in the repo.

## Keys

| Key | Action |
| --- | --- |
| <kbd>y</kbd> | Hebrew — or, on a boundary task, keep the full span |
| <kbd>n</kbd> | Not Hebrew — or, on a boundary task, use the shorter span |
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
