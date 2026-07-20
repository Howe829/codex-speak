from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import re
import unicodedata
from typing import Final, Literal

from .protocol import ParsedResponse, TASK_TITLE_PLACEHOLDER


SpeechMode = Literal["summary", "full"]
MAX_SEGMENT_CHARS: Final[int] = 600
FULL_SEGMENT_CHARS: Final[int] = 180
MAX_TASK_TITLE_CHARS: Final[int] = 80

_FENCE_OPEN_RE = re.compile(
    r"(?m)^[ \t]*(?P<fence>`{3,}|~{3,})[^\r\n]*(?:\r?\n|\Z)"
)
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
    r"(?m)^[ \t]*(?:#{1,6}[ \t]+|>[ \t]*|[-+*][ \t]+)"
)
_EMPHASIS_RE = re.compile(r"(?:~~|[*_]+)")
_WHITESPACE_RE = re.compile(r"\s+")
_SAY_TRUNCATING_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:app|iphone)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_SAY_TOKEN_REPLACEMENTS: Final[dict[str, str]] = {
    "app": "A P P",
    "iphone": "I Phone",
}
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_SENTENCE_ENDINGS: Final[frozenset[str]] = frozenset("。！？.!?")
_UNCONDITIONAL_SENTENCE_ENDINGS: Final[frozenset[str]] = frozenset("。！？!?")
_SENTENCE_CLOSERS: Final[frozenset[str]] = frozenset("'’」』】）)]}")
_SAFE_INLINE_LABELS: Final[frozenset[str]] = frozenset({"/hooks"})
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
    starts_at_line_start: bool


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
    visible_start: int
    visible_end: int


@dataclass(frozen=True, slots=True)
class _InlineCodeSpan:
    start: int
    end: int
    label: str | None


@dataclass(frozen=True, slots=True)
class _MarkdownContainerIndex:
    openings: tuple[int, ...]
    containers: tuple[_MarkdownContainer, ...]
    inline_starts: tuple[int, ...]
    inline_spans: tuple[_InlineCodeSpan, ...]


@dataclass(frozen=True, slots=True)
class _FragmentScan:
    value: str
    cursor: int
    end: int
    starts_at_line_start: bool
    container_index: _MarkdownContainerIndex


@dataclass(frozen=True, slots=True)
class _FragmentEmission:
    fragment: _TextFragment


_FragmentWork = _FragmentScan | _FragmentEmission


@dataclass(frozen=True, slots=True)
class _PlainContainerScan:
    value: str
    cursor: int
    end: int
    container_index: _MarkdownContainerIndex


@dataclass(frozen=True, slots=True)
class _PlainContainerEmission:
    value: str


_PlainContainerWork = _PlainContainerScan | _PlainContainerEmission


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


def _normalize_say_compatibility(value: str) -> str:
    return _SAY_TRUNCATING_TOKEN_RE.sub(
        lambda match: _SAY_TOKEN_REPLACEMENTS[match.group(0).lower()],
        value,
    )


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
    if len(ticks) != 1 or not 1 <= len(content) <= 32:
        return None
    if content in _SAFE_INLINE_LABELS:
        return content
    text = _remove_unicode_controls(content)
    text = text.translate(_DOUBLE_QUOTE_TRANSLATION)
    text = _replace_plain_markdown_containers(text)
    text = _URL_RE.sub("链接", text)
    text = _PATH_RE.sub("相关文件", text)
    text = _normalize_say_compatibility(text)
    return text.strip() or None


def _append_fragment(
    fragments: list[_TextFragment], fragment: _TextFragment
) -> None:
    if isinstance(fragment, _OrdinaryFragment) and not fragment.value:
        return
    fragments.append(fragment)


