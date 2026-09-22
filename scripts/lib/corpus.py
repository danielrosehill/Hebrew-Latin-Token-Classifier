"""Shared corpus helpers: tokenisation, span matching, BIO tagging, JSONL IO."""
from __future__ import annotations

import fcntl
import json
import pathlib
import re

TOKEN_RE = re.compile(r"\w+(?:'\w+)?|[^\w\s]")


def word_spans(text: str, term: str) -> list[tuple[int, int]]:
    """Every word-boundary occurrence of `term`. Empty means the term is not there —
    which is the rejection test the source dataset's labels would have failed."""
    pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
    return [(m.start(), m.end()) for m in pattern.finditer(text)]


def bio_tags(text: str, spans: list[dict]) -> list[list[str]]:
    tags = []
    for m in TOKEN_RE.finditer(text):
        tag = "O"
        for s in spans:
            if m.start() >= s["start"] and m.end() <= s["end"]:
                tag = "B-HE" if m.start() == s["start"] else "I-HE"
                break
        tags.append([m.group(0), tag])
    return tags


def read_jsonl(path: pathlib.Path, *, dedupe_on: str | None = None) -> list[dict]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if dedupe_on:
        seen = {r[dedupe_on]: r for r in rows}
        return list(seen.values())
    return rows


def append_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    """Append under an exclusive lock. The generation and annotation passes are
    resumable, which invites running two at once; without the lock they interleave
    and duplicate rows (observed 2026-09-22: 36 sentences produced 52 annotations)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
