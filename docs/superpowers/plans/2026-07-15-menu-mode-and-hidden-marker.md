# Codex Speak Menu Mode and Hidden Marker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Codex Speak 0.2.1 with menu checkmarks refreshed on menu open and an invisible CommonMark v2 control marker for new tasks.

**Architecture:** Keep `settings.json` as the sole mode source and refresh it through the existing `ControlClient` from `NSMenuDelegate.menuWillOpen`. Add a strict v2 trailing-reference parser while temporarily accepting the current v1 HTML comment, then update SessionStart to emit only v2.

**Tech Stack:** Python 3.10+ standard library, Swift 6/AppKit, unittest, XCTest, Swift Package Manager, Codex lifecycle hooks, personal Marketplace.

## Global Constraints

- Do not change queue, speech playback, diagnostics privacy, helper ownership, or fallback semantics.
- New tasks emit exactly one trailing `codex-speak:v2` reference definition.
- Version 2 preserves the exact payload keys, statuses, summary rules, and 280-character hard limit.
- Version 2 rejects unsafe angle brackets, line breaks, duplicates, mixed markers, non-trailing markers, malformed payloads, and unknown versions.
- Version 1 is accepted only as a transition path for already-running tasks; `codex-voice-notifier` remains rejected.
- The release version is `0.2.1` before the Marketplace cachebuster is refreshed.
- The embedded helper remains universal `x86_64 arm64` and locally ad hoc signed.

---

## File map

- `tests/test_protocol.py` — v2 and transition parser regression coverage.
- `tests/test_hooks.py` — SessionStart v2 instruction contract.
- `codex_speak/protocol.py` — strict v1/v2 extraction and summary sanitization.
- `hooks/session_start.py` — v2-only instructions for new tasks.
- `tests/test_packaging.py` — menu-open refresh source contract and version assertion.
- `menu-bar/Sources/CodexSpeakMenu/MenuController.swift` — `NSMenuDelegate` refresh behavior.
- `.codex-plugin/plugin.json` — base release version `0.2.1`.
- `README.md` — hidden-marker migration and new-task acceptance note.

### Task 1: Add the hidden v2 marker with v1 transition parsing

**Files:**
- Modify: `tests/test_protocol.py`
- Modify: `tests/test_hooks.py`
- Modify: `codex_speak/protocol.py`
- Modify: `hooks/session_start.py`

**Interfaces:**
- Consumes: `extract_response(message: str | None) -> ParsedResponse | None`.
- Produces: the same public parser interface accepting one trailing v2 reference or transitional v1 comment.

- [ ] **Step 1: Write failing protocol and SessionStart tests**

Add a v2 helper and tests that require extraction, body stripping, v1 compatibility, and mixed/duplicate/unsafe rejection:

```python
def marker_v2(status: str, text: str) -> str:
    payload = json.dumps(
        {"status": status, "speech_text": text},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"[codex-speak-v2]: <codex-speak:v2#{payload}>"

def test_extracts_hidden_v2_marker_and_keeps_v1_transition(self) -> None:
    self.assertEqual(
        extract_response("正文\n\n" + marker_v2("completed", "完成。")),
        ParsedResponse("completed", "完成。", "正文"),
    )
    self.assertEqual(
        extract_response(marker("completed", "完成。")),
        ParsedResponse("completed", "完成。", ""),
    )

def test_rejects_mixed_duplicate_non_trailing_and_unsafe_v2(self) -> None:
    v2 = marker_v2("completed", "完成。")
    self.assertIsNone(extract_response(v2 + "\n" + marker("completed", "完成。")))
    self.assertIsNone(extract_response(v2 + "\n" + v2))
    self.assertIsNone(extract_response(v2 + " trailing"))
    self.assertIsNone(extract_response(marker_v2("completed", "包含>符号")))
```

