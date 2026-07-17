# Codex Speak Local Release Workflow

This workflow is for maintainers who serialize a verified development checkout
into a personal marketplace source. Public users should follow the GitHub
marketplace instructions in the repository README.

## Configure portable roots

Run from the accepted development checkout:

```bash
export DEV_PLUGIN_ROOT="$(git rev-parse --show-toplevel)"
export FORMAL_PLUGIN_ROOT="$HOME/plugins/codex-speak"
export PLUGIN_CREATOR_ROOT="${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator"
```

The default personal marketplace file is discovered automatically at
`~/.agents/plugins/marketplace.json` and must already contain the
`codex-speak` entry pointing at `$FORMAL_PLUGIN_ROOT`.

## Synchronize and serialize

```bash
rsync -a --delete \
  --exclude .git --exclude .build --exclude menu-bar/.build \
  --exclude __pycache__ --exclude .superpowers --exclude .worktrees \
  "$DEV_PLUGIN_ROOT/" "$FORMAL_PLUGIN_ROOT/"
python3 "$PLUGIN_CREATOR_ROOT/scripts/update_plugin_cachebuster.py" \
  "$FORMAL_PLUGIN_ROOT"
python3 "$PLUGIN_CREATOR_ROOT/scripts/read_marketplace_name.py"
git -C "$FORMAL_PLUGIN_ROOT" add -A
git -C "$FORMAL_PLUGIN_ROOT" commit -m "chore: refresh codex speak local release"
```

Verify source equality while allowing the serialized manifest version to
differ:

```bash
rsync -ani --delete \
  --exclude .git --exclude .build --exclude menu-bar/.build \
  --exclude __pycache__ --exclude .superpowers --exclude .worktrees \
  --exclude .codex-plugin/plugin.json \
  "$DEV_PLUGIN_ROOT/" "$FORMAL_PLUGIN_ROOT/"
```

## Reinstall

```bash
codex plugin add codex-speak@personal
codex plugin list --marketplace personal --available --json
```

Review and trust changed hook definitions, then start a new task. A running task
retains the absolute hook paths that were bound when it started, so it must not
be used as the acceptance task after a cachebuster reinstall.
