# Annotation policy

What counts as a positive span. Written 2026-09-22, before review starts, so the
decisions are consistent across a session and legible to whoever picks this up next.

Open questions are marked **UNDECIDED** — they are the ones to settle in the first
twenty review tasks, then record the answer here.

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
consistent. When genuinely unsure, **say no**: precision is weighted over recall,
because a miss leaves today's behaviour unchanged while a false positive makes an
English word be read in Hebrew.

## Settled cases

| Case | Decision | Reason |
| --- | --- | --- |
| Hebrew word inside an English sentence | **positive** | The core case |
| Multi-token institutional terms — *Bituach Leumi*, *teudat zehut*, *osek patur* | **positive**, one span | They are one unit and the TTS needs them as one |
| Hebrew term with English plural — *latkes*, *chagim* used as a plural | **positive**, span covers the whole surface form | The pronunciation problem is in the stem |
| Guttural ח / כ words | **positive** | English orthography cannot represent them |
| Anglicised Hebrew — *kosher*, *rabbi*, *Shabbat*, *hummus* | **negative** | Already pronounced acceptably |
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

**Brand and company names.** The dataset's 42 unlabelled records are full of them:
*10 Bis*, *Zol Stock*, *Max Stock*, *Super Pharm*, *Rami Levy*, *Aroma*, *Cellcom*,
*Yad2*, *Ynet*, *Mako*, *Arutz 12*, *Galgalatz*, *Kan Bet*, *AM:PM*, *Tubi60*,
*El Al*, *Janglo*, *Castro*, *Fox Home*, *Nefesh b'Nefesh*.

These are a real category the lexicon does not model, and they split several ways:
*Super Pharm* is English words in an Israeli brand; *Yad2* and *Arutz 12* mix Hebrew
with a numeral; *Galgalatz* is Hebrew and would certainly be mispronounced.

*Provisional:* judge by the operational test, per brand, and add each decision to the
table above as it is made. Numerals inside a brand need their own rule — an `en`
segment containing a numeral spoken as Hebrew would be wrong.

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
