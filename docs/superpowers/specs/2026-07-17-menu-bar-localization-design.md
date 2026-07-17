# Codex Speak Menu Bar Localization Design

Date: 2026-07-17
Status: Confirmed in conversation; awaiting written-spec review

## Goal

Localize the Codex Speak menu bar interface in English and Simplified Chinese. The app follows the macOS preferred language automatically and falls back to English. No in-app language preference is added.

This change localizes the menu bar interface only. It does not translate spoken Codex output, choose a speech voice, or change the plugin protocol.

## User Experience

- English resources use the `en` localization.
- Simplified Chinese resources use the `zh-Hans` localization.
- macOS selects the localization when Codex Speak starts.
- A system-language change takes effect the next time the menu bar helper starts.
- If the preferred language is unavailable, the existing English development region remains the fallback.

The six menu items are translated as follows:

| Key | English | Simplified Chinese |
| --- | --- | --- |
| `menu.mode.silent` | Silent | 静音 |
| `menu.mode.summary` | Summary | 摘要 |
| `menu.mode.full` | Full | 全文 |
| `menu.action.stop` | Stop Current Speech | 停止当前朗读 |
| `menu.action.clear` | Clear Pending Speeches | 清除待朗读内容 |
| `menu.action.quit` | Quit Codex Speak | 退出 Codex Speak |

Transient status-button tooltips are localized as well:

| Key | English | Simplified Chinese |
| --- | --- | --- |
| `error.bridge_stopped` | Speech bridge stopped | 语音桥接已停止 |
| `error.clear_failed` | Could not clear pending speeches | 无法清除待朗读内容 |
| `error.mode_write_failed` | Could not change speech mode | 无法更改朗读模式 |
| `error.mode_read_failed` | Could not read speech mode | 无法读取朗读模式 |
| `error.heartbeat_unavailable` | Heartbeat unavailable | 心跳不可用 |
| `error.playback_record_failed` | Could not record playback result | 无法记录播放结果 |

`Codex Speak` remains an untranslated product name for the default tooltip, accessibility description, and bundle display name.

## Architecture

Add standard application localization resources at:

- `menu-bar/Resources/en.lproj/Localizable.strings`
- `menu-bar/Resources/zh-Hans.lproj/Localizable.strings`

A small `MenuLocalization` value in the `CodexSpeakMenu` target resolves keys from an injected `Bundle`. Production uses `Bundle.main`; tests use an explicitly selected language bundle so results do not depend on the developer machine's language.

`MenuController` requests named menu and error strings from this localization boundary. The existing UI title array is removed from `CodexSpeakCore`, because core speech/configuration behavior must not depend on a display language.

The raw values `silent`, `summary`, and `full`, hook messages, control output, configuration values, and diagnostic identifiers remain unchanged and language-neutral.

## Packaging

The menu app build script copies both `.lproj` directories into `CodexSpeakMenu.app/Contents/Resources` before signing. The existing `CFBundleDevelopmentRegion` remains `en`.

The packaged app must continue to be a signed universal `arm64` and `x86_64` application. No user preference or additional runtime file is introduced.

## Error Handling

Every lookup supplies its English text as a safe fallback. A missing or malformed localized entry therefore displays readable English rather than a localization key. Runtime failures continue to use the existing two-second tooltip behavior and do not expose raw errors.

## Verification

- Unit tests load the English and Simplified Chinese bundles explicitly and verify every required key and exact translation.
- Menu tests verify the six-item order in both languages and keep mode actions mapped to the same `SpeechMode` values.
- Packaging tests verify both localization directories and their strings files are present in the built app.
- The full Python and Swift test suites, plugin validator, universal-binary check, and code-signing verification remain release gates.

## Out of Scope

- A manual language submenu or saved language preference.
- Traditional Chinese or other additional localizations.
- Translating speech content or forcing a language-specific macOS voice.
- Localizing command-line-only usage and diagnostic identifiers.
