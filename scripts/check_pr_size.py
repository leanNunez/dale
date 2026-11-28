"""PR size guard: fail when a diff changes more than 400 authored lines.

Counts ``git diff --numstat`` additions + deletions, skipping ``openspec/``, the generated
eval files (``evals/recordings/`` and ``evals/reports/``), ``uv.lock``, the generated contract
files (``contracts/**/*.schema.json``, ``contracts/v1/components.json`` and
``contracts/v1/notice.json``; the authored samples under
``contracts/v1/samples/`` still count) and the page's lockfile and generated types
(``apps/web/package-lock.json`` and ``apps/web/src/contract/generated/``; ``package.json`` still
counts, so a dependency change is always reviewed). The release PR
(``dev`` of this same repository into ``main``) is skipped: it carries slices that were already
reviewed. A fork's ``dev`` is not.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import PurePosixPath

LIMIT = 400
EXCLUDED_PREFIXES = (
    "openspec/",
    "evals/recordings/",
    "evals/reports/",
    "apps/web/src/contract/generated/",
)
EXCLUDED_FILES = (
    "uv.lock",
    "contracts/v1/components.json",
    "contracts/v1/notice.json",
    "apps/web/package-lock.json",
)


def is_generated_schema(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return parts[:1] == ("contracts",) and "samples" not in parts and path.endswith(".schema.json")


def is_excluded(path: str) -> bool:
    return path in EXCLUDED_FILES or path.startswith(EXCLUDED_PREFIXES) or is_generated_schema(path)


def count_changed_lines(numstat: str) -> int:
    """Sum ``--numstat`` lines minus excluded paths; a malformed line raises ``ValueError``."""
    total = 0
    for line in numstat.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            raise ValueError(f"malformed numstat line: {line!r}")
        added, deleted, path = parts
        binary = (added, deleted) == ("-", "-")
        if not binary and not (added.isdigit() and deleted.isdigit()):
            raise ValueError(f"malformed numstat line: {line!r}")
        if binary or is_excluded(path):
            continue
        total += int(added) + int(deleted)
    return total


def is_release_pr(head_ref: str, base_ref: str, head_repo: str, base_repo: str) -> bool:
    """Only ``dev`` of the base repository itself may release into ``main``."""
    return head_ref == "dev" and base_ref == "main" and bool(base_repo) and head_repo == base_repo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="git ref to diff against")
    parser.add_argument("--head", default="HEAD", help="git ref with the changes")
    for name in ("head-branch", "base-branch", "head-repo", "base-repo"):
        parser.add_argument(f"--{name}", default="", help=f"PR {name.replace('-', ' ')}")
    args = parser.parse_args(argv)

    if is_release_pr(args.head_branch, args.base_branch, args.head_repo, args.base_repo):
        print("Release PR (dev -> main): size check skipped.")
        return 0

    diff = subprocess.run(
        ["git", "diff", "--numstat", "--no-renames", f"{args.base}...{args.head}"],
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        print(f"error: git diff failed ({diff.returncode}): {diff.stderr.strip()}", file=sys.stderr)
        return 2
    try:
        total = count_changed_lines(diff.stdout)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"Changed lines (excluding generated and reviewed paths): {total} / {LIMIT}")
    if total > LIMIT:
        print("PR is over the size budget: split it into chained slices.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
