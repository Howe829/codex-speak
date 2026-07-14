# Codex Speak

Codex Speak is a local macOS Codex Plugin that speaks turn outcomes with the
system `say` command. It can announce concise outcome summaries or read the
complete visible response, while a private menu bar helper provides playback
controls without adding commands to the conversation.

## Requirements

- macOS 13.0 or newer
- Python 3.10 or newer available as `python3`
- Codex with Plugin lifecycle-hook support
- Xcode command-line tools with Swift 6 only when rebuilding the menu helper

Runtime operation uses the Python standard library and macOS frameworks. It
needs no network service, API key, third-party Python package, custom voice,
or global Codex `notify` setting.

## Install and trust

The personal Marketplace source is `/Users/howard/plugins/codex-speak`, with
its entry in `/Users/howard/.agents/plugins/marketplace.json`:

```bash
codex plugin add codex-speak@personal
```

Open `/hooks` after installation, review the bundled `SessionStart` and `Stop`
commands, and trust the current definitions. Codex asks again when a hook
definition changes. Start a new thread after installation or reinstall so the
SessionStart protocol becomes active.

The embedded app is built and ad hoc signed locally. macOS may ask for local
execution approval if the checkout or app was downloaded or quarantined;
review its origin before approving it. Do not bypass Gatekeeper for an app you
do not trust.

## Speech modes and outcomes

The menu bar checkmark selects one speech mode:

- `Summary` speaks only important `completed`, `blocked`, or
  `action_required` outcome text. Ordinary `silent` answers remain quiet.
- `Full` reads the normalized visible response. Markdown formatting, code,
  URLs, and local paths are replaced with speech-safe descriptions.

Important announcements follow the active primary instruction. Internal
commands, temporary files, tests, test fixtures, validation artifacts, and
tool mechanics remain unspoken unless explicitly requested. Language,
salutation, and tone come from active context such as `AGENTS.md`, memory, and
conversation preferences; the plugin does not hard-code a user's name.

The default macOS voice and rate are used. `Plugin Toggle` in Codex controls the whole plugin,
including both hooks and speech; it is not a mode selector.
Use `Summary` or `Full` in the menu to change only the speech mode.

## Menu controls

The helper has exactly five menu actions:

1. `Summary`
2. `Full`
3. `Stop Current Speech`
4. `Clear Pending Speeches`
5. `Quit Codex Speak`

These are context-free local controls: they act on playback and settings
without submitting a prompt, mutating the current conversation, or requiring
an active thread. Quit stops the helper UI; a later hook can start it again
while the plugin remains enabled.

## Privacy and fallback

The final assistant response and user input are never copied into plugin
diagnostics. Speech exists temporarily in a private `0600` queue under
`PLUGIN_DATA`, is claimed and removed before playback, and is discarded when
older than five minutes. Speech reaches `/usr/bin/say` only through standard
input, never process arguments.

Diagnostics contain only timestamps, hashed event identifiers, allowlisted
status/outcome values, counts, duration, and fixed error codes. The menu
helper-state contains only version, PID, boot identity, and monotonic heartbeat.
No component performs network access. Automated privacy canaries cover prompt,
body, summary, code, URL, path, segmented speech, success, failure, and cancel
paths; fake runners ensure tests never produce sound.

The hook passes its active Python executable to the menu helper. If the
embedded helper is absent, cannot be verified, or cannot start, the plugin
uses a detached Python fallback worker to drain queued speech safely. The
fallback preserves speech and diagnostics privacy but has no menu bar UI;
rebuild or reinstall the helper to restore interactive controls.

## Migrate from the legacy plugin

Disable or uninstall `codex-voice-notifier` before enabling Codex Speak so two
plugins do not announce the same turn. Install `codex-speak@personal`, trust
its current hooks in `/hooks`, and start a new thread. Old runtime data is not
imported; mode and queue state begin cleanly under the Codex Speak plugin data
directory.

## Test and validate

From the development checkout:

```bash
cd /Users/howard/plugins/codex-speak
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m compileall -q hooks codex_speak tests
python3 -m json.tool hooks/hooks.json
swift test --package-path menu-bar -Xswiftc -warnings-as-errors
```

The official validator is a maintainer/development check, not a runtime
dependency. It imports PyYAML, so create a disposable environment when the
workspace validator environment is unavailable:

```bash
python3 -m venv /private/tmp/codex-plugin-validator
/private/tmp/codex-plugin-validator/bin/python -m pip install PyYAML
/private/tmp/codex-plugin-validator/bin/python \
  /Users/howard/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py \
  /Users/howard/plugins/codex-speak
```

## Build the universal menu helper

The build performs separate release builds, combines exact `arm64` and
`x86_64` slices, assembles the app, and verifies its local ad hoc signature.
It downloads nothing and writes only `.build`, `assets`, and a temporary
staging directory:

```bash
./scripts/build_menu_app.sh
lipo -archs assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
codesign --verify --deep --strict assets/CodexSpeakMenu.app
```

Commit the rebuilt `assets/CodexSpeakMenu.app` with source changes so local
installs receive the matching helper.

The bundled ad hoc signature is appropriate for local builds, not signed sharing
with other Macs. For distribution, replace it with a Developer ID
Application signature using the hardened runtime and timestamp, archive the
app without altering its contents, submit it to Apple for notarization, staple
the ticket, and verify both Gatekeeper and `codesign` before sharing. Never
describe an ad hoc build as notarized or Developer ID signed.

## Update a local installation

After source or embedded-app changes, refresh the immutable Marketplace
cachebuster with the supported helper and reinstall:

```bash
python3 /Users/howard/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py \
  /Users/howard/plugins/codex-speak
python3 /Users/howard/.codex/skills/.system/plugin-creator/scripts/read_marketplace_name.py
codex plugin add codex-speak@personal
```

Review changed definitions in `/hooks` and start a new thread afterward.

## Troubleshooting

- No speech: confirm `Plugin Toggle` is enabled, then review and trust both
  bundled hooks in `/hooks`.
- No speech in an existing thread: start a new thread so SessionStart injects
  the protocol.
- Menu missing but speech works: the Python fallback is active; rebuild the
  embedded app and reinstall after updating the cachebuster.
- Menu opens but actions fail: verify `python3` is still executable and the
  helper was launched by a current trusted hook so active-Python propagation
  is intact.
- App rejected by macOS: verify its source and signature. Rebuild locally or
  use a properly Developer ID signed and notarized copy.
- Ordinary answers are silent in Summary mode by design; select Full if the
  visible response should be read.
- Concurrent announcements are FIFO and play one at a time; use Clear Pending
  Speeches to discard the queue or Stop Current Speech to cancel playback.
