# Codex Speak Menu Bar Poster V2 Design

## Goal

Revise both Codex Speak launch posters so the menu bar helper is a prominent
product advantage alongside the local speech pipeline. The posters must show
that users can change speech mode and control playback without opening a
separate app.

The privacy claim remains scoped to Codex Speak's speech processing, queueing,
and playback pipeline. The design must not imply that the complete Codex
conversation is offline.

## Deliverables

Create two new raster assets without replacing the approved first versions:

1. `assets/posters/codex-speak-github-16x9-v2.png`
2. `assets/posters/codex-speak-xiaohongshu-3x4-v2.png`

Both posters retain the established charcoal, indigo, and violet visual family.
The production logo remains the primary brand mark. A tiny monochrome menu bar
glyph may anchor the menu panel but must read as a functional system control,
not as a second logo.

## Menu Panel

Use one authentic-looking macOS dark menu panel as the second visual focal
point. Reproduce the shipping menu structure rather than inventing a dashboard,
toolbar, or app window.

- Use a single compact rounded panel with native macOS spacing and typography.
- Show a checkmark only beside the default `Summary` or `摘要` mode.
- Keep the exact shipping item order.
- Do not add icons, descriptions, toggles, separators, keyboard shortcuts, or
  status badges that are absent from the actual menu.
- Keep all menu text fully legible at the target channel size.

### English Menu Text

1. `Silent`
2. `Summary` with a checkmark
3. `Full`
4. `Stop Current Speech`
5. `Clear Pending Speeches`
6. `Quit Codex Speak`

### Simplified Chinese Menu Text

1. `静音`
2. `摘要` with a checkmark
3. `全文`
4. `停止当前朗读`
5. `清除待朗读内容`
6. `退出 Codex Speak`

## GitHub Poster

### Layout

- Preserve the 16:9 landscape format and left-aligned editorial copy.
- Keep the privacy headline as the first focal point.
- On the right, form one connected product cluster from the production logo,
  a small menu bar trigger, and the open English menu panel.
- The open menu is the second focal point and must be readable at README width.
- Retain subtle waveform lighting behind the product cluster.

### Exact Copy Outside the Menu

- `CODEX SPEAK`
- `Your Codex speaks. Your voice stays on your Mac.`
- `Switch modes and control playback from the menu bar.`
- `macOS say · No TTS API · No API Key · No Network`
- `Local refers to the Codex Speak speech pipeline.`

The first-version line `Silent · Summary · Full` is removed because the menu
panel now communicates those modes directly.

## Xiaohongshu Poster

### Layout

- Preserve the 3:4 portrait format.
- Keep the production logo and privacy headline in the upper section.
- Place the open Chinese menu panel in the middle as the second focal point.
- Place the local speech proof and privacy qualifier below the menu.
- Maintain phone-feed readability and avoid turning the poster into a dense app
  screenshot.

### Exact Copy Outside the Menu

- `CODEX SPEAK`
- `让 Codex 开口说话`
- `语音完全留在你的 Mac`
- `菜单栏切换模式，随时停止或清除`
- `只用 macOS say`
- `无需 TTS API · 无需 API Key · 不联网`
- `本地仅指 Codex Speak 的语音处理与播放链路`

The first-version line `静音 · 摘要 · 全文` is removed because the menu panel
now communicates those modes directly.

## Generation and Preservation Strategy

- Use the production logo as an identity reference and the approved first
  posters as style and composition references.
- Generate one channel-specific v2 composition per tool call.
- Preserve each first-version PNG unchanged.
- Allow at most one targeted correction per poster, changing only the failed
  text, menu, logo, or hierarchy criterion.

## Acceptance Criteria

- The menu bar capability is immediately visible without displacing the local
  speech privacy message as the primary claim.
- Every menu item matches the shipping localization exactly and appears once.
- `Summary` or `摘要` is the only checked item.
- The panel looks like one macOS menu, not a custom settings app or fake
  dashboard.
- The production speaker-prompt logo remains recognizable and is not
  redesigned.
- The tiny menu bar trigger does not compete with the production logo.
- All outside-menu copy is rendered verbatim with no extra claims.
- The privacy qualifier remains legible and correctly scoped.
- The GitHub and Xiaohongshu posters remain one brand family.
- Both original poster files remain byte-for-byte unchanged.
- No people, unrelated logos, stock imagery, watermark, or decorative clutter
  appears.
