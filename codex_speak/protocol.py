from __future__ import annotations

from dataclasses import dataclass
import json
import re
import unicodedata
from typing import Final


IMPORTANT_STATUSES: Final[frozenset[str]] = frozenset(
    {"completed", "blocked", "action_required"}
)
ALL_STATUSES: Final[frozenset[str]] = IMPORTANT_STATUSES | {"silent"}
HARD_LIMIT: Final[int] = 280

_V1_MARKER_RE = re.compile(
    r"(?:\A|\n)<!-- codex-speak:v1 (?P<payload>\{[^\r\n]*\}) -->\s*\Z"
)
_V2_MARKER_RE = re.compile(
    r"(?:\A|\n)\[codex-speak-v2\]: <codex-speak:v2#(?P<payload>\{[^\r\n]*\})>\s*\Z"
)
_MARKER_SENTINELS: Final[tuple[str, ...]] = ("codex-speak:v", "[codex-speak-v")
_WHITESPACE_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://[^\s,，。！？!?]+")
_ABSOLUTE_PATH_RE = re.compile(
    r"(?<!\w)/(?:[^/,，\s。；！？!?()\[\]{}]+/)*[^/,，\s。；！？!?()\[\]{}]+"
)
_MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]\r\n]*)\]\([^\)\r\n]*\)")
_MARKDOWN_LINE_PREFIX_RE = re.compile(
    r"(?m)^[ \t]*(?:>[ \t]*(?:(?:[-+*]|\d+[.)])[ \t]+)?|(?:[-+*]|\d+[.)])[ \t]+)"
)
_STRIKETHROUGH_RE = re.compile(r"~~")
_MARKDOWN_RE = re.compile(r"[`*_#]+")
_SENTENCE_ENDINGS: Final[tuple[str, ...]] = ("。", "！", "？", ".", "!", "?")


@dataclass(frozen=True, slots=True)
class ParsedResponse:
    status: str
    summary_text: str
    visible_body: str


def _sanitize_speech_text(value: str) -> str:
    text = "".join(
        "\n" if char in {"\r", "\n"} else " " if char.isspace() else ""
        if unicodedata.category(char) in {"Cc", "Cf"}
        else char
        for char in value
    )
    text = _MARKDOWN_LINE_PREFIX_RE.sub("", text)
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = _URL_RE.sub("链接", text)
    text = _ABSOLUTE_PATH_RE.sub("相关文件", text)
    text = _STRIKETHROUGH_RE.sub("", text)
    text = _MARKDOWN_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) <= HARD_LIMIT:
        return text

    candidate = text[:HARD_LIMIT]
    boundary = max(candidate.rfind(mark) for mark in _SENTENCE_ENDINGS)
    if boundary >= 0:
        return candidate[: boundary + 1].rstrip()
    return candidate.rstrip()


def _parse_exact_payload(payload_text: str) -> tuple[str, str] | None:
    try:
        payload = json.loads(payload_text)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(payload, dict) or set(payload) != {"status", "speech_text"}:
        return None

    status = payload.get("status")
    raw_speech = payload.get("speech_text")
    if (
        not isinstance(status, str)
        or status not in ALL_STATUSES
        or not isinstance(raw_speech, str)
    ):
        return None

    speech_text = _sanitize_speech_text(raw_speech)
    if status == "silent":
        if speech_text:
            return None
        return "silent", ""

    if not speech_text:
        return None
    return status, speech_text


def extract_response(message: str | None) -> ParsedResponse | None:
    if not isinstance(message, str):
        return None

    matches = [
        *(('v1', match) for match in _V1_MARKER_RE.finditer(message)),
        *(('v2', match) for match in _V2_MARKER_RE.finditer(message)),
    ]
    if len(matches) != 1:
        return None
    version, match = matches[0]
    payload_text = match.group("payload")
    if version == "v2" and any(character in payload_text for character in "<>"):
        return None
    parsed = _parse_exact_payload(payload_text)
    if parsed is None:
        return None
    prefix = message[: match.start()]
    if any(sentinel in prefix for sentinel in _MARKER_SENTINELS):
        return None
    status, summary = parsed
    return ParsedResponse(status, summary, prefix.rstrip())
