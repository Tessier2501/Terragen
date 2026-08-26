#!/usr/bin/env python3
"""Export en/zh_CN text from the authoritative GD file to ParaTranz JSON.

Generated files:
- out/paratranz_source.json: key + original only, for Create/Update File.
- out/paratranz_initial_translation.json: key + original + translation,
  for Import Translation.
- out/paratranz_changes.json: key changes relative to the previous run.
- metadata.json: local source hash and per-key state.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from gd_format import (
    GDParseError,
    Metadata,
    MetadataEntry,
    ParsedGD,
    file_sha256,
    load_metadata,
    parse_translations_file,
    read_utf8,
    save_metadata,
    text_sha256,
)

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
DEFAULT_GD = (
    REPO_ROOT
    / "IndustriesOfEnceladusRewriteCN"
    / "HEVLIB_EQUIPMENT_DRIVER_TAGS"
    / "REPLACE_TRANSLATIONS.gd"
)
DEFAULT_OUT_DIR = TOOLS_DIR / "out"
DEFAULT_METADATA = TOOLS_DIR / "metadata.json"


def _write_json(path: Path, payload: Any) -> None:
    """Write a JSON file with the project's canonical formatting."""
    from gd_format import atomic_write_text

    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, encoded)


def _source_item(key: str, original: str) -> dict[str, str]:
    """Return a ParaTranz source-only JSON item."""
    return {
        "key": key,
        "original": original,
        "translation": "",
        "context": "",
    }


def _translation_item(key: str, original: str, translation: str) -> dict[str, str]:
    """Return a ParaTranz JSON item carrying an initial translation."""
    return {
        "key": key,
        "original": original,
        "translation": translation,
        "context": "",
    }


def _build_metadata(
    parsed: ParsedGD,
    source_sha256: str,
    previous: Metadata | None,
) -> Metadata:
    """Build fresh metadata while carrying valid placeholder flags forward."""
    previous_entries = previous.entries if previous is not None else {}
    entries: dict[str, MetadataEntry] = {}
    zh_entries = parsed.zh.entries

    for key, en_entry in parsed.en.entries.items():
        previous_entry = previous_entries.get(key)
        zh_entry = zh_entries.get(key)
        placeholder = bool(
            previous_entry is not None
            and previous_entry.zh_placeholder
            and zh_entry is not None
            and zh_entry.version_hash == 0
        )
        entries[key] = MetadataEntry(
            en_text_sha256=text_sha256(en_entry.text),
            en_version_hash=en_entry.version_hash,
            zh_version_hash=zh_entry.version_hash if zh_entry is not None else None,
            zh_placeholder=placeholder,
        )
    return Metadata(
        schema_version=1,
        source_sha256=source_sha256,
        generated_at=datetime.now(timezone.utc).isoformat(),
        entries=entries,
    )


def _changes_payload(
    parsed: ParsedGD,
    previous: Metadata | None,
    new_metadata: Metadata,
    source_sha256: str,
) -> dict[str, Any]:
    """Compare old and new English text hashes and return a change report."""
    en_order = parsed.en_key_order
    if previous is None:
        return {
            "first_run": True,
            "source_sha256": source_sha256,
            "added": list(en_order),
            "changed": [],
            "removed": [],
        }

    old_entries = previous.entries
    old_keys = set(old_entries)
    new_keys = set(new_metadata.entries)
    added = [key for key in en_order if key not in old_keys]
    removed = [key for key in old_keys - new_keys if key in old_entries]
    changed = [
        key
        for key in en_order
        if key in old_entries
        and old_entries[key].en_text_sha256
        != new_metadata.entries[key].en_text_sha256
    ]
    return {
        "first_run": False,
        "source_sha256": source_sha256,
        "added": added,
        "changed": changed,
        "removed": removed,
    }


def generate(
    gd_path: Path,
    out_dir: Path,
    metadata_path: Path,
) -> dict[str, Any]:
    """Generate all ParaTranz JSON files and metadata for one GD file."""
    gd_text = read_utf8(gd_path, "GD file")
    parsed = parse_translations_file(gd_text)
    source_sha256 = file_sha256(gd_path)
    previous = load_metadata(metadata_path)
    metadata = _build_metadata(parsed, source_sha256, previous)

    source_items: list[dict[str, str]] = []
    translation_items: list[dict[str, str]] = []
    for key in parsed.en_key_order:
        en_entry = parsed.en.entries[key]
        source_items.append(_source_item(key, en_entry.text))

        zh_entry = parsed.zh.entries.get(key)
        is_placeholder = metadata.entries[key].zh_placeholder
        if zh_entry is not None and not is_placeholder:
            translation_items.append(
                _translation_item(key, en_entry.text, zh_entry.text)
            )
        else:
            translation_items.append(_translation_item(key, en_entry.text, ""))

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "paratranz_source.json", source_items)
    _write_json(out_dir / "paratranz_initial_translation.json", translation_items)
    changes = _changes_payload(parsed, previous, metadata, source_sha256)
    _write_json(out_dir / "paratranz_changes.json", changes)
    save_metadata(metadata_path, metadata)

    return {
        "gd_path": str(gd_path),
        "en_count": len(parsed.en.entries),
        "zh_count": len(parsed.zh.entries),
        "placeholder_count": sum(
            1 for entry in metadata.entries.values() if entry.zh_placeholder
        ),
        "changes": changes,
        "out_dir": str(out_dir),
        "metadata_path": str(metadata_path),
    }


def _print_summary(summary: dict[str, Any]) -> None:
    """Print a concise summary of the generated files."""
    changes = summary["changes"]
    print(f"GD file: {summary['gd_path']}")
    print(f"en entries: {summary['en_count']}")
    print(f"zh_CN entries: {summary['zh_count']}")
    print(f"placeholders: {summary['placeholder_count']}")
    print(f"changes: added={len(changes['added'])} "
          f"changed={len(changes['changed'])} "
          f"removed={len(changes['removed'])}")
    if changes["first_run"]:
        print("  first run: all current en keys recorded")
    else:
        for label, prefix, keys in (
            ("added", "+", changes["added"]),
            ("changed English text", "~", changes["changed"]),
            ("removed", "-", changes["removed"]),
        ):
            if not keys:
                continue
            print(f"  {label}:")
            for key in keys[:20]:
                print(f"    {prefix} {key}")
            if len(keys) > 20:
                print(f"    ... and {len(keys) - 20} more")
    print(f"wrote: {summary['out_dir']}/paratranz_source.json")
    print(f"wrote: {summary['out_dir']}/paratranz_initial_translation.json")
    print(f"wrote: {summary['out_dir']}/paratranz_changes.json")
    print(f"wrote: {summary['metadata_path']}")


def build_parser() -> argparse.ArgumentParser:
    """Build the command line argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gd", type=Path, default=DEFAULT_GD)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    try:
        summary = generate(args.gd, args.out_dir, args.metadata)
    except (GDParseError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
