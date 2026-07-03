"""Emit the forecast delta between a git ref and the working tree.

    uv run python scripts/pr_delta.py --base-ref origin/main --out delta.md

Writes markdown to --out (default stdout) and, when $GITHUB_OUTPUT is set,
appends `changed=true|false` for workflow conditionals. Exits nonzero if the
head model fails to load — that makes CI reject broken model edits.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from waterline.delta import compare, snapshot

MODEL_FILES = ["models/cpi/tree.yaml", "registry/assumptions.yaml"]


def snapshot_from_ref(ref: str):
    tmp = Path(tempfile.mkdtemp(prefix="waterline-base-"))
    for rel in MODEL_FILES:
        content = subprocess.run(
            ["git", "show", f"{ref}:{rel}"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return snapshot(tmp)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    base = snapshot_from_ref(args.base_ref)
    head = snapshot(ROOT)
    md, changed = compare(base, head)

    if args.out:
        Path(args.out).write_text(md + "\n", encoding="utf-8")
    else:
        print(md)

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
    print(f"\nchanged={changed}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
