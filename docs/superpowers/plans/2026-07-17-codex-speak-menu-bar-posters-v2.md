# Codex Speak Menu Bar Posters V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate GitHub and Xiaohongshu v2 launch posters that make the shipping macOS menu bar mode and playback controls immediately visible while preserving the accurate local-speech privacy claim.

**Architecture:** Use the built-in Image Gen tool once per channel-specific composition. Treat the production logo as the identity reference and each approved v1 poster as the channel-specific style reference, then save selected outputs as new v2 PNGs so the original assets remain unchanged.

**Tech Stack:** Built-in Image Gen, Codex image inspection, PNG assets, macOS `file`, `sips`, and `shasum` validation.

## Global Constraints

- Preserve `assets/posters/codex-speak-github-16x9.png` with SHA-256 `fbc6c5401ac23262fc4c397dbd8cb2ba1bbee31c2d6c5a0b299a0e1448340bb0`.
- Preserve `assets/posters/codex-speak-xiaohongshu-3x4.png` with SHA-256 `fc6afdc54972f8c58467714e9bb07e4923782518ad2f4614e63e83854e8d9141`.
- Preserve the production logo's rounded-square silhouette, white speaker, embedded `>_` prompt, indigo-to-violet palette, and proportions.
- Make the local speech privacy statement the primary claim and the menu panel the second focal point.
- Scope local privacy only to Codex Speak's speech processing, queueing, and playback pipeline.
- Use a single authentic-looking macOS menu with the exact shipping order and localization.
- Check only `Summary` or `摘要`; add no icons, descriptions, toggles, separators, shortcuts, or badges inside the menu.
- Do not overwrite either v1 poster.
- No people, unrelated logos, stock imagery, watermark, decorative 3D clutter, fake dashboard, or additional copy.
- Allow at most one targeted Image Gen correction per poster.

---

### Task 1: GitHub Landscape V2

**Files:**
- Reference: `assets/codex-speak-github.png`
- Reference: `assets/posters/codex-speak-github-16x9.png`
- Create: `assets/posters/codex-speak-github-16x9-v2.png`

**Interfaces:**
- Consumes: the production logo for identity and the approved GitHub v1 poster for palette, lighting, typography, and channel composition.
- Produces: a standalone 16:9 English v2 poster with an authentic menu panel.

- [ ] **Step 1: Inspect both local references at original detail**

Open `assets/codex-speak-github.png` and
`assets/posters/codex-speak-github-16x9.png`. Confirm that Image 1 is the
identity reference and Image 2 is the visual-family reference, not an asset to
overwrite.

Expected: the production speaker-prompt geometry and approved v1 visual family
are visible before generation.

- [ ] **Step 2: Generate the 16:9 composition**

Use one built-in Image Gen call with both reference images and this prompt:

```text
Use case: ads-marketing
Asset type: GitHub README and release poster v2
Primary request: Create a premium minimal 16:9 landscape launch poster for Codex Speak. Keep local speech privacy as the primary claim and make the shipping macOS menu bar control the second focal point.
Input images: Image 1 is the production Codex Speak logo identity reference. Preserve its exact rounded-square silhouette, white speaker, embedded >_ terminal prompt, indigo-to-violet colors, and proportions. Image 2 is the approved GitHub v1 poster and is a style reference only. Match its charcoal background, indigo/violet glow, subtle waveform, typography character, and editorial spacing without overwriting or merely upscaling it.
Scene/backdrop: deep charcoal-black with restrained indigo and violet glow and subtle waveform rhythm.
Composition/framing: true 16:9 landscape. Keep all editorial copy left aligned. On the right, connect the production logo, a tiny functional monochrome menu bar trigger, and one open macOS dark menu panel into a single product cluster. The trigger must not look like a second brand logo. Make every menu row legible at GitHub README width.
Text outside the menu (verbatim, render each line exactly once): "CODEX SPEAK"; "Your Codex speaks. Your voice stays on your Mac."; "Switch modes and control playback from the menu bar."; "macOS say · No TTS API · No API Key · No Network"; "Local refers to the Codex Speak speech pipeline."
Menu text (verbatim, one row each in this exact order): "Silent"; "Summary"; "Full"; "Stop Current Speech"; "Clear Pending Speeches"; "Quit Codex Speak".
Menu state: place one native checkmark beside "Summary" only. Do not check any other row.
Style/medium: polished macOS product campaign graphic, crisp flat typography, native-looking dark menu material, generous negative space.
Constraints: preserve the supplied logo; use one compact rounded menu panel; no icons, descriptions, toggles, separators, keyboard shortcuts, badges, or extra text inside the menu; no extra outside copy; no people; no other logos; no fake app window; no watermark.
```

