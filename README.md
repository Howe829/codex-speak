# Codex Speak

Codex Speak is a macOS Codex Plugin that speaks important turn
outcomes with the system `say` command. It announces completed work, blocked
work, and tasks that require user action. Ordinary answers remain silent.

## Requirements

- macOS
- Python 3.10 or newer available as `python3`
- Codex with Plugin lifecycle-hook support

The plugin uses no network service, API key, third-party Python package,
custom voice, or global Codex `notify` setting.

## Install from the personal Marketplace

This development checkout uses `/Users/howard/plugins/codex-speak`
as its local source and `/Users/howard/.agents/plugins/marketplace.json` as the
default personal Marketplace.

```bash
codex plugin add codex-speak@personal
```

After installation, open `/hooks` in Codex, review the `SessionStart` and
`Stop` commands, and trust the current hook definitions. Changed hook
definitions require review again.

Start a new thread after installation or reinstall so Codex loads the
SessionStart protocol context.

## Behavior

- `completed`: speaks the result and the next recommended step.
- `blocked`: speaks the blocker and the next required step.
- `action_required`: speaks the action or decision needed from the user.
- `silent`: does not speak ordinary answers, routine clarification, casual
  conversation, progress updates, or optional follow-up invitations.

Important announcements track the active primary instruction in the
conversation. Internal commands, temporary files, tests, test fixtures,
validation artifacts, and tool mechanics stay unspoken process details unless
the user explicitly requested them. Each announcement states the requested
outcome first and then the real next step, or that no follow-up is needed.

Language, salutation, and tone come from the active Codex context, including
applicable `AGENTS.md`, memory, and conversation preferences. The plugin does not hard-code a user's name.

The first release uses the current macOS default voice and rate. Disable the
plugin when speech is not wanted.

## Privacy

The final assistant response and user input are not written to plugin
diagnostics. Speech text exists temporarily in a private `0600` queue file
under `PLUGIN_DATA`, is removed before `/usr/bin/say` starts, and is discarded
rather than spoken when older than five minutes or when the worker cannot
start. The worker feeds speech through standard input, so it does not appear
in the `say` process arguments.

Diagnostics contain only timestamps, hashed event identifiers, status,
outcome, duration, and fixed error codes. No component performs network
access.

## Test

The plugin and its automated tests use only the Python standard library:

```bash
cd /Users/howard/plugins/codex-speak
python3 -m unittest discover -s tests -v
```

Automated tests use fake speech runners and do not make sound.

The official plugin validator is a maintainer/development check, not a plugin
runtime dependency. The validator itself imports PyYAML. Run it reproducibly
in a disposable virtual environment outside the repository:

```bash
python3 -m venv /private/tmp/codex-plugin-validator
/private/tmp/codex-plugin-validator/bin/python -m pip install PyYAML
/private/tmp/codex-plugin-validator/bin/python \
  /Users/howard/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py \
  /Users/howard/plugins/codex-speak
```

## Update a local installation

After changing the plugin, refresh its cachebuster and reinstall it from the
existing personal Marketplace entry:

```bash
python3 /Users/howard/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py \
  /Users/howard/plugins/codex-speak
python3 /Users/howard/.codex/skills/.system/plugin-creator/scripts/read_marketplace_name.py
codex plugin add codex-speak@personal
```

Then review changed hooks with `/hooks` and test in a new thread.

## Troubleshooting

- No speech: confirm the plugin is enabled, open `/hooks`, and trust both
  bundled hooks.
- No speech in an existing thread: start a new thread so SessionStart injects
  the protocol.
- Still silent: verify `python3 --version` is 3.10 or newer and
  `/usr/bin/say` exists.
- Ordinary answers are silent by design.
- Concurrent announcements wait in a local FIFO queue and play one at a time.
