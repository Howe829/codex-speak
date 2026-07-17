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
LEAD_HARD_LIMIT: Final[int] = 120
TASK_TITLE_PLACEHOLDER: Final[str] = "{{task_title}}"
_TASK_TITLE_SENTINEL: Final[str] = "\ue000CodexSpeakTaskTitle\ue001"

_V1_MARKER_RE = re.compile(
    r"(?:\A|\n)<!-- codex-speak:v1 (?P<payload>\{[^\r\n]*\}) -->\s*\Z"
)
_V2_MARKER_RE = re.compile(
    r"(?:\A|\n)\[codex-speak-v2\]: <codex-speak:v2#(?P<payload>\{[^\r\n]*\})>\s*\Z"
)
_V3_MARKER_RE = re.compile(
    r"(?:\A|\n)\[codex-speak-v3\]: <codex-speak:v3#(?P<payload>\{[^\r\n]*\})>\s*\Z"
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
    speech_lead_template: str = ""


def _sanitize_speech_text(value: str, *, hard_limit: int = HARD_LIMIT) -> str:
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
    if len(text) <= hard_limit:
        return text

    candidate = text[:hard_limit]
    boundary = max(candidate.rfind(mark) for mark in _SENTENCE_ENDINGS)
    if boundary >= 0:
        return candidate[: boundary + 1].rstrip()
    return candidate.rstrip()


def _sanitize_speech_lead(value: str) -> str | None:
    if (
        value.count(TASK_TITLE_PLACEHOLDER) != 1
        or _TASK_TITLE_SENTINEL in value
    ):
        return None
    protected = value.replace(TASK_TITLE_PLACEHOLDER, _TASK_TITLE_SENTINEL)
    sanitized = _sanitize_speech_text(
        protected,
        hard_limit=max(
            len(protected), LEAD_HARD_LIMIT + len(_TASK_TITLE_SENTINEL)
        ),
    ).replace(_TASK_TITLE_SENTINEL, TASK_TITLE_PLACEHOLDER)
    if (
        len(sanitized) > LEAD_HARD_LIMIT
        or sanitized.count(TASK_TITLE_PLACEHOLDER) != 1
    ):
        return None
    return sanitized


def _parse_exact_payload(
    payload_text: str, *, version: str
) -> tuple[str, str, str] | None:
    try:
        payload = json.loads(payload_text)
    except (json.JSONDecodeError, TypeError):
        return None

    expected_keys = (
        {"status", "speech_lead", "speech_text"}
        if version == "v3"
        else {"status", "speech_text"}
    )
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        return None

    status = payload.get("status")
    raw_speech = payload.get("speech_text")
    raw_lead = payload.get("speech_lead", "")
    if (
        not isinstance(status, str)
        or status not in ALL_STATUSES
        or not isinstance(raw_speech, str)
        or not isinstance(raw_lead, str)
    ):
        return None

    speech_text = _sanitize_speech_text(raw_speech)
    if status == "silent":
        if raw_speech or raw_lead:
            return None
        return "silent", "", ""

    if not speech_text:
        return None
    if version == "v3":
        speech_lead = _sanitize_speech_lead(raw_lead)
        if speech_lead is None:
            return None
    else:
        speech_lead = ""
    return status, speech_text, speech_lead


def extract_response(message: str | None) -> ParsedResponse | None:
    if not isinstance(message, str):
        return None

    matches = [
        *(('v1', match) for match in _V1_MARKER_RE.finditer(message)),
        *(('v2', match) for match in _V2_MARKER_RE.finditer(message)),
        *(('v3', match) for match in _V3_MARKER_RE.finditer(message)),
    ]
    if len(matches) != 1:
        return None
    version, match = matches[0]
    payload_text = match.group("payload")
    if version in {"v2", "v3"} and any(
        character in payload_text for character in "<>"
    ):
        return None
    parsed = _parse_exact_payload(payload_text, version=version)
    if parsed is None:
        return None
    prefix = message[: match.start()]
    if any(sentinel in prefix for sentinel in _MARKER_SENTINELS):
        return None
    status, summary, speech_lead = parsed
    return ParsedResponse(status, summary, prefix.rstrip(), speech_lead)
