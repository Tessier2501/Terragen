"""Shared GDScript translation dictionary parsing and rendering.

The module intentionally parses only the dictionary literal assigned to
``const TRANSLATIONS``.  It is not a general GDScript parser.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence, cast

MARKER = "const TRANSLATIONS = {"
METADATA_SCHEMA_VERSION = 1
_NUMBER_RE = re.compile(r"-?\d+")
_ESCAPE_DECODE = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    '"': '"',
    "\\": "\\",
}


class GDParseError(ValueError):
    """Raised when the GDScript translation dictionary cannot be parsed safely."""


class MetadataError(ValueError):
    """Raised when metadata.json is missing required data or is malformed."""


TokenKind = Literal["string", "integer", "{", "}", ":", ","]


@dataclass(frozen=True)
class Token:
    """A lexical token inside the TRANSLATIONS dictionary."""

    kind: TokenKind
    value: Any
    start: int
    end: int


@dataclass(frozen=True)
class Node:
    """A parsed value node with source span information."""

    kind: Literal["string", "integer", "dict"]
    start: int
    end: int
    value: Any
    items: tuple[tuple[str, "Node"], ...] = ()
    key_tokens: dict[str, Token] = field(default_factory=dict)


@dataclass(frozen=True)
class Entry:
    """One translation entry inside a locale block."""

    key: str
    text: str
    version_hash: int
    string_node: Node
    hash_node: Node


@dataclass(frozen=True)
class LocaleBlock:
    """A locale block and the character span it occupies in the source text."""

    name: str
    start: int
    end: int
    entries: dict[str, Entry]


@dataclass(frozen=True)
class ParsedGD:
    """Parsed representation of a REPLACE_TRANSLATIONS.gd file."""

    text: str
    master_locale: str
    locales: dict[str, LocaleBlock]

    @property
    def en(self) -> LocaleBlock:
        """Return the English locale block."""
        return self.locales["en"]

    @property
    def zh(self) -> LocaleBlock:
        """Return the Simplified Chinese locale block."""
        return self.locales["zh_CN"]

    @property
    def en_key_order(self) -> list[str]:
        """Return English keys in file order."""
        return list(self.en.entries)


@dataclass(frozen=True)
class LocalizedText:
    """An entry ready to be rendered into a locale block."""

    key: str
    text: str
    version_hash: int


@dataclass(frozen=True)
class MetadataEntry:
    """Per-key local metadata."""

    en_text_sha256: str
    en_version_hash: int
    zh_version_hash: int | None
    zh_placeholder: bool


@dataclass
class Metadata:
    """Local metadata file content."""

    schema_version: int
    source_sha256: str
    generated_at: str
    entries: dict[str, MetadataEntry]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "schema_version": self.schema_version,
            "source_sha256": self.source_sha256,
            "generated_at": self.generated_at,
            "entries": {
                key: {
                    "en_text_sha256": entry.en_text_sha256,
                    "en_version_hash": entry.en_version_hash,
                    "zh_version_hash": entry.zh_version_hash,
                    "zh_placeholder": entry.zh_placeholder,
                }
                for key, entry in self.entries.items()
            },
        }


def decode_gd_string(escaped: str) -> str:
    """Decode GDScript string escape sequences into human-readable text.

    Only the escape sequences used by the target file are accepted.  Unknown
    escapes raise ``GDParseError`` instead of being silently passed through.
    """
    if not isinstance(escaped, str):
        raise TypeError("escaped must be str")
    result: list[str] = []
    index = 0
    while index < len(escaped):
        char = escaped[index]
        if char != "\\":
            result.append(char)
            index += 1
            continue
        index += 1
        if index >= len(escaped):
            raise GDParseError("dangling backslash at end of GDScript string")
        escape_char = escaped[index]
        try:
            result.append(_ESCAPE_DECODE[escape_char])
        except KeyError as exc:
            raise GDParseError(
                f"unsupported GDScript escape sequence: \\{escape_char}"
            ) from exc
        index += 1
    return "".join(result)


def encode_gd_string(text: str) -> str:
    """Encode plain text as a GDScript double-quoted string body."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    result: list[str] = []
    for char in text:
        if char == "\\":
            result.append("\\\\")
        elif char == '"':
            result.append('\\"')
        elif char == "\n":
            result.append("\\n")
        elif char == "\r":
            result.append("\\r")
        elif char == "\t":
            result.append("\\t")
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            raise GDParseError(
                f"refusing to encode unsupported control character U+{ord(char):04X}"
            )
        else:
            result.append(char)
    return "".join(result)


