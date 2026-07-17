# Task Title Speech Prefix Design

**Date:** 2026-07-17

## Summary

Codex Speak will identify important spoken results with the real user-facing
Codex task title. Completed, blocked, and action-required responses will begin
with a short lead such as:

> 豪哥，任务：确认 codex-speak 发布前准备已完成。

The lead follows the language and form of address already established in the
conversation. When no form of address is known, it begins directly with the
task. The existing Summary, Full, and Silent control modes keep their current
meaning.

## Goals

- Distinguish concurrent Codex tasks by speaking the task title before an
  important result.
- Use the actual title shown by Codex, including a user-renamed title.
- Cover `completed`, `blocked`, and `action_required` with status-appropriate
  wording.
- Follow the conversation's language and known form of address without
  hard-coding a personal name into the public plugin.
- Apply the lead consistently in Summary and Full modes when the response has
  an important status.
- Preserve existing v1 and v2 marker compatibility.
- Fail open: title lookup problems must not suppress or delay the underlying
  speech beyond a short bounded timeout.

## Non-goals

- Adding a menu item or persistent setting for the user's form of address.
- Adding a user-editable title independent of the Codex task title.
- Prefixing ordinary `silent`-status responses that Full mode chooses to read.
- Reading or announcing subagent titles; the plugin registers the root `Stop`
  hook, not `SubagentStop`.
- Publishing, releasing, or reinstalling the plugin as part of this design.

## Evaluated Title Sources

### 1. Codex `thread/read` through app-server — selected

The Stop hook already receives `session_id`, which Codex represents as the
thread ID. A short-lived `codex app-server --stdio` client can initialize, call
`thread/read` with that ID, and read the returned thread's `name`. This path was
verified against the current local Codex build and returned the exact sidebar
name `确认 codex-speak 发布前准备`.

This is selected because `thread/read` is a documented Codex protocol surface
and does not require Codex Speak to understand private persistence schemas. Its
cost is a short child-process startup, controlled by a strict timeout.
The `app-server` CLI remains marked experimental, so all interaction is
isolated behind one resolver and a generic-title fallback; a future protocol
change cannot prevent the underlying speech from being queued.

### 2. Parse `session_index.jsonl` — rejected as the primary source

The current Codex home records `thread_name` entries keyed by the same thread
ID. Reading this file would be fast, but its format and location are internal
persistence details and can change independently of the app-server protocol.

### 3. Query Codex SQLite state directly — rejected

The state database contains the required title and would avoid a second Codex
process, but it couples the plugin to a private schema, introduces migration and
locking risks, and creates an unnecessary direct dependency on Codex storage.

## Protocol v3

SessionStart will instruct the model to emit a v3 CommonMark reference marker:

```text
[codex-speak-v3]: <codex-speak:v3#{"status":"completed","speech_lead":"豪哥，任务：{{task_title}}已完成。","speech_text":"语音前置信息方案已经实现，无需继续操作。"}>
```

The exact payload keys are:

- `status`: one of `completed`, `blocked`, `action_required`, or `silent`.
- `speech_lead`: a short speech-ready template containing exactly one literal
  `{{task_title}}` placeholder for important statuses.
- `speech_text`: the concise result details and real next step, if any.

For `silent`, both `speech_lead` and `speech_text` must be empty. For every
important status, both must be non-empty and `speech_lead` must contain exactly
one placeholder.

The model chooses the language, form of address, and status wording from the
active conversation. The SessionStart rules include these canonical Chinese
examples:

- `completed`: `豪哥，任务：{{task_title}}已完成。`
- `blocked`: `豪哥，任务：{{task_title}}遇到阻塞。`
- `action_required`: `豪哥，任务：{{task_title}}需要你处理。`

If the conversation has no known form of address, the lead begins with
`任务：`. Equivalent wording in the conversation's language is valid.

The v3 label and URI distinguish the new three-field payload from v2. The
parser continues accepting v1 and v2 markers with their current semantics.
Legacy markers do not gain a synthesized task lead, so an already-running old
task behaves exactly as before. A newly installed version needs a new task for
SessionStart to activate v3, consistent with the existing upgrade model.

## Title Resolver

A focused Python title-resolver unit will own app-server interaction. Given a
validated Stop-hook `session_id`, it will:

1. Resolve the `codex` executable from `PATH`.
2. Launch `codex app-server --stdio` with the current environment and hook
   working directory.
