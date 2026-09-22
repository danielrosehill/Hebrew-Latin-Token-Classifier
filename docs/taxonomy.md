# Taxonomy — what counts, what doesn't, and what is being held back

Written 2026-09-22. This is the decision record behind
[`data/exclusions.csv`](../data/exclusions.csv). Every category below maps to a
`category` value in that file, and every judgement call is recoverable by editing it —
no regeneration, no new inference.

## The North Star

> **makolet** — a neighbourhood corner shop.

If a rule would exclude *makolet*, the rule is wrong. It is the canonical positive
because it has every property the classifier is for:

- Common in the English speech of English-speakers in Israel.
- **Not** significant enough to be in any major speech corpus.
- Reliably mangled. Dictated on 2026-09-22 it came back as *"macaullete"*. No model
  Daniel has tried gets it.

The target is the long tail of specific Israeli words used in code-switching. Not
Hebrew in general, not translation, not anything English already handles.

## Disposition

Two values in `exclusions.csv`, and a `--posture` flag on `adjudicate.py`:

| Disposition | Conservative build (default) | Expansive build |
| --- | --- | --- |
| `always` | excluded | excluded |
| `conservative` | **excluded** | included |

```bash
python3 scripts/adjudicate.py                        # conservative, the default
python3 scripts/adjudicate.py --posture expansive    # reinstate the judgement calls
```

**The default posture is conservative.** A flagged span is not a label, it is work: it
splits the sentence, adds a separate speech call, and needs the audio stitched back
with padding tuned by ear. A miss costs nothing — the word is read exactly as it is
read today. A false positive gets an English word spoken in Hebrew *and* pays all that
cost to make the output worse.

Measured effect on the 2,733-sentence corpus:

| Posture | Exclusions active | Spans dropped | Agreed spans kept | Disagreement | Review tasks |
| --- | --- | --- | --- | --- | --- |
| conservative | 126 | 494 | 1,760 | 14.7% | 546 |
| expansive | 89 | 293 | 1,832 | 16.3% | 595 |

## Categories

### 1. Core positive — the target

Hebrew words in Latin script that an English voice genuinely botches, with no
established English pronunciation.

*makolet · mashkanta · tlush · maskoret · arnona · mazgan · dud · machsom · miluim ·
tor · balagan · beseder · chagim · hashmal · chufshat leida · osek patur ·
bituach leumi · teudat zehut · mas hachnasa*

Includes words whose gutturals English orthography cannot carry — *challah* would
qualify on phonetics alone were it not already absorbed (see category 2), but
*chagim*, *machsom* and *hashmal* are not absorbed and stay positive.

Not in `exclusions.csv`. This is everything the file does not name.

### 2. `anglicised` — **always excluded**

Hebrew words, modern or ancient, that can be assumed present in an English corpus and
that current TTS renders acceptably with no Hebrew instruction at all.

*kosher · kashrut · shabbat · hummus · tahini · falafel · pita · matzo · bagel ·
rabbi · synagogue · yeshiva · kibbutz · chutzpah · schlep · torah · talmud · seder ·
passover · hanukkah · sukkot · purim · yom kippur · rosh hashanah · shiva · menorah ·
dreidel · yarmulke · kippah · tallit · mezuzah · mitzvah · bar mitzvah · kaddish ·
shofar · knesset · shekel · mossad · kabbalah*

68 terms. Excluded under every posture — reinstating these would be reinstating a
known-bad idea, not a different judgement.

### 3. `function_word` — **always excluded**

Hebrew particles and pronouns. These never entered the corpus honestly: every one is
an artefact of the predecessor dataset's substring matching — *hi* from "t**hi**nk",
*ma* from "**ma**shav", *ach* from "m**ach**som".

*od · po · ma · mi · lo · ken · at · ani · atem · ein · ach · hi · bo · sham · af ·
or · sa · kan · eifo · le'an · me'ayin*

21 terms. Confirmed by Daniel 2026-09-22: there is no context in which these appear
untranslated in English speech.

### 4. `place_name` — excluded, **conservative**

