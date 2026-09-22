# Annotation policy

What counts as a positive span. Written 2026-09-22, before review starts, so the
decisions are consistent across a session and legible to whoever picks this up next.

Open questions are marked **UNDECIDED** — settle them in the first twenty review tasks,
then record the answer here. Decisions already taken are marked **DECIDED** with a date.

## The label

One entity type, `HE`: a **Hebrew word rendered in Latin characters**. BIO tagging,
so a multi-token term is `B-HE I-HE` (51 of 139 known terms are multi-token).

## The operational test

Not "is this word etymologically Hebrew?" but:

> **Would an English TTS voice mispronounce it, and would tagging it as Hebrew fix
> that?**

This is a pronunciation task, not an etymology task. It follows that:

- **Words the English corpus has absorbed are negatives.** *Kosher*, *Shabbat*,
  *hummus*, *rabbi*, *kibbutz*, *chutzpah* are read acceptably by an English voice.
  Tagging them would change working output for no gain.
- **Words the English corpus lacks are positives.** *Bituach Leumi*, *makolet*,
  *mashkanta*, *tlush*, *mazgan*, *arnona*, *dud*.
- **Guttural phonemes are always positives.** *Challah*, *chagim*, *machsom*,
  *hashmal* — English orthography cannot represent ח or כ, so an English voice
  cannot get them right.

The boundary between the first two is a judgement call and will not be perfectly
consistent. When genuinely unsure, **say no**.

### Why the default is no — DECIDED 2026-09-22

Daniel's rule: *"each time we flag a word as being Hebrew in Latin characters it's
going to trigger downstream actions — it's going to add complication. I'd rather it's
selective on the things that truly get botched in TTS."*

A flagged span is not a label, it is **work**. It splits the sentence, adds a separate
speech call for the fragment, and requires the audio to be stitched back together with
padding tuned by ear. So the two errors are not symmetric:

| Error | Cost |
| --- | --- |
| Missed a Hebrew word | Current behaviour, unchanged. The word is read as it is read today |
| Flagged an English word | It gets spoken in Hebrew, **and** the pipeline does all that work to make it worse |

A miss is free. A false positive is expensive twice over. Err towards no.

### Anglicised Hebrew — always negative, and applied automatically

A large class of Hebrew words, modern and ancient, can be assumed present in an
English corpus. Today's TTS renders them acceptably with no Hebrew language
instruction at all. **They are always negative** — *kosher*, *kashrut*, *Shabbat*,
*challah*, *hummus*, *tahini*, *falafel*, *Torah*, *seder*, *Hanukkah*, *Sukkot*,
*shiva*, *menorah*, *yarmulke*, *mitzvah*, *bar mitzvah*, *Knesset*, *shekel*,
*aliyah*.

This is not left to per-case judgement. The class is known and finite, so it lives in
[`data/anglicised.csv`](../data/anglicised.csv) — 72 terms, each with its basis
(`dictionary` where the word is in the system English dictionary, `curated`
otherwise) — and `adjudicate.py` drops those spans before the review queue is built.
On the first corpus that removed **264 spans across 38 terms** and took the model
disagreement rate from 20.8% to 16.3%.

**The file is meant to be edited.** Adding a term removes it from the corpus and from
the queue on the next `adjudicate.py` run. Reviewing 72 lines once is strictly better
than answering the same question 264 times, and it leaves an auditable record of what
was excluded and why — which a fuzzy instruction to a model does not.

Borderline entries currently on the list, flagged as the ones most worth arguing
about: *haredi*, *aliyah*, *moshav*, *shul*. Each is routine in English writing about
Israel, but none is in an English dictionary.

## Settled cases

| Case | Decision | Reason |
| --- | --- | --- |
| Hebrew word inside an English sentence | **positive** | The core case |
| Multi-token institutional terms — *Bituach Leumi*, *teudat zehut*, *osek patur* | **positive**, one span | They are one unit and the TTS needs them as one |
| Hebrew term with English plural — *latkes*, *chagim* used as a plural | **positive**, span covers the whole surface form | The pronunciation problem is in the stem |
| Guttural ח / כ words | **positive** | English orthography cannot represent them |
| Anglicised Hebrew — *kosher*, *rabbi*, *Shabbat*, *hummus*, *kashrut* | **negative** | Already pronounced acceptably. Enforced by `data/anglicised.csv`, not by judgement |
| Hebrew function words and particles — *od*, *po*, *ma*, *mi*, *lo*, *ken* | **negative** | Confirmed by Daniel 2026-09-22: there is no context in which these appear untranslated in English speech. They entered the term list as substring artefacts |
| A lexicon term matching inside a longer word — *ma* in *moshav* | **negative** | This is the source dataset's defect; do not reproduce it |
| English words that happen to be quarantined terms — *at*, *hi*, *lo*, *baby* | **negative** when used as English | Quarantine exists to catch exactly these |