Update `test_session_start_injects_protocol_as_developer_context` to require `[codex-speak-v2]`, `codex-speak:v2#`, and `CommonMark reference definition`, and to reject the instruction phrase `append exactly one single-line HTML comment`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_protocol tests.test_hooks -v
```

Expected: FAIL because v2 is not parsed and SessionStart still instructs v1 HTML comments.

- [ ] **Step 3: Implement the minimal v1/v2 parser and v2 instructions**

In `protocol.py`, keep the v1 regex and add:

```python
_V2_MARKER_RE = re.compile(
    r"(?:\A|\n)\[codex-speak-v2\]: <codex-speak:v2#(?P<payload>\{[^\r\n]*\})>\s*\Z"
)
```

Refactor `extract_response` to collect matches from both regexes, require exactly one total match, reject any earlier `codex-speak:v1` or `[codex-speak-v2]`, reject `<` or `>` inside a v2 payload, parse with `_parse_exact_payload`, and strip the matched line from `visible_body`.

In `session_start.py`, replace the marker instruction with:

```text
Codex Speak is active. For every final response, append exactly one unused CommonMark reference definition as the final non-whitespace line:
[codex-speak-v2]: <codex-speak:v2#{"status":"STATUS","speech_text":"TEXT"}>
```

Also state that `TEXT` must not contain `<`, `>`, line breaks, or controls and that the reference definition must not be mentioned in the visible answer.

- [ ] **Step 4: Run focused and full Python tests**

Run:

```bash
python3 -m unittest tests.test_protocol tests.test_hooks -v
python3 -m unittest discover -s tests -v
```

Expected: all tests pass with no failures.

- [ ] **Step 5: Commit**

```bash
git add tests/test_protocol.py tests/test_hooks.py codex_speak/protocol.py hooks/session_start.py
git commit -m "fix: hide speech protocol marker in new tasks"
```

### Task 2: Refresh menu mode whenever the menu opens

**Files:**
- Modify: `tests/test_packaging.py`
- Modify: `menu-bar/Sources/CodexSpeakMenu/MenuController.swift`

**Interfaces:**
- Consumes: existing `ControlClientProtocol.getMode() -> SpeechMode` and `refreshMode()`.
- Produces: `MenuController.menuWillOpen(_:)` as the menu-open synchronization boundary.

- [ ] **Step 1: Write the failing source-contract test**

Add:

```python
def test_menu_refreshes_persisted_mode_when_opened(self) -> None:
    source = (
        ROOT / "menu-bar" / "Sources" / "CodexSpeakMenu" / "MenuController.swift"
    ).read_text(encoding="utf-8")
    self.assertIn("NSObject, NSMenuDelegate", source)
    self.assertIn("menu.delegate = self", source)
    self.assertRegex(
        source,
        r"func menuWillOpen\(_ menu: NSMenu\)\s*\{\s*refreshMode\(\)\s*\}",
    )
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m unittest tests.test_packaging.PackagingTests.test_menu_refreshes_persisted_mode_when_opened -v
```

Expected: FAIL because `MenuController` is not an `NSMenuDelegate` and has no menu-open refresh.

- [ ] **Step 3: Implement the minimal AppKit change**

Change the declaration and menu setup, then add the delegate callback:

```swift
final class MenuController: NSObject, NSMenuDelegate {
    // existing members

    // after super.init()
    menu.delegate = self

    func menuWillOpen(_ menu: NSMenu) {
        refreshMode()
    }
}
```

Do not add timers, file watchers, or new settings state.

- [ ] **Step 4: Run focused tests and Swift tests**

Run:

```bash
python3 -m unittest tests.test_packaging.PackagingTests.test_menu_refreshes_persisted_mode_when_opened -v
CODEX_SPEAK_TEST_PYTHON=/Users/howard/opt/miniconda3/bin/python3 \
  swift test --package-path menu-bar -Xswiftc -warnings-as-errors
```

Expected: packaging test passes and all 36 Swift tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_packaging.py menu-bar/Sources/CodexSpeakMenu/MenuController.swift
git commit -m "fix: refresh speech mode when menu opens"
```

### Task 3: Prepare the 0.2.1 release tree