3. Send `initialize`, then `initialized`, then `thread/read` with
   `includeTurns: false`.
4. Ignore unrelated notifications and accept only the response with the
   expected request ID and matching thread ID.
5. Prefer the non-empty `thread.name`; use the non-empty `thread.preview` only
   when `name` is absent, matching Codex's untitled-thread presentation.
6. Terminate and reap the child process on success, timeout, malformed output,
   or any other failure.

The entire lookup has a 1.5-second deadline and bounded output consumption.
The resolver returns no raw error text. The Stop hook must not write the thread
ID, title, app-server output, or failure details to diagnostics.

The resolved title is converted to single-line speech-ready plain text using
the same safety principles as marker speech: remove controls, Markdown syntax,
URLs, and absolute paths; collapse whitespace; and cap the final title at 80
Unicode characters. An empty result is treated as lookup failure.

## Speech Composition

The Stop-hook flow becomes:

1. Validate the hook IDs and parse the final response marker.
2. Load the current control mode; return immediately in Silent mode.
3. Determine whether the response will produce speech under Summary or Full.
4. Only when a valid v3 important-status lead is present, resolve the title.
5. Substitute the sanitized title into the lead and render the final speech.
6. Enqueue and start the existing consumer exactly as today.

Summary mode renders:

```text
resolved lead + speech_text
```

Full mode renders an important response as:

```text
resolved lead + normalized visible response body
```

Full mode continues reading an ordinary `silent`-status visible body without a
task lead. Silent control mode continues suppressing all rendering, title
lookup, queue writes, and consumer startup.

The lead template is sanitized before substitution and capped independently.
The task title is substituted as plain text, never interpreted as markup or a
second template. Existing segment limits split long composed speech without
dropping the lead.

## Fallback Behavior

Title resolution is best effort. If the executable is unavailable, app-server
returns an error, the response is malformed, the title is empty, or the
deadline expires, speech continues using a generic title:

- `当前任务` when the lead contains Chinese characters.
- `current task` otherwise.

For example, the Chinese fallback is:

```text
豪哥，任务：当前任务已完成。正文
```

A title lookup failure is not a queue, renderer, or helper failure and does not
create a diagnostic record. This prevents an optional identity enhancement
from changing the reliability or privacy posture of existing speech.

## Validation and Limits

- v3 accepts exactly the three documented payload keys.
- Important `speech_lead` templates contain exactly one literal placeholder.
- Silent v3 payloads require both speech fields to be empty.
- The template before substitution is capped at 120 Unicode characters.
- Resolved titles are capped at 80 Unicode characters.
- `speech_text` keeps the existing soft and hard limits.
- Marker and title sanitation continue rejecting or removing Markdown, code,
  URLs, paths, control characters, and line breaks from spoken content.
- v1 and v2 parsing and rendering remain unchanged.

## Testing

Python tests will cover:

- SessionStart emits v3 instructions, the exact placeholder contract, Chinese
  examples for all three important statuses, and neutral-address behavior.
- Protocol parsing accepts valid v3 payloads and rejects missing, duplicate,
  malformed, extra-key, over-limit, and silent-with-content variants.
- v1 and v2 protocol fixtures retain their current parsed results.
- The title resolver handles notifications before the matching response,
  prefers `name`, falls back to `preview`, validates the thread ID, sanitizes
  titles, enforces output bounds, times out, and reaps its child process.
- Summary mode composes lead plus summary body.
- Full mode composes lead plus visible body for important statuses and does not
  prefix ordinary silent-status speech.
- A missing title uses the Chinese or non-Chinese generic fallback.
- Silent control mode never calls the resolver.
- Diagnostics never contain the title, session ID, or raw app-server output.
- Existing queue, worker, bridge, privacy, packaging, and hook tests remain
  green.

## Acceptance Criteria

- Two simultaneously completing tasks announce different real sidebar titles.
- User-renamed task names are spoken on the next important completion.
- Completed, blocked, and action-required responses use distinct lead wording.
- The current conversation's known form of address is used; unknown users hear
  no hard-coded personal name.
- Summary and Full behavior matches the composition rules above.
- A failed or slow title lookup still produces the original speech with the
  generic task fallback within the bounded delay.
- Silent mode performs no title lookup and produces no speech.
- Existing v1/v2 tasks retain their prior behavior, and all automated tests
  pass.
