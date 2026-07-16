# Codex Speak Full Speech Quoted Labels Design

## Goal

Fix two Full-mode speech defects without changing Summary mode, queueing,
playback concurrency, diagnostics, or helper heartbeat behavior:

1. Text inside ASCII, Chinese, or full-width double quotes must be spoken.
2. Short prose labels such as `` `Full` `` must be spoken as their visible
   text instead of being replaced with the generic inline-code placeholder.

## Root cause

The Full renderer currently preserves double quotes. macOS `say` interprets
quoted input in a way that can omit the text between the quote marks. Removing
the quote delimiters before playback preserves the intended words.

The renderer also replaces every matched inline-code span with `代码`, without
distinguishing a short prose label from executable or structured code.

## Double-quote normalization

During `normalize_full_text`, remove double-quote delimiter characters while
keeping all enclosed text in place. The supported delimiters are:

- ASCII double quote: `"`
- Chinese opening and closing double quotes: `“` and `”`
- Low and reversed double quotes: `„` and `‟`
- Full-width double quote: `＂`

The operation is deliberately delimiter-only. It does not require balanced
pairs and does not remove single quotes or apostrophes. Existing control,
Markdown, URL, path, table, and whitespace normalization remains unchanged.

## Inline-label classification

Keep fenced code and multi-backtick inline spans unchanged: they continue to
produce `代码块` and `代码` placeholders respectively.

For a matched single-backtick inline span, unwrap and speak the content only
when all of these conditions hold:

1. The trimmed content contains 1 through 32 Unicode characters.
2. Every character is a Unicode letter or number, whitespace, or ASCII
   hyphen. Underscores remain code-shaped because the later Markdown emphasis
   pass would otherwise change the label's visible text.
3. The content contains no newline.

Examples preserved as labels:

- `` `Full` ``
- `` `Summary` ``
- `` `codex-speak` ``
- `` `语音模式` ``

Examples replaced with `代码`:

- `` `x=1` ``
- `` `run()` ``
- `` `~/secret` ``
- `` `a | b` ``
- Any inline span longer than 32 characters
- Any span delimited by two or more backticks

This rule is intentionally syntax-based rather than a fixed product-term
allowlist, so future short UI labels work without another release while code,
paths, and shell-like expressions retain the existing speech-safe placeholder.

## Data flow and isolation

`hooks/stop.py` continues to pass the visible response to
`render_speech`. Only `codex_speak.render.normalize_full_text` changes its
normalization result. Segmentation, queue serialization, the Swift bridge,
`/usr/bin/say` invocation, and metadata-only diagnostics receive the same
interfaces as before.

The helper heartbeat and any external watchdog or transcription heartbeat are
outside this change and must remain untouched.

## Error handling and privacy

Normalization remains deterministic and exception-free for arbitrary Unicode
input. Unbalanced double quotes are handled by removing the delimiter only.
Code-shaped or ambiguous inline content fails closed to the existing `代码`
placeholder. No response text is added to diagnostics, command arguments, or
persistent settings.

## Tests and acceptance

Add focused renderer tests that first reproduce and then protect:

- The complete heartbeat sentence with Chinese double quotes normalizes to the
  same sentence without quote delimiters and with both quoted phrases intact.
- ASCII and full-width double-quoted text retains its content.
- `` `Full` ``, `` `Summary` ``, `` `codex-speak` ``, and a short Chinese label
  retain their visible text.
- Assignment, function-call, path, shell-like, over-length, and multi-backtick
  spans continue to normalize to `代码`.

Run the focused renderer tests, the full Python suite, the Python compile and
Hook JSON checks, the Swift suite with warnings as errors, plugin validation,
and packaging verification before release. A final macOS `say` smoke should
confirm the original quoted heartbeat sentence is no longer shortened.

## Release scope

The release version becomes `0.2.2`. The implementation changes only the Full
renderer, its tests, release notes, and manifest version. The embedded Swift
helper is unchanged because playback receives the same segment interface. The
formal Marketplace source receives the accepted files and a refreshed
cachebuster version beginning with `0.2.2+codex.`.

The release does not modify Summary protocol semantics, menu behavior, speech
ordering, queue formats, runtime permissions, diagnostics schemas, helper
packaging, or heartbeat behavior.
