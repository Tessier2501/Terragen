"""Small GDScript translation fixtures for unit tests."""

from __future__ import annotations


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _block(entries: list[tuple[str, str, int]]) -> str:
    lines: list[str] = []
    for index, (key, text, version_hash) in enumerate(entries):
        lines.append(f'\t\t"{_escape(key)}": {{')
        lines.append(f'\t\t\t"string": "{_escape(text)}",')
        lines.append(f'\t\t\t"version_hash": {version_hash}')
        suffix = "," if index < len(entries) - 1 else ""
        lines.append(f"\t\t}}{suffix}")
    return "\n".join(lines)


def make_gd(
    en: list[tuple[str, str, int]],
    zh: list[tuple[str, str, int]],
    master_locale: str = "en",
) -> str:
    """Build a minimal but valid REPLACE_TRANSLATIONS.gd body."""
    return (
        'const TRANSLATIONS = {\n'
        f'\t"master_locale": "{master_locale}",\n'
        '\t"en": {\n'
        f"{_block(en)}\n"
        "\t},\n"
        '\t"zh_CN": {\n'
        f"{_block(zh)}\n"
        "\t}\n"
        "}\n"
    )
