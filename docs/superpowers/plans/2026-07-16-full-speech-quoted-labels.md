# Codex Speak Full Speech Quoted Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Codex Speak `0.2.2` so Full mode speaks text inside double quotes and preserves short prose labels such as `` `Full` `` while continuing to redact code-shaped inline spans.

**Architecture:** Keep the change inside `codex_speak.render.normalize_full_text`. Remove double-quote delimiters before playback, then classify single-backtick spans with one small syntax-based helper; all existing queue, bridge, Swift playback, diagnostics, and heartbeat interfaces remain unchanged.

**Tech Stack:** Python 3 standard library, `unittest`, Swift 6/XCTest for unchanged integration verification, Codex plugin validator, macOS `/usr/bin/say`.

## Global Constraints

- Release version is exactly `0.2.2`; the formal Marketplace cachebuster begins with `0.2.2+codex.`.
- Double-quote delimiters are `"`, `“`, `”`, `„`, `‟`, and `＂`; their enclosed text remains intact.
- Single quotes and apostrophes remain unchanged.
- A spoken inline label has 1 through 32 trimmed Unicode characters, each a letter, number, whitespace, or ASCII hyphen; underscores remain code-shaped.
- Multi-backtick spans and ambiguous or code-shaped single-backtick spans remain `代码`.
- Do not change Summary semantics, queue formats, bridge events, Swift playback, menu behavior, diagnostics, runtime permissions, helper packaging, or any heartbeat behavior.
- Do not rebuild `assets/CodexSpeakMenu.app`; verify that its checksum remains unchanged.

---

### Task 1: Preserve double-quoted speech content

**Files:**
- Modify: `tests/test_render.py:65-69`
- Modify: `codex_speak/render.py:35-87`

**Interfaces:**
- Consumes: `normalize_full_text(value: str) -> str`.
- Produces: the same function signature, with double-quote delimiters removed and their content preserved.

- [ ] **Step 1: Write the failing quote-normalization tests**

Add these methods to `RenderTests` after `test_normalizes_images_urls_tables_emphasis_and_controls`:

```python
    def test_removes_double_quote_delimiters_without_dropping_content(self) -> None:
        body = "新增内部心跳，watchdog 现在能区分“现场断流”和“转写进程卡死”。"
        self.assertEqual(
            normalize_full_text(body),
            "新增内部心跳，watchdog 现在能区分现场断流和转写进程卡死。",
        )

    def test_removes_supported_double_quotes_but_keeps_single_quotes(self) -> None:
        cases = {
            '前文 "ASCII label" 后文': "前文 ASCII label 后文",
            "前文 „low quote‟ 后文": "前文 low quote 后文",
            "前文 ＂全角内容＂ 后文": "前文 全角内容 后文",
            "前文 'single quote' 后文": "前文 'single quote' 后文",
            "前文 “unbalanced 后文": "前文 unbalanced 后文",
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertEqual(normalize_full_text(body), expected)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest \
  tests.test_render.RenderTests.test_removes_double_quote_delimiters_without_dropping_content \
  tests.test_render.RenderTests.test_removes_supported_double_quotes_but_keeps_single_quotes -v
```

Expected: both tests fail because the current output still contains double-quote delimiters.

- [ ] **Step 3: Implement delimiter-only normalization**

Add this constant after `_SENTENCE_ENDINGS` in `codex_speak/render.py`:

```python
_DOUBLE_QUOTE_TRANSLATION: Final[dict[int, None]] = str.maketrans(
    "", "", '\"“”„‟＂'
)
```

In `normalize_full_text`, immediately after `_replace_fenced_code`, add:

```python
    text = text.translate(_DOUBLE_QUOTE_TRANSLATION)
```