def _index_markdown_containers(value: str) -> _MarkdownContainerIndex:
    bracket_stack: list[int] = []
    parenthesis_stack: list[int] = []
    bracket_openings: list[int] = []
    bracket_closings: dict[int, int] = {}
    parenthesis_closings: dict[int, int] = {}
    escaped_indices: set[int] = set()
    escaped = False
    matched_inline = tuple(_INLINE_CODE_RE.finditer(value))
    inline_spans = tuple(
        _InlineCodeSpan(match.start(), match.end(), _inline_label(match))
        for match in matched_inline
    )
    inline_matches = iter(matched_inline)
    inline = next(inline_matches, None)
    index = 0

    while index < len(value):
        while inline is not None and index >= inline.end():
            inline = next(inline_matches, None)
        inside_inline = (
            inline is not None
            and inline.start() <= index < inline.end()
        )
        char = value[index]
        if escaped:
            escaped_indices.add(index)
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if char == "[" and not inside_inline:
            bracket_stack.append(index)
            bracket_openings.append(index)
        elif char == "]" and not inside_inline and bracket_stack:
            bracket_closings[bracket_stack.pop()] = index
        if char == "(":
            parenthesis_stack.append(index)
        elif char == ")" and parenthesis_stack:
            parenthesis_closings[parenthesis_stack.pop()] = index
        index += 1

    openings: list[int] = []
    containers: list[_MarkdownContainer] = []
    for opening in bracket_openings:
        closing = bracket_closings.get(opening)
        if closing is None:
            continue
        destination_opening = closing + 1
        if (
            destination_opening >= len(value)
            or value[destination_opening] != "("
            or destination_opening in escaped_indices
        ):
            continue
        destination_closing = parenthesis_closings.get(
            destination_opening
        )
        if destination_closing is None:
            continue
        is_image = (
            opening > 0
            and value[opening - 1] == "!"
            and opening - 1 not in escaped_indices
        )
        openings.append(opening)
        containers.append(
            _MarkdownContainer(
                "image" if is_image else "link",
                opening - 1 if is_image else opening,
                destination_closing + 1,
                opening + 1,
                closing,
            )
        )
    return _MarkdownContainerIndex(
        tuple(openings),
        tuple(containers),
        tuple(span.start for span in inline_spans),
        inline_spans,
    )


def _find_markdown_container(
    index: _MarkdownContainerIndex, cursor: int, end: int
) -> _MarkdownContainer | None:
    position = bisect_left(index.openings, cursor)
    while position < len(index.containers):
        opening = index.openings[position]
        if opening >= end:
            return None
        container = index.containers[position]
        if container.start >= cursor and container.end <= end:
            return container
        position += 1
    return None


def _find_inline_code_span(
    index: _MarkdownContainerIndex, cursor: int, end: int
) -> _InlineCodeSpan | None:
    position = bisect_left(index.inline_starts, cursor)
    while position < len(index.inline_spans):
        span = index.inline_spans[position]
        if span.start >= end:
            return None
        if span.end <= end:
            return span
        position += 1
    return None


def _replace_plain_markdown_containers(value: str) -> str:
    parts: list[str] = []
    work: list[_PlainContainerWork] = [
        _PlainContainerScan(
            value,
            0,
            len(value),
            _index_markdown_containers(value),
        )
    ]
    while work:
        task = work.pop()
        if isinstance(task, _PlainContainerEmission):
            parts.append(task.value)
            continue

        container = _find_markdown_container(
            task.container_index, task.cursor, task.end
        )
        if container is None:
            parts.append(task.value[task.cursor : task.end])
            continue

        parts.append(task.value[task.cursor : container.start])
        descriptor = "图片" if container.kind == "image" else "链接"
        prefix = (
            " " if container.visible_start < container.visible_end else ""
        )
        work.extend(
            (
                _PlainContainerScan(
                    task.value,
                    container.end,
                    task.end,
                    task.container_index,
                ),
                _PlainContainerEmission(prefix + descriptor),
                _PlainContainerScan(
                    task.value,
                    container.visible_start,
                    container.visible_end,
                    task.container_index,
                ),
            )
        )
    return "".join(parts)


def _starts_at_line_start(
    value: str, index: int, value_starts_at_line_start: bool
) -> bool:
    return (
        value_starts_at_line_start
        if index == 0
        else value[index - 1] in {"\r", "\n"}
    )


def _parse_text_fragments(
    value: str, *, starts_at_line_start: bool = True
) -> tuple[_TextFragment, ...]:
    fragments: list[_TextFragment] = []
    work: list[_FragmentWork] = [
        _FragmentScan(
            value,
            0,
            len(value),
            starts_at_line_start,
            _index_markdown_containers(value),
        )
    ]
    while work:
        task = work.pop()
        if isinstance(task, _FragmentEmission):
            _append_fragment(fragments, task.fragment)
            continue

        cursor = task.cursor
        while cursor < task.end:
            container = _find_markdown_container(
                task.container_index, cursor, task.end
            )
            inline = _find_inline_code_span(
                task.container_index, cursor, task.end
            )
            if container is None and inline is None:
                _append_fragment(
                    fragments,
                    _OrdinaryFragment(
                        task.value[cursor : task.end],
                        _starts_at_line_start(
                            task.value,
                            cursor,
                            task.starts_at_line_start,
                        ),
                    ),
                )
                break

            container_is_next = container is not None and (
                inline is None or container.start < inline.start
            )
            match_start = (
                container.start if container_is_next else inline.start
            )
            _append_fragment(
                fragments,
                _OrdinaryFragment(
                    task.value[cursor:match_start],
                    _starts_at_line_start(
                        task.value,
                        cursor,
                        task.starts_at_line_start,
                    ),
                ),
            )

            if not container_is_next:
                assert inline is not None
                _append_fragment(
                    fragments,
                    _LabelFragment(inline.label)
                    if inline.label is not None
                    else _CodeFragment(),
                )
                cursor = inline.end
                continue

            assert container is not None
            descriptor = "图片" if container.kind == "image" else "链接"
            prefix = (
                " "
                if container.visible_start < container.visible_end
                else ""
            )
            work.extend(
                (
                    _FragmentScan(
                        task.value,
                        container.end,
                        task.end,
                        task.starts_at_line_start,
                        task.container_index,
                    ),
                    _FragmentEmission(
                        _OrdinaryFragment(prefix + descriptor, False)
                    ),
                    _FragmentScan(
                        task.value,
                        container.visible_start,
                        container.visible_end,
                        False,
                        task.container_index,
                    ),
                )
            )
            break

    return tuple(fragments)


