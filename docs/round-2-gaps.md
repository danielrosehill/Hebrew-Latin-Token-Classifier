# Round 2 — what the first corpus got wrong

Written 2026-09-22, from Daniel's 498 review decisions and the resulting corpus.
This is the brief for a second generation round.

## The corpus as built

1,960 positive spans over 603 terms. Term-disjoint splits, zero leakage. But the
distribution is not what the data plan intended.

| Category | Spans | Share | Terms in inventory | Drop rate at review |
| --- | --- | --- | --- | --- |
| colloquial | 413 | 21.1% | 145 | **50%** |
| food_shopping | 239 | 12.2% | 94 | **57%** |
| *discovered* (mostly `tofes`) | 232 | 11.8% | 0 | — |
| health | 189 | 9.6% | 68 | 34% |
| home_utilities | 183 | 9.3% | 66 | 47% |
| religious_calendar | 176 | 9.0% | 69 | 14% |
| transport_geography | 167 | 8.5% | 64 | 21% |
| bureaucracy | 93 | 4.7% | 120 | 22% |
| finance | 33 | 1.7% | 9 | **0%** |
| religious | 31 | 1.6% | 17 | **0%** |
| shopping | 21 | 1.1% | 7 | **0%** |
| government | 9 | 0.5% | 2 | **0%** |
| documents / education / military / services / social / time / work / childcare / emergency / sports / tourism / weather / beverages | 3-8 each | <0.5% each | 1-2 each | — |

## Three problems

### 1. A single term is 11% of the corpus

`tofes` alone carries **219 of 1,960 spans**. The next most frequent term has 9.

This is fallout from the fabricated `tofes NNNN` family: 27 invented form numbers,
each generating sentences, all correctly narrowed to `tofes` at review. The rulings
were right; the effect is a classifier that will be excellent at one word and learn
proportionally less from the other 602.

**Fix:** cap any single term's share of positives, and bar the generator from
inventing numbered-form families.

### 2. The registers with the highest drop rates are the largest

Colloquial is 21% of the corpus and **half of what was generated was rejected**.
Food/shopping is 12% with a **57% drop rate**. Those two were the biggest slices of
the term inventory and the worst value per term.

The register choice was right — colloquial vocabulary is exactly what TTS botches.
The *term generation* for it was poor: too many near-synonyms, greetings and
interjections that do not survive the "would TTS botch it" test, plus foreign foods
that are anglicised anyway (*merguez*, *taramosalata*, *ful medames*).

**Fix:** keep the register, raise the bar. Fewer terms, better chosen, with the
survivors used as few-shot examples.

### 3. The categories with a 0% drop rate are nearly empty

These are the clearest gaps in the whole corpus — everything generated for them was
accepted, and there was almost nothing generated:

| Category | Terms | Survivors, in full |
| --- | --- | --- |
| government | 2 | *misrad haklita, misrad hapnim* |
| shopping | 6 | *kupa, makolet, osher ad, rami levy, shufersal, maayan 2000* |
| finance | 9 | *arnona, bituach leumi, bituach menhalim, heshbon iska, heshbonit mas, heshbonit mas kabala, kabala, keren hishtalmut, mas hachnasa* |
| religious | 11 | *brit milah, chag, kol nidre, mikve, pidyon haben, rosh chodesh, rosh hashanah, sheva brachot, tisha bav, tu bishvat, upsherin* |

A 0% drop rate over a handful of terms is not a sign of quality — it is a sign the
category was barely attempted. *Misrad hapnim* and *misrad haklita* are two of maybe
thirty government bodies an English-speaker in Israel names untranslated.

Thirteen further categories carry 1-2 terms each, inherited from the predecessor
dataset's own category labels and never expanded: documents, education, military,
services, social, time, work, childcare, emergency, sports, tourism, weather,
beverages.

## What round 2 should do

**Terms first, sentences second.** The lesson of round 1 is that bad terms are the
root cause: a junk term costs three generated sentences, a blind annotation pass and
a review decision before it is removed. Judging terms directly is far cheaper, and it
is where Daniel's judgement has the most leverage.

1. Generate ~500 candidate terms concentrated on the thin categories, plus new
   domains the inventory never had: banking, legal, real estate and rental, vehicles
   and the annual test, telecoms and internet, municipality, pharmacy, post.
2. Daniel judges the **terms** in the review UI — fast, one keystroke each.
3. Generate sentences only for the survivors.
4. Downweight colloquial and food/shopping, seeding them with the round-1 survivors
   as few-shot examples rather than asking cold.
5. Cap `tofes`-style families and any single term's share of the corpus.

## What is already known to work

Categories worth generating more of, by survival rate: `religious_calendar` (14%
drop), `transport_geography` (21%), `bureaucracy` (22%, once the fabricated form
families are excluded), `health` (34%).

The 11 terms Daniel typed in on record tasks were all already on the exclusion list
(*sukkot*, *machane yehuda*, *ramat gan*, *chanukah*, *kanyon azrieli*, *kan*) — so
the inventory has no known *missed* vocabulary from round 1. The gaps are the
categories never attempted, not words the generator forgot.
