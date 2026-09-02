#!/usr/bin/env python3
"""Merge reviewed ParaTranz zh_CN translations back into the GD file.

Input JSON must be the ParaTranz "Download Raw Data" array:
[{"key": "...", "original": "...", "translation": "...", "stage": 5}]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from gd_format import (
    GDParseError,
    LocalizedText,
    Metadata,
    MetadataEntry,
    ParsedGD,
    file_sha256,
    load_metadata,
    parse_translations_file,
    read_utf8,
    render_locale_block,
    save_metadata,
    text_sha256,
)

TOOLS_DIR = Path(__file__).resolve().parent
# Layout: repo_root/Script/para-translation, so the root is two levels up.
REPO_ROOT = TOOLS_DIR.parent.parent
DEFAULT_GD = (
    REPO_ROOT
    / "IndustriesOfEnceladusRewriteCN"
    / "HEVLIB_EQUIPMENT_DRIVER_TAGS"
    / "REPLACE_TRANSLATIONS.gd"
)
DEFAULT_EXPORT = TOOLS_DIR / "out" / "paratranz_export.json"
DEFAULT_METADATA = TOOLS_DIR / "metadata.json"


@dataclass(frozen=True)
class ExportItem:
    """One item from the ParaTranz raw data file."""

    key: str
    original: str
    translation: str
    stage: int


@dataclass(frozen=True)
class MergePlan:
    """A validated, ready-to-apply merge plan."""

    entries: list[LocalizedText]
    changes: list[dict[str, Any]]
    placeholder_keys: list[str]
    deleted_keys: list[str]
    reviewed_count: int


def load_export_items(path: Path) -> list[ExportItem]:
    """Load and validate the ParaTranz raw data JSON file."""
    raw = read_utf8(path, "ParaTranz export file")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ParaTranz export file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("ParaTranz export JSON must be an array")

    items: list[ExportItem] = []
    seen_keys: set[str] = set()
    for index, raw_item in enumerate(data):
        if not isinstance(raw_item, dict):
            raise ValueError(f"export item {index} must be a JSON object")
        key = raw_item.get("key")
        original = raw_item.get("original")
        translation = raw_item.get("translation")
        stage = raw_item.get("stage")
        if not isinstance(key, str) or not key:
            raise ValueError(f"export item {index} has an empty or non-string 'key'")
        if key in seen_keys:
            raise ValueError(f"export file contains duplicate key {key!r}")
        seen_keys.add(key)
        if not isinstance(original, str):
            raise ValueError(f"export item {key!r} has a non-string 'original'")
        if not isinstance(translation, str):
            raise ValueError(f"export item {key!r} has a non-string 'translation'")
        if not isinstance(stage, int) or isinstance(stage, bool):
            raise ValueError(f"export item {key!r} has a non-integer 'stage'")
        items.append(
            ExportItem(key=key, original=original, translation=translation, stage=stage)
        )
    return items


def _validate_key_set(parsed: ParsedGD, export_items: list[ExportItem]) -> dict[str, ExportItem]:
    """Return an export map after checking that its key set equals en."""
    en_keys = set(parsed.en.entries)
    export_map = {item.key: item for item in export_items}
    missing = en_keys - set(export_map)
    extra = set(export_map) - en_keys
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing keys: {sorted(missing)!r}")
        if extra:
            details.append(f"unexpected keys: {sorted(extra)!r}")
        raise ValueError(
            "ParaTranz export key set does not match current en key set; "
            + "; ".join(details)
        )
    return export_map


def _validate_reviewed_entries(
    parsed: ParsedGD,
    export_map: dict[str, ExportItem],
    review_stage: int,
) -> None:
    """Reject reviewed entries whose translation or original text is invalid."""
    errors: list[str] = []
    for key in parsed.en_key_order:
        item = export_map[key]
        if item.stage < review_stage:
            continue
        en_entry = parsed.en.entries[key]
        if not item.translation.strip():
            errors.append(f"{key!r}: stage is {item.stage} but translation is empty")
        if item.original != en_entry.text:
            errors.append(
                f"{key!r}: ParaTranz original does not match current en text; "
                f"re-upload paratranz_source.json first"
            )
    if errors:
        raise ValueError(
            "reviewed entries failed validation:\n- " + "\n- ".join(errors)
        )


def plan_merge(
    parsed: ParsedGD,
    export_items: list[ExportItem],
    review_stage: int = 5,
) -> MergePlan:
    """Validate and plan a zh_CN merge without writing files."""
    export_map = _validate_key_set(parsed, export_items)
    _validate_reviewed_entries(parsed, export_map, review_stage)

    zh_entries = parsed.zh.entries
    entries: list[LocalizedText] = []
    changes: list[dict[str, Any]] = []
    placeholder_keys: list[str] = []
    reviewed_count = 0

    for key in parsed.en_key_order:
        en_entry = parsed.en.entries[key]
        item = export_map[key]
        current = zh_entries.get(key)
        is_reviewed = item.stage >= review_stage

        if is_reviewed:
            reviewed_count += 1
            new_text = item.translation
            new_hash = en_entry.version_hash
        elif current is None:
            new_text = en_entry.text
            new_hash = 0
        else:
            new_text = current.text
            new_hash = current.version_hash

        if new_text == en_entry.text and new_hash == 0:
            placeholder_keys.append(key)

        if current is None:
            changes.append(
                {
                    "key": key,
                    "action": "insert",
                    "old_text": None,
                    "new_text": new_text,
                    "old_hash": None,
                    "new_hash": new_hash,
                    "reviewed": is_reviewed,
                }
            )
        else:
            text_changed = new_text != current.text
            hash_changed = new_hash != current.version_hash
            if text_changed or hash_changed:
                changes.append(
                    {
                        "key": key,
                        "action": "update",
                        "old_text": current.text,
                        "new_text": new_text,
                        "old_hash": current.version_hash,
                        "new_hash": new_hash,
                        "reviewed": is_reviewed,
                    }
                )

        entries.append(LocalizedText(key=key, text=new_text, version_hash=new_hash))

    deleted_keys = [key for key in zh_entries if key not in parsed.en.entries]
    return MergePlan(
        entries=entries,
        changes=changes,
        placeholder_keys=placeholder_keys,
        deleted_keys=deleted_keys,
        reviewed_count=reviewed_count,
    )


def render_merged_text(parsed: ParsedGD, plan: MergePlan) -> str:
    """Return the full GD text with only the zh_CN block replaced."""
    block = render_locale_block("zh_CN", plan.entries)
    return parsed.text[: parsed.zh.start] + block + parsed.text[parsed.zh.end :]


def _updated_metadata(
    metadata: Metadata,
    parsed: ParsedGD,
    plan: MergePlan,
    new_source_sha256: str,
) -> Metadata:
    """Build updated metadata after a successful GD write."""
    final_zh = {entry.key: entry for entry in plan.entries}
    entries: dict[str, MetadataEntry] = {}
    for key in parsed.en_key_order:
        previous = metadata.entries[key]
        zh_entry = final_zh[key]
        entries[key] = MetadataEntry(
            en_text_sha256=previous.en_text_sha256,
            en_version_hash=previous.en_version_hash,
            zh_version_hash=zh_entry.version_hash,
            zh_placeholder=(
                zh_entry.text == parsed.en.entries[key].text
                and zh_entry.version_hash == 0
            ),
        )
    return Metadata(
        schema_version=metadata.schema_version,
        source_sha256=new_source_sha256,
        generated_at=datetime.now(timezone.utc).isoformat(),
        entries=entries,
    )


def _validate_metadata_matches(parsed: ParsedGD, metadata: Metadata, gd_path: Path) -> None:
    """Ensure metadata was generated from the current GD and key set."""
    current_sha = file_sha256(gd_path)
    if metadata.source_sha256 != current_sha:
        raise ValueError(
            f"metadata source hash does not match current GD file; "
            f"re-run gd_to_json.py first"
        )
    if set(metadata.entries) != set(parsed.en.entries):
        raise ValueError(
            "metadata key set does not match current en key set; "
            "re-run gd_to_json.py first"
        )


def write_merge(
    gd_path: Path,
    metadata_path: Path,
    plan: MergePlan,
    parsed: ParsedGD,
    metadata: Metadata,
) -> bool:
    """Atomically write the merged GD file and update metadata.

    Returns True when the GD file was changed and written.
    """
    if not plan.changes and not plan.deleted_keys:
        return False

    from gd_format import atomic_write_text

    new_text = render_merged_text(parsed, plan)
    try:
        reparsed = parse_translations_file(new_text)
    except GDParseError as exc:
        raise GDParseError(f"refusing to write generated GD text: {exc}") from exc
    if reparsed.zh.start >= reparsed.zh.end:
        raise GDParseError("generated zh_CN block is empty")

    atomic_write_text(gd_path, new_text)

    try:
        updated = _updated_metadata(
            metadata,
            parsed,
            plan,
            text_sha256(new_text),
        )
        save_metadata(metadata_path, updated)
    except OSError as exc:
        raise OSError(
            f"GD file was written, but metadata update failed: {exc}; "
            f"re-run gd_to_json.py to regenerate metadata"
        ) from exc
    return True


def _format_text(value: Any, limit: int = 60) -> str:
    """Format a text value for the change report."""
    if value is None:
        return "<missing>"
    text = str(value).replace("\n", "\\n")
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def print_plan(plan: MergePlan) -> None:
    """Print a human-readable merge report."""
    print(f"reviewed entries (stage >= configured threshold): {plan.reviewed_count}")
    print(f"entries in zh_CN after merge: {len(plan.entries)}")
    print(f"changes to write: {len(plan.changes)}")
    print(f"placeholders (en text + hash 0): {len(plan.placeholder_keys)}")
    print(f"deleted zh_CN-only keys: {len(plan.deleted_keys)}")

    for change in plan.changes:
        print(
            f"  {change['action']:6} {change['key']}: "
            f"{_format_text(change['old_text'])} -> {_format_text(change['new_text'])}; "
            f"hash {change['old_hash']} -> {change['new_hash']} "
            f"(reviewed={change['reviewed']})"
        )
    for key in plan.deleted_keys:
        print(f"  delete {key}")


def build_parser() -> argparse.ArgumentParser:
    """Build the command line argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gd", type=Path, default=DEFAULT_GD)
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument(
        "--review-stage",
        type=int,
        default=5,
        help="minimum ParaTranz stage treated as reviewed (default: 5)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the merged GD file; default is check-only",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    if args.review_stage < 0:
        print("error: --review-stage must be >= 0", file=sys.stderr)
        return 2
    try:
        gd_text = read_utf8(args.gd, "GD file")
        parsed = parse_translations_file(gd_text)
        metadata = load_metadata(args.metadata)
        if metadata is None:
            print(
                f"error: metadata file {args.metadata} does not exist; "
                f"run gd_to_json.py first",
                file=sys.stderr,
            )
            return 1
        _validate_metadata_matches(parsed, metadata, args.gd)
        export_items = load_export_items(args.export)
        plan = plan_merge(parsed, export_items, review_stage=args.review_stage)
    except (GDParseError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_plan(plan)
    if not args.write:
        if plan.changes or plan.deleted_keys:
            print("check-only: no files were written")
        else:
            print("check-only: no changes needed")
        return 0

    try:
        wrote = write_merge(args.gd, args.metadata, plan, parsed, metadata)
    except (GDParseError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if wrote:
        print("wrote merged GD file and updated metadata")
    else:
        print("no changes needed; no files were written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
