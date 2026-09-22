#!/usr/bin/env python3
"""Publish the review UI to a Hugging Face Space, with the current queue baked in.

The Space is `sdk: static` — no server, no build. The queue is uploaded as a plain
file next to the page, decisions live in the reviewer's `localStorage`, and nothing
is ever sent back. That keeps review possible from any machine or phone without
standing up a backend, at the cost of decisions being per-browser: export
decisions.json and commit it to the repo when finished.

Re-run this after every `adjudicate.py` to refresh the queue.

Dry run by default; --push publishes to a public URL.

    python3 scripts/publish_space.py
    python3 scripts/publish_space.py --push
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPACE = ROOT / "space"
QUEUE = ROOT / "review" / "queue.json"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default="danielrosehill/hebrew-latin-span-review")
    p.add_argument("--private", action="store_true")
    p.add_argument("--queue", default=str(QUEUE),
                   help="which queue to bake in (e.g. review/queue-terms.json)")
    p.add_argument("--push", action="store_true")
    args = p.parse_args()

    queue_path = pathlib.Path(args.queue)
    if not queue_path.exists():
        raise SystemExit(f"no {queue_path} — run adjudicate.py or build_term_queue.py")
    shutil.copy(queue_path, SPACE / "queue.json")

    tasks = json.loads(queue_path.read_text())
    by_risk: dict[str, int] = {}
    for t in tasks:
        by_risk[t["risk"]] = by_risk.get(t["risk"], 0) + 1

    files = sorted(f for f in SPACE.iterdir() if f.is_file())
    print(f"space   {args.repo} ({'private' if args.private else 'public'})")
    print(f"queue   {len(tasks)} tasks — {json.dumps(by_risk)}")
    for f in files:
        print(f"  upload  space/{f.name}  ({f.stat().st_size:,} bytes)")

    if not args.push:
        print("\ndry run — pass --push to publish. This creates a public page.")
        return

    token = os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        raise SystemExit("HUGGINGFACE_TOKEN not set")
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(args.repo, repo_type="space", space_sdk="static",
                    private=args.private, exist_ok=True)
    api.upload_folder(folder_path=str(SPACE), repo_id=args.repo, repo_type="space")
    print(f"\nhttps://huggingface.co/spaces/{args.repo}")


if __name__ == "__main__":
    main()
