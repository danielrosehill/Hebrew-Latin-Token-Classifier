"""Spelling variation in romanized Hebrew.

There is no single correct romanization, and the one people actually type is
rarely the careful one. `ma'alit` is more accurate; almost everyone writes
`maalit`. A classifier trained only on the careful form will miss the common one,
and a lexicon keyed on the careful form will not match it either.

Two functions, doing different jobs:

  normalise(term)   collapse a term to a canonical key, for MATCHING. Aggressive
                    and lossy on purpose -- "ma'alit", "maalit" and "ma-alit" all
                    become the same key.

  variants(term)    plausible alternative spellings, for TRAINING. Conservative
                    on purpose -- only substitutions Israelis genuinely write,
                    capped so one term cannot flood the corpus.

The substitutions come from the consonants with no settled English spelling:

  ח כ   ch / kh / h     machsom, mahsom
  צ     tz / ts / z     tzav, tsav
  ק     k / q           kupa, qupa
  א ע   ' or nothing    ma'alit, maalit
  Definite article      ha'X / haX / ha-X

Deliberately NOT included: vowel respellings (o/oh, u/oo, ei/ey/ay). They
multiply combinations fast and are far less common in practice than dropping an
apostrophe, which is the dominant real-world variation.
"""
from __future__ import annotations

import re

APOSTROPHES = "'’ʼ`´"

# (pattern, replacements) applied to produce variants. Order matters only for
# readability; each is applied independently to the base form.
_SUBS: list[tuple[str, tuple[str, ...]]] = [
    ("ch", ("kh", "h")),
    ("kh", ("ch", "h")),
    ("tz", ("ts", "z")),
    ("ts", ("tz",)),
    ("q", ("k",)),
]

_NORM_SUBS = [
    (re.compile(r"[" + APOSTROPHES + r"]"), ""),
    (re.compile(r"[-_]"), " "),
    (re.compile(r"\bkh"), "ch"),
    (re.compile(r"kh"), "ch"),
    (re.compile(r"\bts"), "tz"),
    (re.compile(r"ts"), "tz"),
    (re.compile(r"q"), "k"),
    (re.compile(r"(.)\1"), r"\1"),        # doubled consonants: shabbat -> shabat
    (re.compile(r"\s+"), " "),
]


def normalise(term: str) -> str:
    """Canonical matching key. Lossy by design — use for lookup, never for output."""
    out = term.strip().lower()
    for pattern, repl in _NORM_SUBS:
        out = pattern.sub(repl, out)
    # h and ch collapse only at the end, so "hanuka"/"chanuka" meet but "har"
    # and "char" are not forced together mid-word more than once.
    out = re.sub(r"\bch", "h", out)
    out = re.sub(r"ch", "h", out)
    # A final -h is decorative in most schemes: chanukah / hanuka, hoda'a / hodaah.
    out = re.sub(r"h\b", "", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def variants(term: str, *, limit: int = 4) -> list[str]:
    """Plausible alternative spellings, most likely first, excluding `term`."""
    base = term.strip().lower()
    seen = {base}
    out: list[str] = []

    def add(candidate: str) -> None:
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)

    # 1. Dropping the apostrophe is by far the most common real variation.
    stripped = re.sub(f"[{APOSTROPHES}]", "", base)
    add(stripped)

    # 2. ha'X / haX / ha-X for the definite article inside a compound.
    if re.search(f"ha[{APOSTROPHES}]", base):
        add(re.sub(f"ha[{APOSTROPHES}]", "ha-", base))
    elif re.search(r"\bha[aeiou]", stripped):
        add(re.sub(r"\bha([aeiou])", r"ha'\1", stripped))

    # 3. A trailing -h is optional in most schemes.
    if stripped.endswith("h") and len(stripped) > 3:
        add(stripped[:-1])
    elif re.search(r"[aeiou]$", stripped):
        add(stripped + "h")

    # 4. Consonants with no settled spelling, applied to the apostrophe-free form
    #    since that is what people type.
    for pattern, replacements in _SUBS:
        if pattern not in stripped:
            continue
        for replacement in replacements:
            add(stripped.replace(pattern, replacement))

    return out[:limit]


def variant_map(terms) -> dict[str, str]:
    """variant -> canonical term, skipping any variant that collides with a real
    term. A collision means the two words are genuinely ambiguous in writing and
    guessing between them would be worse than not matching."""
    canonical = {t.strip().lower() for t in terms}
    mapping: dict[str, str] = {}
    clashes: set[str] = set()
    for term in sorted(canonical):
        for v in variants(term):
            if v in canonical:
                continue
            if v in mapping and mapping[v] != term:
                clashes.add(v)
                continue
            mapping[v] = term
    for v in clashes:
        mapping.pop(v, None)
    return mapping