Expected: one cohesive landscape poster with five outside-copy lines, six menu
rows in exact order, and only `Summary` checked.

- [ ] **Step 3: Inspect the generated image at original detail**

Verify all five outside-copy lines, all six menu rows, the single `Summary`
checkmark, the production logo, 16:9 hierarchy, qualifier legibility, and the
absence of invented menu affordances.

Expected: every acceptance criterion passes. If exactly one criterion fails,
issue one targeted edit that changes only that criterion and repeats every logo,
copy, menu-order, checkmark, and privacy invariant.

- [ ] **Step 4: Save and validate the selected PNG**

Copy the selected generated image to
`assets/posters/codex-speak-github-16x9-v2.png`, leaving the generated source
and v1 poster in place.

Run:

```bash
file assets/posters/codex-speak-github-16x9-v2.png
sips -g pixelWidth -g pixelHeight assets/posters/codex-speak-github-16x9-v2.png
```

Expected: PNG image data with a landscape ratio within one pixel of 16:9.

- [ ] **Step 5: Commit only the GitHub v2 poster**

```bash
git add assets/posters/codex-speak-github-16x9-v2.png
git commit -m "art: add menu bar github poster v2"
```

Expected: one commit containing only the GitHub v2 raster asset.

### Task 2: Xiaohongshu Portrait V2

**Files:**
- Reference: `assets/codex-speak-github.png`
- Reference: `assets/posters/codex-speak-xiaohongshu-3x4.png`
- Reference: `assets/posters/codex-speak-github-16x9-v2.png`
- Create: `assets/posters/codex-speak-xiaohongshu-3x4-v2.png`

**Interfaces:**
- Consumes: the production logo, approved portrait v1 style, and accepted GitHub v2 menu treatment.
- Produces: a standalone 3:4 Simplified Chinese v2 poster with the same brand and menu system.

- [ ] **Step 1: Inspect all three local references at original detail**

Confirm that the production logo remains the identity source, the portrait v1
defines phone-feed hierarchy, and GitHub v2 defines the accepted menu material
and product-cluster treatment.

Expected: the three reference roles are distinct and no existing file is an
overwrite target.

- [ ] **Step 2: Generate the 3:4 composition**

Use one separate built-in Image Gen call with all three reference images and
this prompt:

```text
Use case: ads-marketing
Asset type: Xiaohongshu launch poster and mobile-feed cover v2
Primary request: Create a premium minimal 3:4 portrait launch poster for Codex Speak. Keep local speech privacy as the primary claim and make the shipping Chinese macOS menu bar control the second focal point.
Input images: Image 1 is the production Codex Speak logo identity reference; preserve its exact rounded-square silhouette, white speaker, embedded >_ terminal prompt, indigo-to-violet colors, and proportions. Image 2 is the approved Xiaohongshu v1 poster and defines the portrait hierarchy and visual family. Image 3 is the accepted GitHub v2 poster and defines the menu material and brand treatment. Use Images 2 and 3 as references only; create a new portrait composition.
Scene/backdrop: deep charcoal-black with restrained indigo and violet glow and subtle waveform rhythm.
Composition/framing: true 3:4 portrait. Keep the production logo and privacy headline in the upper section, the open Chinese macOS menu in the middle as the second focal point, and local speech proof plus privacy qualifier below it. Connect a tiny functional monochrome menu bar trigger to the panel without making it look like a second logo. Keep every menu row readable in a phone feed.
Text outside the menu (verbatim, render each line exactly once): "CODEX SPEAK"; "让 Codex 开口说话"; "语音完全留在你的 Mac"; "菜单栏切换模式，随时停止或清除"; "只用 macOS say"; "无需 TTS API · 无需 API Key · 不联网"; "本地仅指 Codex Speak 的语音处理与播放链路".
Menu text (verbatim, one row each in this exact order): "静音"; "摘要"; "全文"; "停止当前朗读"; "清除待朗读内容"; "退出 Codex Speak".
Menu state: place one native checkmark beside "摘要" only. Do not check any other row.
Style/medium: polished macOS product campaign graphic, crisp Simplified Chinese typography, native-looking dark menu material, clean mobile editorial spacing.
Constraints: preserve the supplied logo; use one compact rounded menu panel; no icons, descriptions, toggles, separators, keyboard shortcuts, badges, or extra text inside the menu; no extra outside copy; no people; no other logos; no fake app window; no watermark.
```

