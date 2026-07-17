# Codex Speak Menu Bar Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add English and Simplified Chinese menu bar UI that follows the macOS preferred language and falls back to English.

**Architecture:** Native Localizable.strings files live in en.lproj and zh-Hans.lproj. An injectable MenuLocalization uses Bundle.main in production, while tests select a language bundle explicitly. The existing build script copies both localizations into the signed universal app.

**Tech Stack:** Swift 6, AppKit, Foundation Bundle, XCTest, Python unittest, macOS application bundles.

## Global Constraints

- Support exactly en and zh-Hans; other preferred languages fall back to English.
- Follow macOS automatically; add no language menu or saved preference.
- Apply a system-language change when the helper next starts.
- Keep silent, summary, full, hooks, control output, config, and diagnostics language-neutral.
- Keep Codex Speak untranslated.
- Do not translate speech content or select a voice.
- Preserve macOS 13 and the signed arm64 plus x86_64 app.

---

## File Map

- Create menu-bar/Sources/CodexSpeakMenu/MenuLocalization.swift for keys, fallbacks, lookup, and menu order.
- Create English and Chinese Localizable.strings files under menu-bar/Resources.
- Create menu-bar/Tests/CodexSpeakMenuTests/MenuLocalizationTests.swift.
- Modify MenuController.swift to localize menu titles and transient errors.
- Remove the UI title array and test from CodexSpeakCore.
- Modify scripts/build_menu_app.sh and tests/test_packaging.py for packaging.
- Update README.md and rebuild assets/CodexSpeakMenu.app.

### Task 1: Localization resources and lookup

**Files:**
- Create: menu-bar/Sources/CodexSpeakMenu/MenuLocalization.swift
- Create: menu-bar/Resources/en.lproj/Localizable.strings
- Create: menu-bar/Resources/zh-Hans.lproj/Localizable.strings
- Create: menu-bar/Tests/CodexSpeakMenuTests/MenuLocalizationTests.swift
- Modify: menu-bar/Sources/CodexSpeakCore/PluginEnablement.swift
- Modify: menu-bar/Tests/CodexSpeakCoreTests/MenuConfigurationTests.swift

**Interfaces:**
- Produces MenuLocalization.init(bundle: Bundle = .main).
- Produces MenuLocalization.string(_:) and menuItemTitles.
- Removes codexSpeakMenuItemTitles from CodexSpeakCore.

- [ ] **Step 1: Write the failing localization tests**

Create tests that load a language directory explicitly:

    import Foundation
    import XCTest
    @testable import CodexSpeakMenu

    final class MenuLocalizationTests: XCTestCase {
        func testEnglishAndSimplifiedChineseMenusHaveExactOrder() throws {
            XCTAssertEqual(
                try localization("en").menuItemTitles,
                ["Silent", "Summary", "Full", "Stop Current Speech",
                 "Clear Pending Speeches", "Quit Codex Speak"]
            )
            XCTAssertEqual(
                try localization("zh-Hans").menuItemTitles,
                ["静音", "摘要", "全文", "停止当前朗读",
                 "清除待朗读内容", "退出 Codex Speak"]
            )
        }

        func testEveryKeyResolvesAndEnglishFallbackIsReadable() throws {
            let english = try localization("en")
            let chinese = try localization("zh-Hans")
            let fallback = MenuLocalization(bundle: Bundle(for: Self.self))
            for key in MenuLocalization.Key.allCases {
                XCTAssertNotEqual(english.string(key), key.rawValue)
                XCTAssertNotEqual(chinese.string(key), key.rawValue)
                XCTAssertEqual(fallback.string(key), key.englishFallback)
            }
            XCTAssertEqual(chinese.string(.errorBridgeStopped), "语音桥接已停止")
            XCTAssertEqual(chinese.string(.errorClearFailed), "无法清除待朗读内容")
            XCTAssertEqual(chinese.string(.errorModeWriteFailed), "无法更改朗读模式")
            XCTAssertEqual(chinese.string(.errorModeReadFailed), "无法读取朗读模式")
            XCTAssertEqual(chinese.string(.errorHeartbeatUnavailable), "心跳不可用")
            XCTAssertEqual(chinese.string(.errorPlaybackRecordFailed), "无法记录播放结果")
        }

        private func localization(_ language: String) throws -> MenuLocalization {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("Resources")
                .appendingPathComponent("\(language).lproj")
            return MenuLocalization(bundle: try XCTUnwrap(Bundle(url: url)))
        }
    }

