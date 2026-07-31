#!/usr/bin/env python3
# Copyright (c) 2026 Alex313031 and gz83.
"""Merge Thorium-owned translation additions into Chromium XTB bundles."""

import argparse
import csv
from collections.abc import Iterable
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re

TRANSLATION_RE = re.compile(
    r'<translation\b(?=[^>]*\bid="([^"]+)")[^>]*>.*?</translation>',
    re.DOTALL,
)
TRANSLATION_BUNDLE_END = "</translationbundle>"
MARKUP_TAG_RE = re.compile(r"<[^>]+>")
CHROMIUM_LINK_BLOCK_RE = re.compile(
    r'<ph name="BEGIN_LINK_CHROMIUM"\s*/>.*?'
    r'<ph name="END_LINK_CHROMIUM"\s*/>',
    re.DOTALL,
)
WEB_STORE_BRAND_TRANSLATION_IDS = frozenset(
    {
        "1431202594789052745",
        "3776796446459804932",
        "3909353120217047026",
        "73786666777299047",
    }
)
PRODUCT_TEXT_REPLACEMENTS_BEFORE_CHROME = (
    ("Chromebook Recovery Utility", "ThoriumOS Recovery Utility"),
    ("Chromebook Plus", "ThoriumOS Plus device"),
    ("Chromebook experience", "ThoriumOS experience"),
    ("Chromebook community", "ThoriumOS community"),
    ("Chromebook help forum", "ThoriumOS help forum"),
    ("Chromebook questions", "ThoriumOS questions"),
    ("features of Chromebook", "features of ThoriumOS"),
    ("Chromebooks", "ThoriumOS devices"),
    ("Chromebook", "ThoriumOS device"),
    ("Chromium", "Thorium"),
)
PRODUCT_TEXT_REPLACEMENTS_AFTER_CHROME = (
    ("Google Thorium", "Thorium"),
    ("Google recommends Thorium", "Alex313031 recommends Thorium"),
    ("ThoriumOS Flex", "ThoriumOS"),
    ("made possible by Thorium", "made possible by Chromium"),
)


def _apply_product_text_replacements(
    text: str,
    *,
    replace_chrome: bool,
) -> str:
    """Apply product replacements while optionally preserving Chrome names."""
    for old, new in PRODUCT_TEXT_REPLACEMENTS_BEFORE_CHROME:
        text = text.replace(old, new)
    if replace_chrome:
        text = text.replace("Chrome", "Thorium")
    for old, new in PRODUCT_TEXT_REPLACEMENTS_AFTER_CHROME:
        text = text.replace(old, new)
    return text


def apply_ordered_replacements(text: str) -> str:
    """Apply reviewed Thorium replacements in their required order."""
    text = _apply_product_text_replacements(text, replace_chrome=True)
    text = re.sub(r"(?<!Thorium )Experiments", "Thorium Experiments", text)
    text = text.replace(
        "Aw, Snap!", "Aw, #@%!, this tab's process has gone bye bye..."
    )
    text = text.replace("Thorium Web Store", "Chrome Web Store")
    text = text.replace("Thorium web store", "Chrome web store")
    text = text.replace("Thorium Remote Desktop", "Chrome Remote Desktop")
    return text


def apply_replacements_preserving_chrome(text: str) -> str:
    """Apply product replacements while preserving Chrome-owned service names."""
    text = _apply_product_text_replacements(text, replace_chrome=False)
    text = re.sub(r"(?<!Thorium )Experiments", "Thorium Experiments", text)
    text = text.replace(
        "Aw, Snap!", "Aw, #@%!, this tab's process has gone bye bye..."
    )
    text = text.replace("Thorium Remote Desktop", "Chrome Remote Desktop")
    return text


def replace_outside_markup(text: str, *, preserve_chrome: bool = False) -> str:
    """Apply text replacements without changing XML-like tags."""
    replacer = (
        apply_replacements_preserving_chrome
        if preserve_chrome
        else apply_ordered_replacements
    )
    parts: list[str] = []
    cursor = 0
    for match in MARKUP_TAG_RE.finditer(text):
        if match.start() > cursor:
            parts.append(replacer(text[cursor : match.start()]))
        parts.append(match.group(0))
        cursor = match.end()
    if cursor < len(text):
        parts.append(replacer(text[cursor:]))
    return "".join(parts)


