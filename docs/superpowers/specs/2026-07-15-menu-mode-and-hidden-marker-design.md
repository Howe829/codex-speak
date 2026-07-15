# Codex Speak Menu Mode and Hidden Marker Design

## Goal

Fix two acceptance defects without changing speech, queue, privacy, or fallback semantics:

1. The menu checkmark must reflect the persisted Summary/Full mode whenever the menu opens.
2. New Codex tasks must not display the speech-control marker as visible response text.

The release version becomes `0.2.1` before the Marketplace cachebuster is refreshed.

## Menu mode synchronization

`MenuController` will conform to `NSMenuDelegate`, assign itself as the status menu delegate, and call the existing `refreshMode()` from `menuWillOpen(_:)`.

The persisted settings file remains the only source of truth. Opening the menu performs one read through `ControlClient`; it does not add polling or a filesystem watcher. A successful read updates both checkmarks. A failed read keeps the previous selection and uses the existing local error indicator.

The existing Summary and Full actions remain unchanged: they write the requested mode, read it back, and update checkmarks.

## Hidden protocol marker

New tasks will receive protocol version 2 from the SessionStart hook. The final line will be one strict, unused CommonMark reference definition:

```text
[codex-speak-v2]: <codex-speak:v2#{"status":"completed","speech_text":"任务完成。"}>
```

An unused reference definition is metadata in rendered Markdown and is not shown as response content. The Stop hook still receives the raw final response and parses the trailing line.

Version 2 keeps the existing exact payload keys, statuses, summary sanitization, `silent` rules, and 280-character hard limit. The payload must remain on one line. Sanitization must prevent `<`, `>`, line breaks, or controls from escaping the angle-bracket destination.

The parser accepts exactly one trailing marker. It rejects duplicates, mixed v1/v2 markers, non-trailing markers, extra payload keys, malformed JSON, invalid status/text combinations, and unknown versions.

## Migration behavior

The `0.2.1` Stop hook temporarily accepts the current `codex-speak:v1` HTML-comment marker so this already-running task continues to work after reinstall. SessionStart emits only v2, so every new task uses the hidden marker.

Legacy `codex-voice-notifier` markers remain rejected. The compatibility parser is transitional and may be removed in a later release after existing tasks have expired.

The current task cannot replace its already-injected developer instruction. After reinstall, acceptance must continue in a new task.

## Tests

Tests will be written before production changes and observed failing for the missing behaviors.

- A packaging/source regression test requires `NSMenuDelegate`, menu delegate assignment, and `menuWillOpen(_:)` mode refresh.
- Protocol tests cover v2 extraction, invisible reference shape, body stripping, sanitization, all status rules, duplicate/mixed/non-trailing rejection, v1 transition compatibility, and legacy rejection.
- SessionStart tests require v2 instructions and forbid instructing new tasks to emit v1.
- Renderer, hooks, queue, worker, privacy, packaging, and Swift suites remain green.
- The embedded universal helper is rebuilt and strict signature/architecture checks rerun.

## Release and acceptance

After all checks pass:

1. Build and embed the universal menu helper.
2. Bump the formal plugin version to `0.2.1` and refresh its cachebuster.
3. Synchronize the accepted development tree to the formal personal Marketplace source.
4. Reinstall `codex-speak@personal`, trust changed hooks, and start a new task.
5. Verify the menu checkmark follows an external mode change when reopened.
6. Verify the v2 marker is absent from rendered response content while Summary and Full speech still work.

No external distribution signing is included; the helper remains a locally ad hoc signed build.