- [ ] **Step 4: Run focused and renderer tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_render -v
```

Expected: all renderer tests pass with no errors or warnings.

- [ ] **Step 5: Commit the quote fix**

```bash
git add codex_speak/render.py tests/test_render.py
git commit -m "fix: preserve quoted full speech content"
```

### Task 2: Speak short backtick labels without exposing code

**Files:**
- Modify: `tests/test_render.py:90-93`
- Modify: `codex_speak/render.py:19-21,35-87`

**Interfaces:**
- Consumes: `_INLINE_CODE_RE` matches named groups `ticks` and `content`.
- Produces: `_replace_inline_code(match: re.Match[str]) -> str`, returning a trimmed label or `代码`.

- [ ] **Step 1: Write failing label and code-classification tests**

Add these methods after `test_normalizes_matching_multi_backtick_inline_code`:

```python
    def test_preserves_short_prose_labels_in_single_backticks(self) -> None:
        body = "模式为 `Full`、`Summary`、`codex-speak`、`语音模式` 和 `two words`。"
        self.assertEqual(
            normalize_full_text(body),
            "模式为 Full、Summary、codex-speak、语音模式 和 two words。",
        )

    def test_replaces_code_shaped_and_ambiguous_inline_spans(self) -> None:
        cases = (
            "`x=1`",
            "`run()`",
            "`~/secret`",
            "`a | b`",
            "`" + "a" * 33 + "`",
            "``plain label``",
        )
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(normalize_full_text(body), "代码")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest \
  tests.test_render.RenderTests.test_preserves_short_prose_labels_in_single_backticks \
  tests.test_render.RenderTests.test_replaces_code_shaped_and_ambiguous_inline_spans -v
```

Expected: the label test fails because every span becomes `代码`; the code-shaped cases continue to pass.

- [ ] **Step 3: Capture inline content and add the classifier**

Replace `_INLINE_CODE_RE` with:

```python
_INLINE_CODE_RE = re.compile(
    r"(?<!`)(?P<ticks>`+)(?!`)(?P<content>[^\r\n]*?)(?<!`)(?P=ticks)(?!`)"
)
```

Add after `_replace_fenced_code`:

```python
def _replace_inline_code(match: re.Match[str]) -> str:
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
    return content if is_label else "代码"
```

Replace the current inline substitution with:

```python
    text = _INLINE_CODE_RE.sub(_replace_inline_code, text)
```

- [ ] **Step 4: Run focused, renderer, hooks, and privacy tests**

Run:

```bash
python3 -m unittest tests.test_render tests.test_hooks tests.test_privacy -v
```

Expected: all tests pass; privacy canaries containing code syntax remain absent from normalized speech.

- [ ] **Step 5: Commit the inline-label fix**

```bash
git add codex_speak/render.py tests/test_render.py
git commit -m "fix: speak short full mode labels"
```

### Task 3: Prepare and verify release 0.2.2

**Files:**
- Modify: `tests/test_packaging.py:103-109`
- Modify: `.codex-plugin/plugin.json:3`
- Modify: `README.md:42-45,189-190`
- Verify unchanged: `assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu`

**Interfaces:**
- Consumes: accepted renderer behavior from Tasks 1 and 2.
- Produces: development plugin version `0.2.2` with documented Full normalization behavior and a fully verified unchanged helper.

- [ ] **Step 1: Change the packaging assertion and verify RED**

Change the version assertion in `tests/test_packaging.py` to:

```python
        self.assertEqual(manifest["version"], "0.2.2")
```

Run:

```bash
python3 -m unittest \
  tests.test_packaging.PackagingTests.test_manifest_has_exact_identity_and_only_supported_fields -v
```

Expected: FAIL showing manifest version `0.2.1` instead of `0.2.2`.

- [ ] **Step 2: Bump the manifest and document the behavior**

Change `.codex-plugin/plugin.json` to:

```json
  "version": "0.2.2",
```

Expand the Full-mode paragraph in `README.md` to state:

```markdown
- `Full` reads the normalized visible response. Markdown formatting, code,
  URLs, and local paths are replaced with speech-safe descriptions. Double-
  quote delimiters are removed so macOS speaks their enclosed text, and short
  prose labels in single backticks are spoken as visible text while code-shaped
  spans retain the `代码` placeholder.
```

Add this troubleshooting item after the Summary-mode item:

```markdown
- Quoted text or a short backtick label is skipped in Full mode: confirm the
  installed plugin version begins with `0.2.2+codex.` and reinstall it if not.
```

- [ ] **Step 3: Run the complete development verification**

Record the helper checksum before and after verification:

```bash
shasum -a 256 assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
```

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-0.2.2-pycache \
  python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-0.2.2-pycache \
  python3 -m compileall -q hooks codex_speak tests
python3 -m json.tool hooks/hooks.json >/dev/null
CODEX_SPEAK_TEST_PYTHON=/Users/howard/opt/miniconda3/bin/python3 \
  swift test --package-path menu-bar -Xswiftc -warnings-as-errors
/private/tmp/codex-plugin-validator/bin/python \
  /Users/howard/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
lipo -archs assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
codesign --verify --deep --strict assets/CodexSpeakMenu.app
git diff --check
```