def replace_outside_markup_preserving_chromium_link(
    text: str,
    *,
    preserve_chrome: bool = False,
) -> str:
    """Apply replacements while preserving Chromium project link text."""
    parts: list[str] = []
    cursor = 0
    for match in CHROMIUM_LINK_BLOCK_RE.finditer(text):
        if match.start() > cursor:
            parts.append(
                replace_outside_markup(
                    text[cursor : match.start()],
                    preserve_chrome=preserve_chrome,
                )
            )
        parts.append(match.group(0))
        cursor = match.end()
    if cursor < len(text):
        parts.append(
            replace_outside_markup(text[cursor:], preserve_chrome=preserve_chrome)
        )
    return "".join(parts)


def normalize_xtb_translation_block(block: str, translation_id: str) -> str:
    """Normalize reviewed Thorium XTB additions before insertion."""
    block = replace_outside_markup_preserving_chromium_link(
        block,
        preserve_chrome=translation_id in WEB_STORE_BRAND_TRANSLATION_IDS,
    )
    for old, new in (
        ("ThoriumOS Flex", "ThoriumOS"),
        ("ThoriumOS\u00a0Flex", "ThoriumOS"),
        ("Thorium OS Flex", "ThoriumOS"),
        ("Thorium\u00a0OS Flex", "ThoriumOS"),
        ("Thorium OS\u00a0Flex", "ThoriumOS"),
        ("Thorium\u00a0OS\u00a0Flex", "ThoriumOS"),
        ("ThoriumOs Flex", "ThoriumOS"),
        ("ThoriumOs\u00a0Flex", "ThoriumOS"),
        ("Thorium Flex", "ThoriumOS"),
        ("Thorium\u00a0Flex", "ThoriumOS"),
    ):
        block = block.replace(old, new)
    return "\n".join(line.rstrip() for line in block.splitlines())


@dataclass(frozen=True)
class XtbAddition:
    translation_id: str
    block: str


@dataclass(frozen=True)
class XtbMergeResult:
    target_path: str
    addition_count: int
    inserted_count: int
    skipped_count: int
    replaced_count: int
    merged_text: str