Toponyms: cities, neighbourhoods, streets, squares, regions, named malls.

*tel aviv · jerusalem · haifa · eilat · ashdod · ashkelon · netanya · herzliya ·
raanana · ramat gan · rishon lezion · nes tziona · kfar saba · rosh pina · ofakim ·
galil · golan · negev · dizengoff · ben yehuda · rothschild · ayalon · hahagana ·
palmachim · hof habonim · machane yehuda · kikar rabin · kikar tzion · kanyon azrieli*

32 terms. Place names are a different problem from vocabulary — proper nouns, often
with an established English pronunciation, and a category where a wrong flag is
conspicuous.

**Common nouns that merely sound geographic are NOT here and stay positive:** *kikar*
(square), *rehov* (street), *derech* (road), *sderot* as "boulevard", *tayelet*
(promenade), *mercaz* (centre). Only the proper name is excluded — *kikar rabin* is
out, *kikar* is in.

#### The one edge case: `yerushalayim`

**Included as a positive**, deliberately, and it is the reason this category is
`conservative` rather than `always`.

*Jerusalem* is English and is excluded. *Yerushalayim* is the Hebrew name, used in
English speech by more religiously-oriented speakers, and is not something an English
voice will get right. It is in the corpus with 3 spans and stays there.

The same argument may apply to other Hebrew-name-for-a-place cases as they appear.

### 5. `israel_english` — excluded, **conservative**

Words routine in English-language writing and speech about Israel, but absent from any
English dictionary. Genuinely arguable in both directions.

*haredi · aliyah · moshav · shul*

4 terms. Reopened by Daniel 2026-09-22 after initially sitting in `anglicised`, then
excluded — but held as `conservative` precisely because this is the category most
likely to be revisited.

### 6. `asr_handles_it` — excluded, **conservative**

Words excluded on **observation rather than principle**: some model was seen to get
them right.

*shuk* — rendered correctly by Deepgram, observed 2026-09-22.

1 term. This category exists because the ground is moving. Speech recognition keeps
improving and the set of problematic words keeps shrinking, so an exclusion justified
by "the current model copes" is provisional by nature. Entries here should carry the
model and the date they were checked, and should be re-tested rather than trusted.

**This is the category most likely to be wrong in both directions.** A word one engine
handles, another mangles; the corpus targets the general case, not one vendor.

### 7. Ambiguous — in the corpus, **both senses**

A string that is both a Hebrew word and an ordinary English word. Not excluded —
these are the most valuable training examples there are, and the classifier must
learn the distinction from context.

*dud* (water heater / a failure) · *tor* (appointment / a hill) · *salon* (living
room / hairdresser) · *layla* (night / a name) · *shana* (year) · *tabu* (land
registry) · *sir* (pot)

19 terms, marked `ambiguous` in `data/terms.csv`. Each is generated for twice: as a
Hebrew positive by `generate_samples.py`, and as an English-sense negative by
`generate_negatives.py`. **Neither half works without the other.**

### 8. Brand and company names — **positive by default**

Decided 2026-09-22: *Yad2* is pronounced as Hebrew, so it should be read as Hebrew,
and including brands is the safer side of this particular line.

*Positive:* Hebrew coinages (*Galgalatz*, *Mako*, *Ynet*, *Janglo*) and Hebrew+English
compounds (*Kan Bet*, *Zol Stock*, *Super Pharm*).
*Negative:* ordinary English said in English (*Fox Home*, *Max Stock*, *AM:PM*).

Full table and the unresolved numeral question in
[`annotation-policy.md`](annotation-policy.md).

### 9. Hallucinated terms — removed at review

The term inventory is model-generated and contains invention. The largest cluster was
**27 fabricated `tofes NNNN` tax-form numbers**, plus 6 fabricated `mas hachnasa X`
compounds.

These are not a category to maintain — they are caught by the term-level rollup in
`adjudicate.py`, where the blind annotator's systematic refusal of a term surfaces it
as one review task instead of three. Ruling the term out removes all of its sentences.