- [ ] **Step 2: Verify RED**

Run:

    swift test --filter MenuLocalizationTests

Expected: compilation fails because MenuLocalization does not exist.

- [ ] **Step 3: Add lookup and resources**

Implement:

    import Foundation

    struct MenuLocalization {
        enum Key: String, CaseIterable {
            case menuModeSilent = "menu.mode.silent"
            case menuModeSummary = "menu.mode.summary"
            case menuModeFull = "menu.mode.full"
            case menuActionStop = "menu.action.stop"
            case menuActionClear = "menu.action.clear"
            case menuActionQuit = "menu.action.quit"
            case errorBridgeStopped = "error.bridge_stopped"
            case errorClearFailed = "error.clear_failed"
            case errorModeWriteFailed = "error.mode_write_failed"
            case errorModeReadFailed = "error.mode_read_failed"
            case errorHeartbeatUnavailable = "error.heartbeat_unavailable"
            case errorPlaybackRecordFailed = "error.playback_record_failed"

            var englishFallback: String {
                switch self {
                case .menuModeSilent: "Silent"
                case .menuModeSummary: "Summary"
                case .menuModeFull: "Full"
                case .menuActionStop: "Stop Current Speech"
                case .menuActionClear: "Clear Pending Speeches"
                case .menuActionQuit: "Quit Codex Speak"
                case .errorBridgeStopped: "Speech bridge stopped"
                case .errorClearFailed: "Could not clear pending speeches"
                case .errorModeWriteFailed: "Could not change speech mode"
                case .errorModeReadFailed: "Could not read speech mode"
                case .errorHeartbeatUnavailable: "Heartbeat unavailable"
                case .errorPlaybackRecordFailed: "Could not record playback result"
                }
            }
        }

        private let bundle: Bundle
        init(bundle: Bundle = .main) { self.bundle = bundle }

        func string(_ key: Key) -> String {
            bundle.localizedString(
                forKey: key.rawValue,
                value: key.englishFallback,
                table: nil
            )
        }

        var menuItemTitles: [String] {
            [.menuModeSilent, .menuModeSummary, .menuModeFull,
             .menuActionStop, .menuActionClear, .menuActionQuit].map(string)
        }
    }

Populate both strings files with the twelve exact design translations. Remove the old core title array and its core-only test.

- [ ] **Step 4: Verify GREEN**

Run:

    swift test --filter MenuLocalizationTests
    swift test --filter MenuConfigurationTests

Expected: zero failures.

- [ ] **Step 5: Commit**

    git add menu-bar/Sources menu-bar/Resources menu-bar/Tests
    git commit -m "feat: add menu bar localization resources"

### Task 2: Localize the controller

**Files:**
- Modify: menu-bar/Sources/CodexSpeakMenu/MenuController.swift
- Modify: tests/test_packaging.py

**Interfaces:**
- Consumes MenuLocalization from Task 1.
- Preserves the six existing actions and SpeechMode mappings.

- [ ] **Step 1: Write a failing source test**

Require let itemTitles = localization.menuItemTitles, all six localization.string error calls, and the absence of direct showLocalError English literals. Update the existing claimed-event regex to expect:

    showLocalError(localization.string(.errorPlaybackRecordFailed))

- [ ] **Step 2: Verify RED**

    PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-localization-pycache \
      python3 -m unittest \
      tests.test_packaging.PackagingTests.test_menu_controller_localizes_every_menu_and_error_string -v