def readable_directory(path: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        raise argparse.ArgumentTypeError(f"not a directory: {path}")
    return resolved


def readable_file(path: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise argparse.ArgumentTypeError(f"not a readable file: {path}")
    return resolved


def load_inventory(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as input_file:
        reader = csv.DictReader(input_file, delimiter="\t")
        required = {"target_path", "translation_id", "translation_block"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                f"inventory is missing columns: {', '.join(sorted(missing))}"
            )
        return list(reader)


def group_inventory(
    rows: list[dict[str, str]],
) -> dict[str, list[XtbAddition]]:
    grouped: dict[str, list[XtbAddition]] = defaultdict(list)
    seen_keys: set[tuple[str, str]] = set()
    for row in rows:
        target_path = row.get("target_path", "").replace("\\", "/").strip("/")
        target_parts = PurePosixPath(target_path).parts
        translation_id = row.get("translation_id", "").strip()
        block = normalize_xtb_translation_block(
            row.get("translation_block", ""),
            translation_id,
        )
        if (
            not target_path.endswith(".xtb")
            or not target_parts
            or ".." in target_parts
            or ":" in target_parts[0]
        ):
            raise ValueError(f"invalid inventory target: {target_path}")
        match = TRANSLATION_RE.fullmatch(block)
        if not match or match.group(1) != translation_id:
            raise ValueError(
                f"invalid translation block for {target_path}:{translation_id}"
            )
        key = (target_path, translation_id)
        if key in seen_keys:
            raise ValueError(
                f"duplicate inventory translation ID {translation_id} "
                f"for {target_path}"
            )
        seen_keys.add(key)
        grouped[target_path].append(
            XtbAddition(
                translation_id=translation_id,
                block=block,
            )
        )
    if not grouped:
        raise ValueError("inventory contains no XTB translations")
    return dict(grouped)


def merge_additions_into_text(
    target_text: str,
    additions: list[XtbAddition],
    target_path: str,
) -> tuple[str, int, int, int]:
    """Insert missing additions and refresh reviewed existing additions."""
    existing: dict[str, str] = {}
    for match in TRANSLATION_RE.finditer(target_text):
        translation_id = match.group(1)
        if translation_id in existing:
            raise ValueError(
                f"duplicate translation ID {translation_id} in {target_path}"
            )
        existing[translation_id] = match.group(0)

    pending: list[XtbAddition] = []
    skipped_count = 0
    replaced_count = 0
    for addition in additions:
        existing_block = existing.get(addition.translation_id)
        if existing_block is None:
            pending.append(addition)
            continue
        if existing_block != addition.block:
            target_text = target_text.replace(existing_block, addition.block, 1)
            replaced_count += 1
            continue
        skipped_count += 1

    if pending:
        closing_index = target_text.rfind(TRANSLATION_BUNDLE_END)
        if closing_index < 0:
            raise ValueError(f"missing {TRANSLATION_BUNDLE_END} in {target_path}")

        prefix = target_text[:closing_index]
        suffix = target_text[closing_index:]
        separator = "" if not prefix or prefix.endswith("\n") else "\n"
        addition_text = "\n".join(addition.block for addition in pending)
        target_text = f"{prefix}{separator}{addition_text}\n{suffix}"

    return (
        target_text,
        len(pending),
        skipped_count,
        replaced_count,
    )


def build_merge_results(
    chromium_root: Path,
    additions_by_target: Iterable[tuple[str, list[XtbAddition]]],
) -> list[XtbMergeResult]:
    """Prepare merged contents without writing Chromium files."""
    results: list[XtbMergeResult] = []
    for target_path, additions in additions_by_target:
        target_file = chromium_root / target_path
        if not target_file.is_file():
            raise FileNotFoundError(f"XTB target is missing: {target_path}")
        target_text = target_file.read_text(encoding="utf-8", errors="strict")
        (
            merged_text,
            inserted_count,
            skipped_count,
            replaced_count,
        ) = merge_additions_into_text(
            target_text,
            additions,
            target_path,
        )
        results.append(
            XtbMergeResult(
                target_path=target_path,
                addition_count=len(additions),
                inserted_count=inserted_count,
                skipped_count=skipped_count,
                replaced_count=replaced_count,
                merged_text=merged_text,
            )
        )
    return results


def write_merge_results(
    chromium_root: Path,
    results: list[XtbMergeResult],
) -> None:
    """Write prepared XTB contents using UTF-8 without newline conversion."""
    for result in results:
        if result.inserted_count == 0 and result.replaced_count == 0:
            continue
        (chromium_root / result.target_path).write_bytes(
            result.merged_text.encode("utf-8")
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge Thorium translation additions into Chromium XTB files."
    )
    parser.add_argument(
        "chromium_root",
        type=readable_directory,
        help="Chromium source root containing the target XTB files.",
    )
    parser.add_argument(
        "--inventory",
        type=readable_file,
        help="Normalized TSV inventory; defaults to the reviewed inventory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report additions without writing target files.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    inventory = args.inventory or (
        Path(__file__).resolve().parent / "config/xtb_additions.tsv"
    )
    inventory_groups = group_inventory(load_inventory(inventory))
    additions_by_target = [
        (target_path, additions)
        for target_path, additions in sorted(inventory_groups.items())
    ]
    results = build_merge_results(args.chromium_root, additions_by_target)
    total_additions = sum(result.addition_count for result in results)
    inserted_count = sum(result.inserted_count for result in results)
    skipped_count = sum(result.skipped_count for result in results)
    replaced_count = sum(result.replaced_count for result in results)
    touched_count = sum(
        result.inserted_count > 0 or result.replaced_count > 0
        for result in results
    )
    if not args.dry_run:
        write_merge_results(args.chromium_root, results)
    mode = "validated" if args.dry_run else "merged"
    print(
        f"{mode} {total_additions} Thorium translations across "
        f"{len(results)} XTB files: {inserted_count} inserted, "
        f"{replaced_count} refreshed, {skipped_count} already present, "
        f"{touched_count} files changed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