## Changing your mind

This is designed to be revisited, because the underlying facts move — models improve,
and judgement calls made in one sitting look different in another.

| To do this | Edit | Cost |
| --- | --- | --- |
| Stop excluding a term | delete its row, or set `disposition: conservative` and build expansive | re-run `adjudicate.py` + `build_splits.py` |
| Start excluding a term | add a row with a category and note | same |
| Reinstate every judgement call at once | `--posture expansive` | same |
| Change what is *generated* | edit `data/terms.csv` and re-run generation | a new generation pass |

Nothing in the first three rows costs an API call. The corpus, the annotations and the
adjudication are all on disk; only the filtering changes.

**Ship the conservative build as the default artefact.** If a use case wants heavier
classification — more recall, more willingness to flag — that is the expansive build,
and it should be published as a separate configuration with this table attached, not
as a silent difference.

## Spelling variation

Added 2026-09-22, raised by Daniel: *"some of them correctly have an apostrophe in
the transliterated Hebrew, but in practice people don't usually do that even though
it's more accurate."*

There is no settled romanization of Hebrew, and the spelling people type is rarely
the careful one. **56% of the term inventory has at least one plausible variant.**
The inventory itself already carried the same word twice — *ba'al bayit* and *baal
bayit*, *choze* and *chozeh*, *do'ach* and *doach* — which would have trained the
classifier on two unrelated-looking terms and split their examples between them.

### What varies

| Source | Spellings | Example |
| --- | --- | --- |
| א ע (glottal) | `'` or nothing | *ma'alit* / *maalit* |
| Definite article | `ha'X` / `haX` / `ha-X` | *misrad ha'avoda* / *misrad haavoda* |
| ח כ | `ch` / `kh` / `h` | *machsom* / *makhsom* / *mahsom* |
| צ | `tz` / `ts` / `z` | *tzav* / *tsav* |
| ק | `k` / `q` | *kupa* / *qupa* |
| Final ה | `-ah` / `-a` | *chanukah* / *chanuka* |

Vowel respellings (`o`/`oh`, `u`/`oo`, `ei`/`ey`) are **deliberately excluded**: they
multiply combinations fast and are far less common in practice than dropping an
apostrophe, which is the dominant real-world variation.

### Two mechanisms, doing different jobs

`scripts/lib/orthography.py`:

- **`normalise(term)`** — collapses a term to a canonical key, for **matching**.
  Aggressive and lossy on purpose. Use it for lexicon lookup at inference, never
  for output. `ma'alit`, `maalit` and `ma-alit` all become one key.
- **`variants(term)`** — plausible alternative spellings, for **training**.
  Conservative on purpose, capped so one term cannot flood the corpus.

### The canonical spelling is the one without the apostrophe

`merge_round2.py` collapses spellings that normalise to the same key and picks the
apostrophe-free form as canonical, keeping the careful spelling as a variant rather
than discarding it. Rationale: the apostrophe-free form is what people type, so it is
what the classifier will mostly see.

### Variants cost nothing to generate

`scripts/add_spelling_variants.py` substitutes a variant into a span in a sentence
already in the corpus and recomputes the offsets. The sentence was already good, so
the copy is as clean as the original, and **no model is called**.

Two rules keep it honest, both enforced rather than assumed:

- **Variant copies stay in their source sentence's split.** A near-duplicate across
  the train/test boundary would let the model score on a sentence it memorised.
  Verified: 0 sentences whose variant copy landed in a different split.
- **No variant that collides with a real inventory term is used.** If two words are
  genuinely ambiguous in writing, guessing between them is worse than not matching.
  30 such collisions exist — *halva* (sweet) against *halva'ah* (loan) among them.

Result on the first corpus: **690 variant sentences, 0 misaligned spans**, and
`tofes`'s share of positives fell from 11.2% to 8.2% as a side effect of dilution.

### At inference

A lexicon keyed on the careful spelling will not match what people type. Look terms
up through `normalise()`, not by exact string. This is the half of the problem the
corpus alone cannot solve.