def _tokenize(text: str, start: int) -> list[Token]:
    """Tokenize the dictionary literal beginning at ``start``."""
    tokens: list[Token] = []
    index = start
    length = len(text)
    while index < length:
        char = text[index]
        if char in " \t\r\n":
            index += 1
            continue
        if char == "#":
            newline = text.find("\n", index)
            index = length if newline == -1 else newline + 1
            continue
        if char == '"':
            quote_start = index
            index += 1
            escaped_parts: list[str] = []
            while index < length:
                current = text[index]
                if current == "\\":
                    index += 1
                    if index >= length:
                        raise GDParseError(
                            f"dangling backslash in string at offset {index - 1}"
                        )
                    escape_char = text[index]
                    try:
                        escaped_parts.append(_ESCAPE_DECODE[escape_char])
                    except KeyError as exc:
                        raise GDParseError(
                            f"unsupported GDScript escape sequence \\{escape_char} "
                            f"at offset {index - 1}"
                        ) from exc
                    index += 1
                    continue
                if current == '"':
                    index += 1
                    tokens.append(
                        Token(
                            kind="string",
                            value="".join(escaped_parts),
                            start=quote_start,
                            end=index,
                        )
                    )
                    break
                escaped_parts.append(current)
                index += 1
            else:
                raise GDParseError(
                    f"unterminated GDScript string at offset {quote_start}"
                )
            continue
        if char in "{}:,":
            tokens.append(
                Token(kind=cast(TokenKind, char), value=char, start=index, end=index + 1)
            )
            index += 1
            continue
        number_match = _NUMBER_RE.match(text, index)
        if number_match is not None:
            tokens.append(
                Token(
                    kind="integer",
                    value=int(number_match.group(0)),
                    start=index,
                    end=number_match.end(),
                )
            )
            index = number_match.end()
            continue
        raise GDParseError(
            f"unexpected character {char!r} at offset {index}"
        )
    return tokens


def _parse_node(tokens: list[Token], position: int) -> tuple[Node, int]:
    """Parse one value node starting at ``position``."""
    token = tokens[position]
    if token.kind == "string":
        return (
            Node(
                kind="string",
                start=token.start,
                end=token.end,
                value=token.value,
            ),
            position + 1,
        )
    if token.kind == "integer":
        return (
            Node(
                kind="integer",
                start=token.start,
                end=token.end,
                value=token.value,
            ),
            position + 1,
        )
    if token.kind != "{":
        raise GDParseError(
            f"expected string, integer, or '{{' at offset {token.start}, "
            f"got {token.kind!r}"
        )

    dict_start = token.start
    position += 1
    items: list[tuple[str, Node]] = []
    key_tokens: dict[str, Token] = {}
    seen_keys: set[str] = set()

    if tokens[position].kind == "}":
        close = tokens[position]
        return (
            Node(
                kind="dict",
                start=dict_start,
                end=close.end,
                value=None,
                items=tuple(items),
                key_tokens=key_tokens,
            ),
            position + 1,
        )

    while True:
        key_token = tokens[position]
        if key_token.kind != "string":
            raise GDParseError(
                f"expected string dictionary key at offset {key_token.start}"
            )
        key = key_token.value
        if key in seen_keys:
            raise GDParseError(f"duplicate dictionary key {key!r} at offset {key_token.start}")
        seen_keys.add(key)
        key_tokens[key] = key_token
        position += 1

        colon = tokens[position]
        if colon.kind != ":":
            raise GDParseError(
                f"expected ':' after key {key!r} at offset {colon.start}"
            )
        position += 1

        child, position = _parse_node(tokens, position)
        items.append((key, child))

        separator = tokens[position]
        if separator.kind == ",":
            position += 1
            if tokens[position].kind == "}":
                continue
            continue
        if separator.kind == "}":
            break
        raise GDParseError(
            f"expected ',' or '}}' after value for key {key!r} at offset {separator.start}"
        )

    close = tokens[position]
    return (
        Node(
            kind="dict",
            start=dict_start,
            end=close.end,
            value=None,
            items=tuple(items),
            key_tokens=key_tokens,
        ),
        position + 1,
    )