def _remove_at_source_line_starts(
    pattern: re.Pattern[str], value: str, starts_at_line_start: bool
) -> str:
    return pattern.sub(
        lambda match: ""
        if starts_at_line_start or match.start() > 0
        else match.group(0),
        value,
    )


def _normalize_ordinary_text(
    value: str, *, starts_at_line_start: bool
) -> str:
    text = _remove_unicode_controls(value)
    text = text.translate(_DOUBLE_QUOTE_TRANSLATION)
    text = _replace_plain_markdown_containers(text)
    text = _URL_RE.sub("链接", text)
    text = _PATH_RE.sub("相关文件", text)
    text = _normalize_say_compatibility(text)
    text = _remove_at_source_line_starts(
        _TABLE_SEPARATOR_RE, text, starts_at_line_start
    )
    text = _remove_at_source_line_starts(
        _MARKDOWN_LINE_PREFIX_RE, text, starts_at_line_start
    )
    text = text.replace("|", " ")
    text = _EMPHASIS_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text)


def normalize_full_text(value: str) -> str:
    text = _replace_fenced_code_before_fragmenting(value)
    fragments = _parse_text_fragments(text)
    rendered: list[str] = []
    ordinary: list[str] = []
    ordinary_starts_at_line_start = True

    def flush_ordinary() -> None:
        if not ordinary:
            return
        rendered.append(
            _normalize_ordinary_text(
                "".join(ordinary),
                starts_at_line_start=ordinary_starts_at_line_start,
            )
        )
        ordinary.clear()

    for fragment in fragments:
        if isinstance(fragment, _OrdinaryFragment):
            if not ordinary:
                ordinary_starts_at_line_start = (
                    fragment.starts_at_line_start
                )
            ordinary.append(fragment.value)
            continue
        flush_ordinary()
        rendered.append(
            fragment.value
            if isinstance(fragment, _LabelFragment)
            else "代码"
        )
    flush_ordinary()
    return "".join(rendered).strip()


def compose_speech_lead(template: str, task_title: str | None) -> str:
    normalized_title = normalize_full_text(task_title or "")[
        :MAX_TASK_TITLE_CHARS
    ].strip()
    if not normalized_title:
        normalized_title = (
            "当前任务" if _CJK_RE.search(template) else "current task"
        )
    return template.replace(TASK_TITLE_PLACEHOLDER, normalized_title)


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


def segment_full_text(
    value: str, limit: int = FULL_SEGMENT_CHARS
) -> tuple[str, ...]:
    if limit < 1:
        raise ValueError("limit must be positive")
    if not value:
        return ()

    segments: list[str] = []
    start = 0
    cursor = 0
    while cursor < len(value):
        character = value[cursor]
        if character not in _SENTENCE_ENDINGS:
            cursor += 1
            continue

        end = cursor + 1
        while end < len(value) and value[end] in _SENTENCE_ENDINGS:
            end += 1
        while end < len(value) and value[end] in _SENTENCE_CLOSERS:
            end += 1
        if (
            character not in _UNCONDITIONAL_SENTENCE_ENDINGS
            and end < len(value)
            and not value[end].isspace()
        ):
            cursor += 1
            continue

        segments.extend(segment_text(value[start:end], limit=limit))
        start = end
        cursor = end

    if start < len(value):
        segments.extend(segment_text(value[start:], limit=limit))
    return tuple(segments)


def render_speech(
    response: ParsedResponse,
    mode: SpeechMode,
    *,
    task_title: str | None = None,
) -> SpeechPayload | None:
    if mode == "summary":
        if response.status == "silent":
            return None
        text = response.summary_text
    elif mode == "full":
        text = normalize_full_text(response.visible_body)
    else:
        raise ValueError(f"unsupported speech mode: {mode}")

    if response.speech_lead_template:
        text = compose_speech_lead(
            response.speech_lead_template, task_title
        ) + text
    text = _normalize_say_compatibility(text)

    segments = (
        segment_full_text(text)
        if mode == "full"
        else segment_text(text)
    )
    if not segments:
        return None
    return SpeechPayload(mode, response.status, segments)