Expected: zero Python and Swift failures; compile, JSON, validator, and signing checks exit zero; helper architectures are exactly `x86_64 arm64`; final helper checksum equals the initial checksum.

- [ ] **Step 4: Run the macOS quoted-speech smoke**

Generate speech from the normalized original sentence and inspect it:

```bash
python3 -c 'from codex_speak.render import normalize_full_text; print(normalize_full_text("新增内部心跳，watchdog 现在能区分“现场断流”和“转写进程卡死”。"))' \
  | /usr/bin/say -o /private/tmp/codex-speak-0.2.2-quoted.aiff
/usr/bin/afinfo /private/tmp/codex-speak-0.2.2-quoted.aiff
```

Expected: normalized input contains both `现场断流` and `转写进程卡死` without quote delimiters; synthesized audio has non-zero audio bytes and duration comparable to the previously measured unquoted sentence, approximately 5.9 seconds with the current system voice.

- [ ] **Step 5: Commit release preparation**

```bash
git add .codex-plugin/plugin.json README.md tests/test_packaging.py
git commit -m "chore: prepare codex speak 0.2.2"
git status --short --branch
```

Expected: development repository is clean on `main`.

### Task 4: Deploy, reinstall, and perform live acceptance

**Files:**
- Synchronize: `/Users/howard/plugins/codex-speak`
- Refresh: `/Users/howard/plugins/codex-speak/.codex-plugin/plugin.json`

**Interfaces:**
- Consumes: clean, verified development plugin `0.2.2`.
- Produces: one installed and enabled `codex-speak@personal` cachebuster release with live speech acceptance recorded.

- [ ] **Step 1: Synchronize the accepted development source**

After receiving approval to write the formal source, run:

```bash
rsync -a --delete \
  --exclude .git --exclude .build --exclude menu-bar/.build --exclude __pycache__ \
  /Users/howard/workspace/my-ai-workspace/plugins/codex-speak/ \
  /Users/howard/plugins/codex-speak/
python3 /Users/howard/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py \
  /Users/howard/plugins/codex-speak
python3 /Users/howard/.codex/skills/.system/plugin-creator/scripts/read_marketplace_name.py
git -C /Users/howard/plugins/codex-speak add -A
git -C /Users/howard/plugins/codex-speak commit -m "chore: release codex speak 0.2.2"
```

Expected: marketplace name is `personal`; formal manifest version begins with `0.2.2+codex.`; formal repository is clean after commit.

- [ ] **Step 2: Verify source equality and unchanged helper**

Run:

```bash
rsync -ani --delete \
  --exclude .git --exclude .build --exclude menu-bar/.build --exclude __pycache__ \
  --exclude .codex-plugin/plugin.json \
  /Users/howard/workspace/my-ai-workspace/plugins/codex-speak/ \
  /Users/howard/plugins/codex-speak/
shasum -a 256 \
  /Users/howard/workspace/my-ai-workspace/plugins/codex-speak/assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu \
  /Users/howard/plugins/codex-speak/assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
```

Expected: rsync dry run prints no changes; both helper checksums are identical.

- [ ] **Step 3: Reinstall and inspect plugin state**

Run:

```bash
codex plugin add codex-speak@personal --json
codex plugin list --marketplace personal --available --json
```

Expected: exactly one installed and enabled `codex-speak@personal` version beginning with `0.2.2+codex.`; `codex-voice-notifier@personal` remains not installed and disabled.

- [ ] **Step 4: Perform user-audible acceptance**

Select Full mode and produce one response containing this exact visible sentence:

```text
新增内部心跳，watchdog 现在能区分“现场断流”和“转写进程卡死”，当前模式是 `Full`。
```

Expected: speech includes `现场断流`, `转写进程卡死`, and `Full`; it does not say `代码`; playback occurs once and no response text appears in diagnostics.

- [ ] **Step 5: Verify final repository state**

Run:

```bash
git status --short --branch
git -C /Users/howard/plugins/codex-speak status --short --branch
```

Expected: both repositories are clean. Report the installed `0.2.2+codex.`
version, automated test counts, quoted-speech smoke duration, and the user's
audible acceptance result in the completion handoff.