Expected: the controller still contains hard-coded text.

- [ ] **Step 3: Inject and use MenuLocalization**

Add:

    private let localization: MenuLocalization

Add localization: MenuLocalization = MenuLocalization() as the last initializer parameter, assign it before super.init(), and derive:

    let itemTitles = localization.menuItemTitles

Use itemTitles indices 0 through 5 for the existing menu actions. Replace all six error messages with their corresponding localization keys. Leave Codex Speak unchanged for the default tooltip and accessibility description.

- [ ] **Step 4: Verify GREEN**

Run the new Python source test, the claimed-event synchronization test, and MenuLocalizationTests. Expected: zero failures.

- [ ] **Step 5: Commit**

    git add menu-bar/Sources/CodexSpeakMenu/MenuController.swift tests/test_packaging.py
    git commit -m "feat: localize menu bar controls and errors"

### Task 3: Package the localizations

**Files:**
- Modify: tests/test_packaging.py
- Modify: scripts/build_menu_app.sh
- Rebuild: assets/CodexSpeakMenu.app

- [ ] **Step 1: Write a failing packaged-resource test**

For en and zh-Hans, assert that the built app Localizable.strings exists and byte-for-byte matches menu-bar/Resources. Also require the build script to enumerate both languages.

- [ ] **Step 2: Verify RED**

    PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-localization-pycache \
      python3 -m unittest \
      tests.test_packaging.PackagingTests.test_embedded_helper_contains_exact_menu_localizations -v

Expected: the current app has no lproj resource directories.

- [ ] **Step 3: Copy resources while staging**

After copying AppIcon.icns, add:

    for localization in en zh-Hans; do
        source="$PACKAGE/Resources/$localization.lproj/Localizable.strings"
        destination="$STAGED_APP/Contents/Resources/$localization.lproj"
        mkdir -p "$destination"
        cp "$source" "$destination/Localizable.strings"
    done

- [ ] **Step 4: Rebuild and verify**

    ./scripts/build_menu_app.sh

Then run the packaged-resource, universal-binary, and signing tests. Expected: exact resources, arm64 plus x86_64, and valid strict signing.

- [ ] **Step 5: Commit**

    git add scripts/build_menu_app.sh tests/test_packaging.py assets/CodexSpeakMenu.app
    git commit -m "build: package menu bar localizations"

### Task 4: Documentation and full gates

**Files:**
- Modify: README.md
- Modify: tests/test_packaging.py
- Modify: docs/superpowers/specs/2026-07-17-menu-bar-localization-design.md

- [ ] **Step 1: Write a failing README assertion**

Require:

    The menu bar follows your macOS preferred language and supports English and Simplified Chinese.

- [ ] **Step 2: Verify RED**

Run the focused README packaging test. Expected: the sentence is absent.

- [ ] **Step 3: Update documentation**

Add the sentence beside the menu description. Change the design status to Implemented. Do not change the marketplace ref, plugin version, tag, or release commands.

- [ ] **Step 4: Run full gates**

    PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-localization-pycache \
      python3 -m unittest discover -s tests -v
    cd menu-bar
    swift test -Xswiftc -warnings-as-errors
    cd ..
    /private/tmp/codex-plugin-validator/bin/python \
      /Users/howard/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
    lipo -archs assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
    codesign --verify --deep --strict assets/CodexSpeakMenu.app
    git diff --check

Expected: all tests and validator pass, the binary is universal, signing is valid, and diff check is empty.

- [ ] **Step 5: Commit**

    git add README.md tests/test_packaging.py \
      docs/superpowers/specs/2026-07-17-menu-bar-localization-design.md
    git commit -m "docs: describe system language support"

- [ ] **Step 6: Confirm scope**

    git status --short --branch
    git log -6 --oneline

Expected: clean local main ahead of origin/main. No push, version bump, tag, release, or installation occurs without separate authorization.