## UNDECIDED — settle these early

**Place names.** *Tel Aviv*, *Jerusalem*, *Haifa*, *Eilat* are pronounced acceptably
in English and are probably negatives. But *Ashdod*, *Ashkelon*, *Palmachim*,
*Hof HaBonim*, *Galil* are less certain, and the source lexicon contains all of them.
A consistent rule is needed, not case-by-case instinct.

*Provisional:* negative if it has a conventional English pronunciation, positive
otherwise. Record what you actually do.

**Street and road names.** *Dizengoff*, *Ben Yehuda*, *Ayalon*, *Rothschild*,
*Hahagana*. Note *Rothschild* is Germanic, not Hebrew, and is already quarantined as
an English homograph.

### Brand and company names — DECIDED 2026-09-22: positive by default

**Israeli brand and company names are positives.** Decided by Daniel: *Yad2* is
pronounced as Hebrew, so it should be read as Hebrew, and including brand names is the
safer option — a brand read in Hebrew by an Israeli-context podcast is right far more
often than it is wrong.

The dataset's 42 unlabelled records are full of them: *10 Bis*, *Zol Stock*,
*Max Stock*, *Super Pharm*, *Rami Levy*, *Aroma*, *Cellcom*, *Yad2*, *Ynet*, *Mako*,
*Arutz 12*, *Galgalatz*, *Kan Bet*, *AM:PM*, *Tubi60*, *El Al*, *Janglo*, *Castro*,
*Fox Home*, *Nefesh b'Nefesh*.

Apply the default, and override only where the operational test clearly says otherwise
— a brand whose name is ordinary English words pronounced in English (*Fox Home*,
*Max Stock*) is a negative.

| Brand shape | Decision | Example |
| --- | --- | --- |
| Hebrew word or coinage | **positive** | *Galgalatz*, *Mako*, *Ynet*, *Janglo* |
| Hebrew + numeral | **positive** — but see the numeral trap | *Yad2*, *Arutz 12*, *10 Bis*, *Tubi60* |
| Hebrew + English word | **positive** | *Kan Bet*, *Zol Stock*, *Super Pharm* |
| Ordinary English words, said in English | **negative** | *Fox Home*, *Max Stock*, *AM:PM* |
| International brand, said in English | **negative** | *Castro* (as pronounced), *Aroma* |

**The numeral trap — unresolved, and it belongs to pass 3, not here.** *Yad2* is said
*yad shtayim*; *Arutz 12* is *arutz shteim-esre*. A digit handed to a Hebrew TTS
segment will be read as a Hebrew numeral, which is usually right — but *10 Bis* is
said *ten bis*, with the number in English. Annotate the span as Hebrew regardless;
record the spoken form in the lexicon's notes so pass 2 can emit the right Hebrew, and
let pass 3 keep digits out of segments where they would be read in the wrong language.
See [`pipeline.md`](pipeline.md).

**Proper names of people.** *Netanyahu*, *Herzog*. Probably negative for well-known
figures. Not yet represented in the corpus.

## Span boundaries

- Spans cover the **surface form** as it appears, including English affixes
  (*latkes*, *chagim*, *supermarkets* if it were positive).
- Spans do not include the preceding article, even when Hebrew takes one: tag
  *makolet*, not *the makolet*, and not *ha-makolet* unless *ha-* is actually written.
- Punctuation is outside the span.
- Adjacent Hebrew words that form a unit are one span (*Bituach Leumi*); adjacent
  Hebrew words that do not are separate spans.

## Reviewing against the machine pass

`scripts/annotate.py` proposes; it never decides. Two rules keep that honest:

1. **Only positively accepted spans become `B-HE`/`I-HE`.** Anything unreviewed or
   rejected stays `O`. An incomplete review yields an under-labelled corpus, which is
   a known quantity, rather than a wrong one.
2. **Typed terms that cannot be word-boundary matched are reported, not dropped** —
   `data/gold/report.json`. A typo in the review UI surfaces instead of vanishing.

The 360 spans that come from an aligned dataset label are pre-accepted and not
queued. That is a deliberate trade: it assumes an aligned label is correct, which is
a weaker assumption than trusting the labels wholesale, but not a free one. If the
review turns up aligned labels that are also wrong, stop and re-queue them.
