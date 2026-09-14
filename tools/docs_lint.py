#!/usr/bin/env python3
"""Validate the tool-neutral deTrouble repository documentation contract."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import unquote


DOC_BUCKETS = (
    "strategy",
    "architecture",
    "decisions",
    "reference",
    "how-to",
    "runbooks",
    "archive",
    "_templates",
)
REQUIRED_ROOT_FILES = ("README.md", "STATUS.md")
INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REFERENCE_TARGET_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S.*)$")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def check_layout(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    docs = root / "docs"

    for name in REQUIRED_ROOT_FILES:
        if not (root / name).is_file():
            errors.append(f"missing required root file: {name}")
    if not docs.is_dir():
        errors.append("missing required directory: docs/")
    else:
        if not (docs / "index.md").is_file():
            errors.append("missing required docs file: docs/index.md")
        for bucket in DOC_BUCKETS:
            if not (docs / bucket).is_dir():
                errors.append(f"missing required docs bucket: docs/{bucket}/")
        allowed = set(DOC_BUCKETS) | {"index.md"}
        for entry in sorted(docs.iterdir(), key=lambda path: path.name):
            if entry.name not in allowed:
                suffix = "/" if entry.is_dir() else ""
                errors.append(
                    f"non-canonical docs entry: docs/{entry.name}{suffix}; "
                    f"allowed: {', '.join(DOC_BUCKETS)} and index.md"
                )

    return errors


def _strip_code(text: str) -> str:
    output: list[str] = []
    fence_marker: str | None = None
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)[0]
            fence_marker = marker if fence_marker is None else None
            output.append("")
            continue
        if fence_marker is not None:
            output.append("")
            continue
        output.append(re.sub(r"`+[^`]*`+", "", line))
    return "\n".join(output)


def _link_destination(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1 : raw.index(">")]
    return raw.split(maxsplit=1)[0] if raw else ""


def _destinations(text: str):
    clean = _strip_code(text)
    for match in INLINE_LINK_RE.finditer(clean):
        yield _link_destination(match.group(1))
    for line in clean.splitlines():
        match = REFERENCE_TARGET_RE.match(line)
        if match:
            yield _link_destination(match.group(1))


def _slug(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[`*_~]", "", text).strip().lower()
    kept = [
        char
        for char in text
        if unicodedata.category(char)[0] in {"L", "M", "N"}
        or char in {" ", "-", "_"}
    ]
    return re.sub(r"\s+", "-", "".join(kept))


def _anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for line in _strip_code(path.read_text(encoding="utf-8")).splitlines():
        match = HEADING_RE.match(line)
        if not match:
            continue
        base = _slug(match.group(2))
        if not base:
            continue
        count = counts.get(base, 0)
        counts[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def _governed_markdown(root: Path) -> list[Path]:
    paths = [root / "README.md", root / "STATUS.md"]
    docs = root / "docs"
    if docs.is_dir():
        paths.extend(
            path
            for path in docs.rglob("*.md")
            if not path.is_relative_to(docs / "archive")
        )
    return sorted({path.resolve() for path in paths if path.is_file()})


def check_links(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    for source in _governed_markdown(root):
        for destination in _destinations(source.read_text(encoding="utf-8")):
            if not destination or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", destination):
                continue
            if destination.startswith("/"):
                errors.append(
                    f"{source.relative_to(root)}: non-portable absolute link: {destination}"
                )
                continue
            decoded = unquote(destination).replace("\\ ", " ")
            target_text, separator, fragment = decoded.partition("#")
            target_text = target_text.split("?", 1)[0]
            target = source if not target_text else (source.parent / target_text)
            target = target.resolve()
            shown = source.relative_to(root)
            if not _is_within(target, root):
                errors.append(f"{shown}: relative link escapes repository: {destination}")
                continue
            if not target.exists():
                errors.append(f"{shown}: broken relative link: {destination}")
                continue
            if separator and fragment and target.is_file() and target.suffix.lower() == ".md":
                anchor = unquote(fragment).strip().lower()
                anchor_cache.setdefault(target, _anchors(target))
                if anchor not in anchor_cache[target]:
                    errors.append(f"{shown}: missing heading anchor: {destination}")
    return errors


def run(root: Path) -> list[str]:
    return check_layout(root) + check_links(root)


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
        print(f"docs-lint: FAIL ({len(errors)} errors)")
        return 1
    print("docs-lint: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
