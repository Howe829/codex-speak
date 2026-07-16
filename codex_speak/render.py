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


@dataclass(frozen=True, slots=True)
class _OrdinaryFragment:
    value: str


@dataclass(frozen=True, slots=True)
class _LabelFragment:
    value: str


@dataclass(frozen=True, slots=True)
class _CodeFragment:
    pass


_TextFragment = _OrdinaryFragment | _LabelFragment | _CodeFragment


@dataclass(frozen=True, slots=True)
class _MarkdownContainer:
    kind: Literal["image", "link"]
    start: int
    end: int
    visible_text: str


def _normalize_unicode_char(char: str) -> str:
    return (
        "\n"
        if char in {"\r", "\n"}
        else " "
        if char.isspace()
        else ""
        if unicodedata.category(char) in {"Cc", "Cf"}
        else char
    )


def _remove_unicode_controls(value: str) -> str:
    return "".join(_normalize_unicode_char(char) for char in value)


def _fenced_code_ranges(value: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    while opening := _FENCE_OPEN_RE.search(value, cursor):
        fence = opening.group("fence")
        closing_re = re.compile(
            rf"(?m)^[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*(?=\r?$)"
        )
        closing = closing_re.search(value, opening.end())
        if closing is None:
            break
        ranges.append((opening.start(), closing.end()))
        cursor = closing.end()
    return tuple(ranges)


def _replace_ranges(
    value: str, ranges: tuple[tuple[int, int], ...]
) -> str:
    parts: list[str] = []
    cursor = 0
    for start, end in ranges:
        parts.extend((value[cursor:start], "代码块"))
        cursor = end
    parts.append(value[cursor:])
    return "".join(parts)


def _replace_fenced_code(value: str) -> str:
    return _replace_ranges(value, _fenced_code_ranges(value))


def _replace_fenced_code_before_fragmenting(value: str) -> str:
    normalized_chars: list[str] = []
    boundaries = [0]
    for index, char in enumerate(value):
        normalized = _normalize_unicode_char(char)
        if normalized:
            normalized_chars.append(normalized)
            boundaries.append(index + 1)

    normalized_value = "".join(normalized_chars)
    normalized_ranges = _fenced_code_ranges(normalized_value)
    original_ranges = tuple(
        (boundaries[start], boundaries[end])
        for start, end in normalized_ranges
    )
    return _replace_ranges(value, original_ranges)


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


def _append_fragment(
    fragments: list[_TextFragment], fragment: _TextFragment
) -> None:
    if isinstance(fragment, _OrdinaryFragment) and not fragment.value:
        return
    if (
        isinstance(fragment, _OrdinaryFragment)
        and fragments
        and isinstance(fragments[-1], _OrdinaryFragment)
    ):
        previous = fragments[-1]
        assert isinstance(previous, _OrdinaryFragment)
        fragments[-1] = _OrdinaryFragment(previous.value + fragment.value)
        return
    fragments.append(fragment)


def _find_closing_delimiter(
    value: str, opening: int, opening_char: str, closing_char: str
) -> int | None:
    depth = 0
    for index in range(opening, len(value)):
        char = value[index]
        if char == opening_char:
            depth += 1
        elif char == closing_char:
            depth -= 1
            if depth == 0:
                return index
    return None


def _find_markdown_container(
    value: str, cursor: int
) -> _MarkdownContainer | None:
    search_from = cursor
    while (opening := value.find("[", search_from)) >= 0:
        is_image = opening > cursor and value[opening - 1] == "!"
        start = opening - 1 if is_image else opening
        closing = _find_closing_delimiter(value, opening, "[", "]")
        if closing is None or closing + 1 >= len(value):
            search_from = opening + 1
            continue
        destination_opening = closing + 1
        if value[destination_opening] != "(":
            search_from = opening + 1
            continue
        destination_closing = _find_closing_delimiter(
            value, destination_opening, "(", ")"
        )
        if destination_closing is None:
            search_from = opening + 1
            continue
        return _MarkdownContainer(
            "image" if is_image else "link",
            start,
            destination_closing + 1,
            value[opening + 1 : closing],
        )
    return None


def _parse_text_fragments(value: str) -> tuple[_TextFragment, ...]:
    fragments: list[_TextFragment] = []
    cursor = 0
    while cursor < len(value):
        container = _find_markdown_container(value, cursor)
        inline = _INLINE_CODE_RE.search(value, cursor)
        if container is None and inline is None:
            _append_fragment(fragments, _OrdinaryFragment(value[cursor:]))
            break

        container_is_next = container is not None and (
            inline is None or container.start < inline.start()
        )
        match_start = container.start if container_is_next else inline.start()
        _append_fragment(
            fragments, _OrdinaryFragment(value[cursor:match_start])
        )

        if not container_is_next:
            assert inline is not None
            label = _inline_label(inline)
            _append_fragment(
                fragments,
                _LabelFragment(label) if label is not None else _CodeFragment(),
            )
            cursor = inline.end()
        else:
            assert container is not None
            for fragment in _parse_text_fragments(container.visible_text):
                _append_fragment(fragments, fragment)
            descriptor = "图片" if container.kind == "image" else "链接"
            prefix = " " if container.visible_text else ""
            _append_fragment(
                fragments, _OrdinaryFragment(prefix + descriptor)
            )
            cursor = container.end

    return tuple(fragments)


def _normalize_ordinary_text(value: str) -> str:
    text = _remove_unicode_controls(value)
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
    return _WHITESPACE_RE.sub(" ", text)


def normalize_full_text(value: str) -> str:
    text = _replace_fenced_code_before_fragmenting(value)
    fragments = _parse_text_fragments(text)
    rendered = (
        _normalize_ordinary_text(fragment.value)
        if isinstance(fragment, _OrdinaryFragment)
        else fragment.value
        if isinstance(fragment, _LabelFragment)
        else "代码"
        for fragment in fragments
    )
    return "".join(rendered).strip()


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
