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


def _parse_text_fragments(value: str) -> tuple[_TextFragment, ...]:
    fragments: list[_TextFragment] = []
    cursor = 0
    while cursor < len(value):
        candidates = (
            ("image", 0, _IMAGE_RE.search(value, cursor)),
            ("link", 1, _MARKDOWN_LINK_RE.search(value, cursor)),
            ("inline", 2, _INLINE_CODE_RE.search(value, cursor)),
        )
        available = [candidate for candidate in candidates if candidate[2]]
        if not available:
            _append_fragment(fragments, _OrdinaryFragment(value[cursor:]))
            break

        kind, _, match = min(
            available,
            key=lambda candidate: (
                candidate[2].start()
                if candidate[2] is not None
                else len(value),
                candidate[1],
            ),
        )
        assert match is not None
        _append_fragment(
            fragments, _OrdinaryFragment(value[cursor : match.start()])
        )

        if kind == "inline":
            label = _inline_label(match)
            _append_fragment(
                fragments,
                _LabelFragment(label) if label is not None else _CodeFragment(),
            )
        else:
            visible_text = match.group(1)
            for fragment in _parse_text_fragments(visible_text):
                _append_fragment(fragments, fragment)
            descriptor = "图片" if kind == "image" else "链接"
            prefix = " " if visible_text else ""
            _append_fragment(
                fragments, _OrdinaryFragment(prefix + descriptor)
            )
        cursor = match.end()

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
    text = _replace_fenced_code(value)
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
