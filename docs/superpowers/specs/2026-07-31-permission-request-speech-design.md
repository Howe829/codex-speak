# Permission Request Speech Design

**Date:** 2026-07-31  
**Status:** Confirmed for implementation

## Goal

Add a Codex `PermissionRequest` hook that gives a short local speech alert whenever Codex creates a permission request. The alert supplements the existing approval UI; it never approves, denies, rewrites, or otherwise changes the request.

## Confirmed Product Behavior

- Every `PermissionRequest` event is eligible for an alert, including requests that Auto-review may subsequently handle.
- Silent mode suppresses the alert.
- Summary and Full modes both speak the same neutral sentence: `Codex 有操作需要审批。`
- The alert never includes the command, tool arguments, paths, approval description, or other request content.
- Existing voice selection, speech rate, menu controls, queue behavior, Stop-hook behavior, and response-marker protocol remain unchanged.

## Considered Approaches

### 1. Dedicated hook that reuses the existing speech queue

This is the selected approach. A new handler owns `PermissionRequest` validation and alert construction, then uses the existing queue and consumer. It preserves current delivery, cancellation, diagnostics, and privacy boundaries without treating an approval as a completed assistant response.

### 2. Convert the approval into a synthetic Stop event

Rejected. A synthetic response marker would blur permission and turn-completion semantics, add unnecessary parsing, and risk colliding with the real Stop event from the same turn.

### 3. Invoke macOS `say` directly from the hook

Rejected. Direct playback would bypass the queue, mode settings, helper lifecycle, stop and clear controls, and normal diagnostics. It would also make the hook wait on speech playback.

## Architecture

### Hook registration

`hooks/hooks.json` will register a `PermissionRequest` command handler with a wildcard matcher. The handler will live at `hooks/permission_request.py` and will use `PLUGIN_ROOT` and `PLUGIN_DATA` in the same way as the existing hooks.

The command exits successfully with empty standard output. It returns no approval decision, so Codex continues its normal approval flow.

### Handler responsibilities

The handler will:

1. Parse hook JSON from standard input.
2. Validate the minimum identity fields required for safe queueing.
3. Return immediately on non-macOS platforms or when the persisted mode is Silent.
4. Construct one fixed `action_required` speech payload for Summary or Full mode.
5. Enqueue the alert under a permission-specific identity.
6. Start the existing consumer on a best-effort basis.
7. Exit successfully with empty standard output and without `allow`, `deny`, `updatedInput`, or other permission-control output.

The handler will not import Stop-marker parsing or task-title resolution because approval alerts have fixed content and are not task-result announcements.

### Event identity and deduplication

The existing queue derives an event ID from `session_id` and the supplied turn identity. Passing the raw `turn_id` would collide with a later Stop event from the same turn, so the handler will derive a namespaced queue identity from:

- the hook event type;
- the original turn ID;
- the canonical tool name;
- a deterministic digest of the tool input.

The raw command and arguments will not be stored in the derived identity. Repeated delivery of the same approval request within one turn deduplicates, while the subsequent Stop event keeps its own existing identity.

### Modes and queue behavior

Silent mode creates no queue event and starts no consumer. Summary and Full retain their actual mode value in the queued payload but use the same fixed sentence.

The existing queue settle delay, expiry, per-session ordering, menu actions, helper process, bridge, and worker remain unchanged. Approval events use the existing `action_required` status so diagnostics and playback validation need no new status value.

### Privacy and security

The implementation treats all `PermissionRequest` tool data as sensitive. It validates only what it needs for event identity and never writes or speaks request content. Diagnostics remain metadata-only.

The handler is fail-open with respect to the approval UI: malformed input, settings-loader failure, queue errors, or helper startup failures may suppress the speech alert, but they must not approve, deny, delay, or block the underlying request. The handler catches internal failures and exits successfully with no decision.

## Error Handling

- Unsupported platform: discard the speech alert and record metadata when possible.
- Invalid or missing hook identity: discard the alert without exposing input data.
- Invalid persisted settings: preserve the existing `load_mode` diagnostic and Summary fallback. If the settings loader itself raises, discard the alert.
- Queue failure: discard any partial event and record a bounded error code.
- Consumer startup failure: preserve an event only when another consumer owns the worker lock; otherwise remove it and record failure.
- Any unexpected exception at the command boundary: emit no permission decision and exit successfully.

## Test Strategy

Implementation will follow red-green-refactor. Tests will cover:

- hook configuration registers `PermissionRequest` without changing existing registrations;
- Summary and Full enqueue the fixed alert with `action_required` status;
- Silent mode does not enqueue or start the consumer;
- the permission-specific event identity does not collide with the turn's Stop identity;
- repeated equivalent approval input deduplicates;
- tool input and approval description never appear in queued speech or diagnostics;
- malformed input, unsupported platforms, settings-loader errors, queue errors, and helper startup errors do not emit approval decisions;
- the command entry point exits zero with empty standard output and returns no `allow` or `deny` behavior;
- packaging and privacy tests include the new hook file and command.

## Acceptance Conditions

The feature is ready for release only when all of the following are demonstrated:

1. After the updated hook definition is reviewed and trusted, a real approval-requiring Codex action triggers the fixed speech alert in Summary and Full modes.
2. The normal approval interface still appears and retains control of the decision.
3. Silent mode produces no approval speech.
4. Approval speech and the later task-result speech can both be delivered for the same turn.
5. No command text, path, tool arguments, or approval description is written to the speech queue or diagnostics.
6. Existing Python, Swift, packaging, privacy, plugin validation, and installed-plugin smoke checks remain green.

Real audible acceptance remains a human verification step and is distinct from automated tests.

## Out of Scope

- Detecting whether an approval was actually shown to a human instead of Auto-review.
- Speaking the approval result after the user or reviewer decides.
- Adding new menu settings, custom wording, voice selection, or rate controls.
- Changing approval policy, Auto-review configuration, sandbox permissions, or MCP annotations.
- Publishing, pushing, releasing, or reinstalling the plugin as part of implementation without a separate explicit request.
