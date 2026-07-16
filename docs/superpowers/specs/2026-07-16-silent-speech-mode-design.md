# Codex Speak Silent Speech Mode Design

## Goal

Ship Codex Speak `0.2.3` with a persistent `Silent` mode in the macOS menu
bar control. Selecting Silent must immediately stop current speech, remove all
pending speech, and prevent every subsequent event from producing audio until
the user selects Summary or Full.

Silent is a control state, not a playable event mode. Queue, bridge, and
diagnostic speech-event schemas continue to accept only Summary and Full
events.

## Menu and persistence

The menu contains exactly six items in this order:

1. `Silent`
2. `Summary`
3. `Full`
4. `Stop Current Speech`
5. `Clear Pending Speeches`
6. `Quit Codex Speak`

Silent, Summary, and Full are mutually exclusive checkmarked modes. The
persisted settings schema remains version 1 and adds `silent` to the accepted
mode values. Existing `summary` and `full` settings remain valid without a
migration. A missing or invalid settings file still repairs to Summary.

Silent persists across Codex, helper, and machine restarts until explicitly
changed.

## Selecting Silent

The menu action uses this order:

1. Persist `silent` through the existing control client and read it back.
2. Update the selected mode and all three checkmarks.
3. Stop the current Swift-owned speech process.
4. Clear every pending queue entry.

The persisted mode is the primary safety gate. Once readback confirms Silent,
new Stop-hook events are suppressed even if stopping or clearing encounters an
error.

If the persistence command fails, the menu restores its prior selected mode,
leaves current playback and pending events unchanged, and shows the existing
local mode-change error.

For a Silent selection, if persistence succeeds but readback fails, the menu
fails safe to Silent, stops and clears speech, and shows the read error. A
successful persistence write is sufficient evidence that future hooks may
already be suppressing events; continuing to play would violate the requested
behavior. If readback succeeds with a different mode because another trusted
control changed it concurrently, the menu adopts that returned mode and does
not run Silent's stop-and-clear side effects.

Current-speech cancellation is best effort and queue clearing may report a
failure after Silent is active. The mode remains Silent and the helper shows a
local error for the queue failure. The playback and fallback guards described
below still prevent a newly claimed event from starting. Existing fixed,
metadata-only diagnostics remain the only persisted error evidence.

Selecting Summary or Full changes only the persisted mode and checkmarks. A
successful write immediately makes the requested audible mode the trusted
local selection. A successful readback may replace it with the returned
trusted mode; if readback fails, the requested mode remains selected and the
menu shows `Could not read speech mode` rather than treating the successful
write as a write failure or restoring the prior mode. The successful audible
write supersedes any older Silent stop-and-clear continuation, so that stale
continuation must not clear the queue or record a queue-clear diagnostic. It
returns a result consistent with the current trusted selection. A failed
audible write does not supersede an older successfully persisted selection.
Returning to Summary or Full does not replay events discarded while Silent was
active.

## Event suppression

Suppression is enforced at every boundary where a race or fallback could
otherwise produce speech:

### Stop hook

After loading the persisted mode, the Stop hook returns without rendering,
enqueueing, or starting a consumer when the mode is `silent`. It still emits
the normal empty hook response and never stores assistant or user text.

### Native helper

The helper refreshes persisted mode before starting its bridge. If startup
mode is Silent, it best-effort clears pending events before the bridge begins
claiming them.

The event handler checks the selected mode immediately before playback. An
event claimed just before Silent was selected is acknowledged without calling
`SpeechPlayer.play`. It records only fixed cancellation metadata with zero
completed segments; no speech text enters diagnostics.

### Python fallback

The Python fallback worker loads persisted mode immediately before each event
would be spoken. In Silent mode it discards the claimed event, records only
fixed discarded metadata, and never invokes `/usr/bin/say`. This protects
restart, missing-helper, and already-queued fallback paths.

## Schema boundaries

Python settings and the Swift control client accept three control modes:
`silent`, `summary`, and `full`.

Speech payloads, queue envelopes, bridge NDJSON events, and playback
diagnostics continue to accept only `summary` and `full`. A forged or corrupt
speech event with `mode: silent` is rejected rather than played or treated as
a valid empty event.

The renderer remains defined only for Summary and Full. Silent does not add a
third rendering branch because it is filtered before rendering.

## Concurrency and lifecycle

The persisted Silent write occurs before cancellation and queue clearing, so a
concurrent Stop hook sees Silent and cannot add new work during the transition.
The native event handler's final mode check closes the claim-versus-selection
race. Queue clearing removes unclaimed work; the handler acknowledges any
already-claimed event without playback.

At helper startup, persisted mode is loaded before bridge consumption. At
fallback playback, persisted mode is checked per event. These gates make
Silent fail safe across helper restarts without changing queue format or lock
ownership.

Switching back to Summary or Full affects only future events. Silent-period
events have already been suppressed, acknowledged, or discarded and cannot be
reconstructed.

## Tests and acceptance

Python tests cover:

- Saving, loading, CLI setting, and restart persistence of `silent`.
- Invalid settings still repairing to Summary.
- Stop hook in Silent mode does not render, enqueue, or start a consumer.
- Python fallback in Silent mode never invokes `say` and records only fixed
  discarded metadata.
- Queue and bridge event validators continue to reject `mode: silent`.

Swift tests cover:

- The exact six-item menu order.
- Three mutually exclusive checkmarks and refresh from persisted Silent.
- Successful Silent selection persists first, stops current speech, and clears
  pending events.
- A persistence failure keeps the prior mode and does not stop or clear.
- A Silent readback failure after successful persistence fails safe to Silent,
  stops current speech, clears pending work, and reports the read error.
- A Summary/Full write followed by readback failure keeps the successfully
  persisted requested mode selected and reports the distinct read error.
- A successfully persisted audible selection supersedes a suspended Silent
  cleanup even when audible readback fails; a failed audible write does not.
- A queue-clear failure leaves Silent active and reports a fixed local error.
- A claimed event is acknowledged without playback when Silent is selected.
- Startup Silent mode clears pending work before bridge consumption.
- `SpeechMode.silent` is accepted by the control client but rejected in
  decoded speech events.

Release acceptance verifies:

1. Select Full and begin a long response.
2. Select Silent while speech is active.
3. Confirm audio stops immediately and pending speech is cleared.
4. Produce multiple Codex responses and confirm no audio.
5. Restart Codex/helper and confirm Silent remains checked and no audio plays.
6. Select Summary, then Full, and confirm only new eligible events play.
7. Confirm the spool is empty and diagnostics contain metadata only.

## Release scope

The release version becomes `0.2.3`. The Swift helper is rebuilt because the
menu, control mode, startup lifecycle, and event handler change. The universal
`x86_64 arm64` app remains locally ad hoc signed. The formal Marketplace
version begins with `0.2.3+codex.`.

The release does not change the speech protocol marker, renderer semantics,
queue format, bridge format, event ordering, heartbeat format, runtime
permissions, or diagnostic schema.