def _parse_locale_entries(locale_name: str, locale_node: Node) -> dict[str, Entry]:
    """Validate and extract entries from one locale dictionary node."""
    if locale_node.kind != "dict":
        raise GDParseError(f"locale {locale_name!r} must be a dictionary")
    entries: dict[str, Entry] = {}
    for key, entry_node in locale_node.items:
        if entry_node.kind != "dict":
            raise GDParseError(f"entry {key!r} in locale {locale_name!r} must be a dictionary")
        fields = {field_name: child for field_name, child in entry_node.items}
        unknown_fields = set(fields) - {"string", "version_hash"}
        if unknown_fields:
            raise GDParseError(
                f"entry {key!r} in locale {locale_name!r} has unsupported "
                f"field(s): {sorted(unknown_fields)!r}"
            )
        if "string" not in fields or "version_hash" not in fields:
            raise GDParseError(
                f"entry {key!r} in locale {locale_name!r} must contain "
                f"'string' and 'version_hash'"
            )
        string_node = fields["string"]
        hash_node = fields["version_hash"]
        if string_node.kind != "string":
            raise GDParseError(
                f"'string' for entry {key!r} in locale {locale_name!r} must be a string"
            )
        if hash_node.kind != "integer":
            raise GDParseError(
                f"'version_hash' for entry {key!r} in locale {locale_name!r} "
                f"must be an integer"
            )
        entries[key] = Entry(
            key=key,
            text=string_node.value,
            version_hash=hash_node.value,
            string_node=string_node,
            hash_node=hash_node,
        )
    return entries


def parse_translations_file(text: str) -> ParsedGD:
    """Parse a REPLACE_TRANSLATIONS.gd file body and return its locales."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    if "\r\n" in text:
        raise GDParseError("CRLF line endings are not supported; expected LF")
    marker_position = text.find(MARKER)
    if marker_position == -1:
        raise GDParseError(f"translation dictionary marker {MARKER!r} not found")
    brace_position = text.find("{", marker_position)
    if brace_position == -1:
        raise GDParseError("translation dictionary opening brace not found")

    tokens = _tokenize(text, brace_position)
    if not tokens:
        raise GDParseError("empty TRANSLATIONS dictionary")
    root_node, position = _parse_node(tokens, 0)
    if position != len(tokens):
        trailing = tokens[position]
        raise GDParseError(
            f"unexpected token {trailing.kind!r} after TRANSLATIONS dictionary "
            f"at offset {trailing.start}"
        )
    if root_node.kind != "dict":
        raise GDParseError("TRANSLATIONS must be a dictionary")

    root_fields = {name: child for name, child in root_node.items}
    if "master_locale" not in root_fields:
        raise GDParseError("TRANSLATIONS is missing 'master_locale'")
    master_node = root_fields["master_locale"]
    if master_node.kind != "string":
        raise GDParseError("'master_locale' must be a string")
    master_locale = master_node.value

    locales: dict[str, LocaleBlock] = {}
    for locale_name, locale_node in root_node.items:
        if locale_name == "master_locale":
            continue
        if locale_node.kind != "dict":
            raise GDParseError(f"locale {locale_name!r} must be a dictionary")
        key_token = root_node.key_tokens[locale_name]
        locales[locale_name] = LocaleBlock(
            name=locale_name,
            start=key_token.start,
            end=locale_node.end,
            entries=_parse_locale_entries(locale_name, locale_node),
        )

    if "en" not in locales:
        raise GDParseError("TRANSLATIONS is missing required locale 'en'")
    if "zh_CN" not in locales:
        raise GDParseError("TRANSLATIONS is missing required locale 'zh_CN'")
    return ParsedGD(text=text, master_locale=master_locale, locales=locales)


def render_locale_block(locale_name: str, entries: Sequence[LocalizedText]) -> str:
    """Render one locale block exactly in the target file's indentation style."""
    if not locale_name:
        raise ValueError("locale_name must not be empty")
    lines: list[str] = [f'"{locale_name}": {{']
    for index, entry in enumerate(entries):
        lines.append(f'\t\t"{encode_gd_string(entry.key)}": {{')
        lines.append(f'\t\t\t"string": "{encode_gd_string(entry.text)}",')
        lines.append(f'\t\t\t"version_hash": {entry.version_hash}')
        if index < len(entries) - 1:
            lines.append("\t\t},")
        else:
            lines.append("\t\t}")
    lines.append("\t}")
    return "\n".join(lines)


