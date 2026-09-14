#!/usr/bin/env python3
"""Export en/zh_CN text from the authoritative GD file to ParaTranz JSON.

Generated files:
- out/paratranz_source.json: full current key + original snapshot, for
  ParaTranz Create/Update File.
- out/paratranz_initial_translation.json: key + original + translation, for
  first-time Import Translation.  On update runs this file is left untouched
  unless --emit-initial is given; changed/added keys are then emitted blank.
- out/paratranz_changes.json: local report with added/changed/removed plus
  untranslated/stale keys.
- metadata.json: local source hash and per-key state.
- out/archive/<old_source_sha256>/: previous exports and metadata, written
  automatically before the baseline advances.

``--check`` computes and prints the same summary without writing any file.
"""

from __future__ import annotations

import argparse
import json
import shutil
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
    resolve_default_gd,
    save_metadata,
    text_sha256,
)

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_GD = resolve_default_gd(TOOLS_DIR)
DEFAULT_OUT_DIR = TOOLS_DIR / "out"
DEFAULT_METADATA = TOOLS_DIR / "metadata.json"


def _utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


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
    """Build fresh metadata while carrying placeholder flags forward."""
    entries: dict[str, MetadataEntry] = {}
    zh_entries = parsed.zh.entries

    for key, en_entry in parsed.en.entries.items():
        zh_entry = zh_entries.get(key)
        entries[key] = MetadataEntry(
            en_text_sha256=text_sha256(en_entry.text),
            en_version_hash=en_entry.version_hash,
            zh_version_hash=zh_entry.version_hash if zh_entry is not None else None,
            # version_hash == 0 is the placeholder marker used by the game.
            zh_placeholder=bool(zh_entry is not None and zh_entry.version_hash == 0),
        )
    return Metadata(
        schema_version=1,
        source_sha256=source_sha256,
        generated_at=_utc_now(),
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
    zh_entries = parsed.zh.entries

    if previous is None:
        added = list(en_order)
        changed: list[str] = []
        removed: list[str] = []
    else:
        old_entries = previous.entries
        old_keys = set(old_entries)
        new_keys = set(new_metadata.entries)
        added = [key for key in en_order if key not in old_keys]
        changed = [
            key
            for key in en_order
            if key in old_entries
            and old_entries[key].en_text_sha256
            != new_metadata.entries[key].en_text_sha256
        ]
        removed = sorted(old_keys - new_keys)

    added_details = [
        {
            "key": key,
            "new_en_text_sha256": new_metadata.entries[key].en_text_sha256,
            "new_en_version_hash": new_metadata.entries[key].en_version_hash,
        }
        for key in added
    ]
    changed_details = [
        {
            "key": key,
            "old_en_text_sha256": previous.entries[key].en_text_sha256,
            "new_en_text_sha256": new_metadata.entries[key].en_text_sha256,
            "old_en_version_hash": previous.entries[key].en_version_hash,
            "new_en_version_hash": new_metadata.entries[key].en_version_hash,
        }
        for key in changed
    ]
    removed_details = [
        {
            "key": key,
            "en_text_sha256": previous.entries[key].en_text_sha256,
            "en_version_hash": previous.entries[key].en_version_hash,
            "zh_version_hash": previous.entries[key].zh_version_hash,
        }
        for key in removed
    ]
    untranslated = [key for key in en_order if key not in zh_entries]
    stale = [
        key
        for key in en_order
        if key in zh_entries
        and zh_entries[key].version_hash != parsed.en.entries[key].version_hash
    ]

    return {
        "first_run": previous is None,
        "generated_at": _utc_now(),
        "source_sha256_before": previous.source_sha256 if previous is not None else None,
        "source_sha256_after": source_sha256,
        # Kept for compatibility with the earlier report schema.
        "source_sha256": source_sha256,
        "en_count": len(en_order),
        "zh_count": len(zh_entries),
        "added": added,
        "changed": changed,
        "removed": removed,
        "untranslated": untranslated,
        "stale": stale,
        "added_details": added_details,
        "changed_details": changed_details,
        "removed_details": removed_details,
    }


def _archive_previous_outputs(
    out_dir: Path,
    metadata_path: Path,
    previous: Metadata,
) -> Path:
    """Copy the previous metadata/exports into an archive keyed by source hash."""
    archive_dir = out_dir / "archive" / previous.source_sha256
    archive_dir.mkdir(parents=True, exist_ok=True)
    candidates = (
        metadata_path,
        out_dir / "paratranz_source.json",
        out_dir / "paratranz_initial_translation.json",
        out_dir / "paratranz_changes.json",
        out_dir / "paratranz_export.json",
    )
    for source in candidates:
        if not source.is_file():
            continue
        destination = archive_dir / source.name
        if not destination.exists():
            shutil.copy2(source, destination)
    return archive_dir


def generate(
    gd_path: Path,
    out_dir: Path,
    metadata_path: Path,
    write: bool = True,
    emit_initial: bool = False,
) -> dict[str, Any]:
    """Generate all ParaTranz JSON files and metadata for one GD file.

    When ``write`` is False no file is written, making this safe to use as a
    dry run.  ``emit_initial`` is only needed when an updated initial
    translation snapshot is explicitly wanted.
    """
    gd_text = read_utf8(gd_path, "GD file")
    parsed = parse_translations_file(gd_text)
    source_sha256 = file_sha256(gd_path)
    previous = load_metadata(metadata_path)
    metadata = _build_metadata(parsed, source_sha256, previous)
    changes = _changes_payload(parsed, previous, metadata, source_sha256)

    source_items: list[dict[str, str]] = []
    for key in parsed.en_key_order:
        source_items.append(_source_item(key, parsed.en.entries[key].text))

    first_run = previous is None
    emit_initial_file = first_run or emit_initial
    translation_items: list[dict[str, str]] = []
    if emit_initial_file:
        # On update runs, do not re-import old translations for changed/added
        # keys.  They must be translated/reviewed again.
        blank_keys = (
            set(changes["added"]) | set(changes["changed"])
            if not first_run
            else set()
        )
        for key in parsed.en_key_order:
            en_entry = parsed.en.entries[key]
            zh_entry = parsed.zh.entries.get(key)
            usable_zh = (
                zh_entry is not None
                and zh_entry.version_hash != 0
                and not metadata.entries[key].zh_placeholder
                and key not in blank_keys
            )
            translation_items.append(
                _translation_item(
                    key,
                    en_entry.text,
                    zh_entry.text if usable_zh and zh_entry is not None else "",
                )
            )

    wrote: list[str] = []
    archive_dir: Path | None = None
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        if previous is not None:
            archive_dir = _archive_previous_outputs(out_dir, metadata_path, previous)

        source_path = out_dir / "paratranz_source.json"
        _write_json(source_path, source_items)
        wrote.append(str(source_path))

        if emit_initial_file:
            initial_path = out_dir / "paratranz_initial_translation.json"
            _write_json(initial_path, translation_items)
            wrote.append(str(initial_path))

        changes_path = out_dir / "paratranz_changes.json"
        _write_json(changes_path, changes)
        wrote.append(str(changes_path))

        save_metadata(metadata_path, metadata)
        wrote.append(str(metadata_path))

    return {
        "gd_path": str(gd_path),
        "en_count": len(parsed.en.entries),
        "zh_count": len(parsed.zh.entries),
        "placeholder_count": sum(
            1 for entry in metadata.entries.values() if entry.zh_placeholder
        ),
        "changes": changes,
        "initial_count": len(translation_items),
        "emit_initial": emit_initial_file,
        "archive_dir": str(archive_dir) if archive_dir is not None else None,
        "wrote": wrote,
        "check_only": not write,
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
    print(
        "changes: "
        f"added={len(changes['added'])} "
        f"changed={len(changes['changed'])} "
        f"removed={len(changes['removed'])} "
        f"untranslated={len(changes['untranslated'])} "
        f"stale={len(changes['stale'])}"
    )
    if changes["first_run"]:
        print("  first run: all current en keys recorded")
    else:
        for label, prefix, keys in (
            ("added", "+", changes["added"]),
            ("changed English text", "~", changes["changed"]),
            ("removed", "-", changes["removed"]),
            ("untranslated (no zh_CN entry)", "?", changes["untranslated"]),
            (
                "stale (zh version_hash != en version_hash)",
                "!",
                changes["stale"],
            ),
        ):
            if not keys:
                continue
            print(f"  {label}:")
            for key in keys[:20]:
                print(f"    {prefix} {key}")
            if len(keys) > 20:
                print(f"    ... and {len(keys) - 20} more")

    for path in summary["wrote"]:
        print(f"wrote: {path}")
    if summary["archive_dir"]:
        print(f"archived previous outputs: {summary['archive_dir']}")
    if summary["check_only"]:
        print("check-only: no files were written")
    elif summary["emit_initial"]:
        print("initial translation snapshot emitted")


def build_parser() -> argparse.ArgumentParser:
    """Build the command line argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gd", type=Path, default=DEFAULT_GD)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compute and print everything, but write no files",
    )
    parser.add_argument(
        "--emit-initial",
        action="store_true",
        help=(
            "also write an initial translation snapshot on update runs; "
            "changed/added entries are emitted with an empty translation"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    try:
        summary = generate(
            args.gd,
            args.out_dir,
            args.metadata,
            write=not args.check,
            emit_initial=args.emit_initial,
        )
    except (GDParseError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
