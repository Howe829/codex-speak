from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Final, Literal

from .protocol import ParsedResponse


SpeechMode = Literal["summary", "full"]
MAX_SEGMENT_CHARS: Final[int] = 600

_FENCE_OPEN_RE = re.compile(
    r"(?m)^[ \t]*(?P<fence>`{3,}|~{3,})[^\r\n]*(?:\r?\n|\Z)"
)
_IMAGE_RE = re.compile(r"!\[([^\]\r\n]*)\]\([^\)\r\n]*\)")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]\r\n]*)\]\([^\)\r\n]*\)")
_INLINE_CODE_RE = re.compile(
    r"(?<!`)(?P<ticks>`+)(?!`)(?P<content>[^\r\n]*?)(?<!`)(?P=ticks)(?!`)"
)
_URL_RE = re.compile(r"https?://[^\s,，。！？!?]+")
_PATH_RE = re.compile(
    r"(?<![\w])(?:~/|/)(?:[^/,，\s。；！？!?()\[\]{}]+/)*"
    r"[^/,，\s。；！？!?()\[\]{}]+"
)
_TABLE_SEPARATOR_RE = re.compile(
    r"(?m)^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*$"
)
_MARKDOWN_LINE_PREFIX_RE = re.compile(
    r"(?m)^[ \t]*(?:#{1,6}[ \t]+|>[ \t]*|(?:[-+*]|\d+[.)])[ \t]+)"
)
_EMPHASIS_RE = re.compile(r"(?:~~|[*_]+)")
_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_ENDINGS: Final[frozenset[str]] = frozenset("。！？.!?")
_DOUBLE_QUOTE_TRANSLATION: Final[dict[int, None]] = str.maketrans(
    "", "", '\"“”„‟＂'
)


@dataclass(frozen=True, slots=True)
class SpeechPayload:
    mode: str
    status: str
    segments: tuple[str, ...]


def _remove_unicode_controls(value: str) -> str:
    return "".join(
        "\n"
        if char in {"\r", "\n"}
        else " "
        if char.isspace()
        else ""
        if unicodedata.category(char) in {"Cc", "Cf"}
        else char
        for char in value
    )


def _replace_fenced_code(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    while opening := _FENCE_OPEN_RE.search(value, cursor):
        fence = opening.group("fence")
        closing_re = re.compile(
            rf"(?m)^[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*(?=\r?$)"
        )
        closing = closing_re.search(value, opening.end())
        if closing is None:
            break
        parts.extend((value[cursor : opening.start()], "代码块"))
        cursor = closing.end()
    parts.append(value[cursor:])
    return "".join(parts)


def _replace_inline_code(match: re.Match[str]) -> str:
    content = _inline_label(match)
    return content if content is not None else "代码"


def _inline_label(match: re.Match[str]) -> str | None:
    ticks = match.group("ticks")
    content = match.group("content").strip()
    is_label = (
        len(ticks) == 1
        and 1 <= len(content) <= 32
        and all(
            char.isalnum() or char.isspace() or char == "-"
            for char in content
        )
    )
    return content if is_label else None


def _protect_inline_code(value: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    guard_char = "\ue000"
    guard = guard_char * (value.count(guard_char) + 1)

    protected: list[tuple[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        label = _inline_label(match)
        if label is None:
            return "代码"
        token = f"{guard}{len(protected)}{guard}"
        protected.append((token, label))
        return token

    return _INLINE_CODE_RE.sub(replace, value), tuple(protected)


def normalize_full_text(value: str) -> str:
    text = _replace_fenced_code(value)
    text, protected_labels = _protect_inline_code(text)
    text = _remove_unicode_controls(text)
    text = _replace_fenced_code(text)
    text = text.translate(_DOUBLE_QUOTE_TRANSLATION)
    text = _IMAGE_RE.sub(lambda match: f"{match.group(1)} 图片".strip(), text)
    text = _MARKDOWN_LINK_RE.sub(r"\1 链接", text)
    text = _URL_RE.sub("链接", text)
    text = _PATH_RE.sub("相关文件", text)
    text = _TABLE_SEPARATOR_RE.sub("", text)
    text = _MARKDOWN_LINE_PREFIX_RE.sub("", text)
    text = text.replace("|", " ")
    text = _EMPHASIS_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    for token, label in protected_labels:
        text = text.replace(token, label)
    return text


def _preferred_boundary(value: str, limit: int) -> int:
    paragraph = value.rfind("\n\n", 0, limit)
    if paragraph >= 0:
        return paragraph + 2

    for index in range(limit - 1, -1, -1):
        if value[index] in _SENTENCE_ENDINGS:
            return index + 1

    whitespace = 0
    for match in re.finditer(r"\s+", value[:limit]):
        whitespace = match.end()
    return whitespace or limit


def segment_text(
    value: str, limit: int = MAX_SEGMENT_CHARS
) -> tuple[str, ...]:
    if limit < 1:
        raise ValueError("limit must be positive")
    if not value:
        return ()

    segments: list[str] = []
    remaining = value
    while len(remaining) > limit:
        boundary = _preferred_boundary(remaining, limit)
        segments.append(remaining[:boundary])
        remaining = remaining[boundary:]
    if remaining:
        segments.append(remaining)
    return tuple(segments)


def render_speech(
    response: ParsedResponse, mode: SpeechMode
) -> SpeechPayload | None:
    if mode == "summary":
        if response.status == "silent":
            return None
        text = response.summary_text
    elif mode == "full":
        text = normalize_full_text(response.visible_body)
    else:
        raise ValueError(f"unsupported speech mode: {mode}")

    segments = segment_text(text)
    if not segments:
        return None
    return SpeechPayload(mode, response.status, segments)