Expected: one cohesive portrait poster with seven outside-copy lines, six menu
rows in exact order, and only `摘要` checked.

- [ ] **Step 3: Inspect the generated image at original detail**

Verify every Chinese character, Latin token, separator, the six-row menu order,
the single `摘要` checkmark, logo silhouette, portrait hierarchy, qualifier
legibility, and the absence of invented menu affordances.

Expected: every acceptance criterion passes. If exactly one criterion fails,
issue one targeted edit that changes only that criterion and repeats every logo,
copy, menu-order, checkmark, and privacy invariant.

- [ ] **Step 4: Save and validate the selected PNG**

Copy the selected generated image to
`assets/posters/codex-speak-xiaohongshu-3x4-v2.png`, leaving the generated source
and v1 poster in place.

Run:

```bash
file assets/posters/codex-speak-xiaohongshu-3x4-v2.png
sips -g pixelWidth -g pixelHeight assets/posters/codex-speak-xiaohongshu-3x4-v2.png
```

Expected: PNG image data with a portrait ratio within one pixel of 3:4.

- [ ] **Step 5: Commit only the Xiaohongshu v2 poster**

```bash
git add assets/posters/codex-speak-xiaohongshu-3x4-v2.png
git commit -m "art: add menu bar xiaohongshu poster v2"
```

Expected: one commit containing only the Xiaohongshu v2 raster asset.

### Task 3: Preservation and Final Visual Verification

**Files:**
- Verify: `assets/posters/codex-speak-github-16x9.png`
- Verify: `assets/posters/codex-speak-xiaohongshu-3x4.png`
- Verify: `assets/posters/codex-speak-github-16x9-v2.png`
- Verify: `assets/posters/codex-speak-xiaohongshu-3x4-v2.png`

**Interfaces:**
- Consumes: both approved v1 posters and both committed v2 posters.
- Produces: a verified four-asset set with untouched originals and channel-ready v2 files.

- [ ] **Step 1: Open both v2 images side by side at original detail**

Confirm that both posters use the same production logo geometry, charcoal and
indigo/violet palette, menu material, typography character, checkmark treatment,
and spacing system while retaining channel-specific layouts.

Expected: the v2 posters read as one brand family and the menu bar capability
is visible immediately after the privacy headline.

- [ ] **Step 2: Verify v1 preservation and all saved files**

Run:

```bash
shasum -a 256 assets/posters/codex-speak-github-16x9.png assets/posters/codex-speak-xiaohongshu-3x4.png
file assets/posters/codex-speak-github-16x9-v2.png assets/posters/codex-speak-xiaohongshu-3x4-v2.png
git status --short
```

Expected:

```text
fbc6c5401ac23262fc4c397dbd8cb2ba1bbee31c2d6c5a0b299a0e1448340bb0  assets/posters/codex-speak-github-16x9.png
fc6afdc54972f8c58467714e9bb07e4923782518ad2f4614e63e83854e8d9141  assets/posters/codex-speak-xiaohongshu-3x4.png
```

Both v2 files report PNG image data, and `git status --short` prints no
uncommitted poster changes.
