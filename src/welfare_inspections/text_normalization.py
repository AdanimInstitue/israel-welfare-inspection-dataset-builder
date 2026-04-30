"""Deterministic text normalization helpers for extracted Hebrew text."""

from __future__ import annotations

import re
import unicodedata

HEBREW_GERESH = "\u05f3"
HEBREW_GERSHAYIM = "\u05f4"

_HEBREW_LETTER_RE = r"[\u05d0-\u05ea]"
_CONTROL_TRANSLATION = {
    codepoint: None
    for codepoint in range(0x20)
    if chr(codepoint) not in {"\n", "\t"}
}
_CONTROL_TRANSLATION.update(
    {
        0x7F: None,
        0x200B: None,
        0x200C: None,
        0x200D: None,
        0x200E: None,
        0x200F: None,
        0x202A: None,
        0x202B: None,
        0x202C: None,
        0x202D: None,
        0x202E: None,
        0x2060: None,
        0x2066: None,
        0x2067: None,
        0x2068: None,
        0x2069: None,
        0xFEFF: None,
        0x00A0: " ",
        0x2007: " ",
        0x202F: " ",
    }
)
_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u0060": "'",
        "\u00b4": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2033": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2026": "...",
    }
)
_HEBREW_APOSTROPHE_RE = re.compile(f"({_HEBREW_LETTER_RE})'")
_HEBREW_QUOTE_RE = re.compile(f"({_HEBREW_LETTER_RE})\"(?={_HEBREW_LETTER_RE})")
_SPACES_RE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_SPACE_BEFORE_NEWLINE_RE = re.compile(r" *\n *")


def normalize_extracted_text(text: str) -> str:
    """Normalize embedded PDF text without applying visual bidi transforms."""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = remove_zero_width_and_controls(normalized)
    normalized = normalize_punctuation_variants(normalized)
    normalized = normalize_hebrew_geresh_gershayim(normalized)
    return cleanup_whitespace(normalized)


def remove_zero_width_and_controls(text: str) -> str:
    """Remove zero-width/control characters while preserving line boundaries."""
    return text.translate(_CONTROL_TRANSLATION)


def normalize_punctuation_variants(text: str) -> str:
    """Normalize common punctuation variants emitted by PDF extractors."""
    return text.translate(_PUNCTUATION_TRANSLATION)


def normalize_hebrew_geresh_gershayim(text: str) -> str:
    """Canonicalize Hebrew geresh/gershayim marks in Hebrew abbreviations."""
    text = _HEBREW_APOSTROPHE_RE.sub(rf"\1{HEBREW_GERESH}", text)
    return _HEBREW_QUOTE_RE.sub(rf"\1{HEBREW_GERSHAYIM}", text)


def cleanup_whitespace(text: str) -> str:
    """Collapse repeated horizontal whitespace and trim blank lines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACES_RE.sub(" ", text)
    text = _SPACE_BEFORE_NEWLINE_RE.sub("\n", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()