**Files:**
- Modify: `tests/test_packaging.py`
- Modify: `.codex-plugin/plugin.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: completed v2 protocol and menu refresh.
- Produces: a validator-clean development tree with base version `0.2.1`.

- [ ] **Step 1: Add a failing version assertion**

In the existing manifest identity test add:

```python
self.assertEqual(manifest["version"], "0.2.1")
```

- [ ] **Step 2: Run the assertion and verify RED**

Run:

```bash
python3 -m unittest tests.test_packaging.PackagingTests.test_manifest_has_exact_identity_and_only_supported_fields -v
```

Expected: FAIL with current version `0.2.0`.

- [ ] **Step 3: Bump the manifest and document migration**

Set `.codex-plugin/plugin.json` version to `0.2.1`. Update README troubleshooting and migration text to state that new tasks use an invisible v2 reference, current tasks may continue showing the v1 comment until replaced, and mode checkmarks refresh when the menu opens.

- [ ] **Step 4: Run full development verification**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m compileall -q hooks codex_speak tests
python3 -m json.tool hooks/hooks.json
CODEX_SPEAK_TEST_PYTHON=/Users/howard/opt/miniconda3/bin/python3 \
  swift test --package-path menu-bar -Xswiftc -warnings-as-errors
/private/tmp/codex-plugin-validator/bin/python \
  /Users/howard/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

Expected: zero failures and plugin validation passes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_packaging.py .codex-plugin/plugin.json README.md
git commit -m "chore: prepare codex speak 0.2.1"
```

### Task 4: Build, deploy, reinstall, and verify

**Files:**
- Rebuild: `assets/CodexSpeakMenu.app`
- Synchronize: `/Users/howard/plugins/codex-speak`
- Refresh: `/Users/howard/plugins/codex-speak/.codex-plugin/plugin.json`
- Update: `/Users/howard/workspace/my-ai-workspace/.superpowers/codex-speak/task-9-acceptance.md`

**Interfaces:**
- Consumes: verified development tree at version `0.2.1`.
- Produces: one installed and enabled `codex-speak@personal` cachebuster release.

- [ ] **Step 1: Build and verify the universal helper**

```bash
./scripts/build_menu_app.sh
lipo -archs assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
codesign --verify --deep --strict assets/CodexSpeakMenu.app
```

Expected: `x86_64 arm64` and strict signature verification succeeds.

- [ ] **Step 2: Rerun packaging and full tests after embedding**

```bash
python3 -m unittest discover -s tests -v
CODEX_SPEAK_TEST_PYTHON=/Users/howard/opt/miniconda3/bin/python3 \
  swift test --package-path menu-bar -Xswiftc -warnings-as-errors
```

Expected: zero failures.

- [ ] **Step 3: Commit the embedded helper**

```bash
git add assets/CodexSpeakMenu.app
git commit -m "build: embed codex speak 0.2.1 menu helper"
```

- [ ] **Step 4: Synchronize to the formal source and refresh the cachebuster**

Preserve the formal repository history while synchronizing accepted runtime files, then refresh and commit the serialized version:

```bash
rsync -a --delete \
  --exclude .git --exclude .build --exclude menu-bar/.build --exclude __pycache__ \
  /Users/howard/workspace/my-ai-workspace/plugins/codex-speak/ \
  /Users/howard/plugins/codex-speak/
python3 /Users/howard/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py \
  /Users/howard/plugins/codex-speak
python3 /Users/howard/.codex/skills/.system/plugin-creator/scripts/read_marketplace_name.py
git -C /Users/howard/plugins/codex-speak add -A
git -C /Users/howard/plugins/codex-speak commit -m "chore: release codex speak 0.2.1"
```

Expected: formal version begins with `0.2.1+codex.` and marketplace is `personal`.

- [ ] **Step 5: Reinstall and inspect state**

```bash
codex plugin add codex-speak@personal --json
codex plugin list --marketplace personal --available --json
```

Expected: exactly one installed and enabled Codex Speak at the new `0.2.1+codex.` version; legacy remains not installed.

- [ ] **Step 6: Final verification and acceptance handoff**

Verify formal source/cache equality excluding `.git`, check helper architecture/signature, confirm hooks require review if their definitions changed, and update the metadata-only acceptance file. Start a new Codex task, trust the new hooks, and verify the menu-open refresh and invisible v2 marker before marking Task 9 complete.
