#!/usr/bin/env python3
"""Validate the portable repository safety baseline."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


OS_ARTIFACT_PATTERNS = (
    "knowledge/episodes/",
    "knowledge/inbox/KNOW-",
    "knowledge/inbox/EPISODE-",
    "knowledge/items/KNOW-",
    "knowledge/receipts/CLOSEOUT-",
    "knowledge/delta-receipts/",
    "planning/COMPONENT.json",
    "planning/OGSM.md",
    "planning/OKRS.md",
    "planning/BACKLOG.md",
    "planning/SPRINT",
)


def _tracked_files(root: Path) -> tuple[list[Path], list[str]]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "git ls-files failed"
        return [], [f"cannot inspect tracked files: {detail}"]
    return [Path(value) for value in result.stdout.split("\0") if value], []


def _unsafe_tracked_path(path: Path) -> str | None:
    relative = path.as_posix()
    name = path.name
    if name == ".DS_Store":
        return "tracked macOS metadata"
    if "__pycache__" in path.parts or path.suffix == ".pyc":
        return "tracked Python runtime cache"
    if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
        return "tracked local environment file; commit an explicit *.example file instead"
    if any(relative == pattern or relative.startswith(pattern) for pattern in OS_ARTIFACT_PATTERNS):
        return "tracked deTrouble OS Knowledge or Planning artifact; keep it in the OS-managed plane"
    return None


def run(root: Path) -> list[str]:
    root = root.resolve()
    tracked, errors = _tracked_files(root)
    for path in tracked:
        reason = _unsafe_tracked_path(path)
        if reason:
            errors.append(f"{path.as_posix()}: {reason}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to this script's repository)",
    )
    args = parser.parse_args(argv)
    errors = run(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"repo-lint: FAIL ({len(errors)} errors)")
        return 1
    print("repo-lint: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