def file_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(text: str) -> str:
    """Return the SHA-256 hex digest of UTF-8 encoded text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_utf8(path: Path, description: str) -> str:
    """Read a UTF-8 file with explicit boundary validation."""
    if not isinstance(path, Path):
        path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise OSError(f"cannot read {description} {path}: {exc}") from exc
    if data.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{description} {path} contains a UTF-8 BOM; expected no BOM")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{description} {path} is not valid UTF-8: {exc}") from exc
    return text


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically, preserving the existing mode."""
    if not isinstance(path, Path):
        path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode: int | None = None
    if path.exists():
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError as exc:
            raise OSError(f"cannot stat {path}: {exc}") from exc

    temporary_path: str | None = None
    try:
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=str(path.parent),
        )
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as exc:
        raise OSError(f"cannot write {path}: {exc}") from exc
    finally:
        if temporary_path is not None and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def load_metadata(path: Path) -> Metadata | None:
    """Load metadata.json, returning None only when the file does not exist."""
    if not path.exists():
        return None
    raw = read_utf8(path, "metadata file")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MetadataError(f"metadata file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MetadataError(f"metadata file {path} must contain a JSON object")
    if data.get("schema_version") != METADATA_SCHEMA_VERSION:
        raise MetadataError(
            f"metadata file {path} has unsupported schema_version "
            f"{data.get('schema_version')!r}; expected {METADATA_SCHEMA_VERSION}"
        )
    source_sha256 = data.get("source_sha256")
    generated_at = data.get("generated_at")
    raw_entries = data.get("entries")
    if not isinstance(source_sha256, str) or not source_sha256:
        raise MetadataError(f"metadata file {path} is missing 'source_sha256'")
    if not isinstance(generated_at, str) or not generated_at:
        raise MetadataError(f"metadata file {path} is missing 'generated_at'")
    if not isinstance(raw_entries, dict):
        raise MetadataError(f"metadata file {path} is missing 'entries' object")

    entries: dict[str, MetadataEntry] = {}
    for key, raw_entry in raw_entries.items():
        if not isinstance(key, str) or not key:
            raise MetadataError(f"metadata file {path} has an empty or non-string key")
        if not isinstance(raw_entry, dict):
            raise MetadataError(f"metadata entry {key!r} in {path} must be an object")
        en_sha = raw_entry.get("en_text_sha256")
        en_hash = raw_entry.get("en_version_hash")
        zh_hash = raw_entry.get("zh_version_hash")
        placeholder = raw_entry.get("zh_placeholder")
        if not isinstance(en_sha, str) or len(en_sha) != 64:
            raise MetadataError(
                f"metadata entry {key!r} has invalid 'en_text_sha256'"
            )
        if not isinstance(en_hash, int):
            raise MetadataError(
                f"metadata entry {key!r} has invalid 'en_version_hash'"
            )
        if zh_hash is not None and not isinstance(zh_hash, int):
            raise MetadataError(
                f"metadata entry {key!r} has invalid 'zh_version_hash'"
            )
        if not isinstance(placeholder, bool):
            raise MetadataError(
                f"metadata entry {key!r} has invalid 'zh_placeholder'"
            )
        entries[key] = MetadataEntry(
            en_text_sha256=en_sha,
            en_version_hash=en_hash,
            zh_version_hash=zh_hash,
            zh_placeholder=placeholder,
        )
    return Metadata(
        schema_version=METADATA_SCHEMA_VERSION,
        source_sha256=source_sha256,
        generated_at=generated_at,
        entries=entries,
    )


def save_metadata(path: Path, metadata: Metadata) -> None:
    """Atomically write metadata.json."""
    payload = json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, payload)
