# Codex Speak Launch Posters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and save one GitHub landscape poster and one Xiaohongshu portrait poster that present Codex Speak's local speech pipeline accurately.

**Architecture:** Use the built-in Image Gen tool once per channel-specific composition, with the production PNG as a logo reference rather than an edit target. Inspect each result for copy accuracy, logo fidelity, hierarchy, and privacy wording before copying the selected raster into `assets/posters/`.

**Tech Stack:** Built-in Image Gen, Codex image inspection, PNG assets, local filesystem copy.

## Global Constraints

- Preserve the production speaker silhouette, embedded `>_` prompt, colors, and proportions from `assets/codex-speak-github.png`.
- The privacy claim applies only to Codex Speak's speech processing, queueing, and playback pipeline.
- Render every listed line verbatim with no extra copy.
- Use a premium minimal macOS aesthetic with deep charcoal, indigo, and violet.
- No people, stock imagery, unrelated logos, fake app screenshots, decorative 3D clutter, or watermark.
- Save final raster images under `assets/posters/` without overwriting the production logo.

---

### Task 1: GitHub Landscape Poster

**Files:**
- Reference: `assets/codex-speak-github.png`
- Create: `assets/posters/codex-speak-github-16x9.png`

**Interfaces:**
- Consumes: the production logo PNG as a visual reference.
- Produces: a standalone 16:9 README/release poster PNG.

- [ ] **Step 1: Generate the landscape composition**

Use the built-in Image Gen tool with `assets/codex-speak-github.png` labeled as `Image 1: reference image; preserve this exact logo design`. Use this prompt:

```text
Use case: ads-marketing
Asset type: GitHub README and release poster
Primary request: Create a premium minimal 16:9 landscape launch poster for Codex Speak, a private local macOS speech companion for Codex.
Input images: Image 1 is the production Codex Speak logo reference. Preserve its speaker silhouette, embedded >_ prompt, indigo-to-violet colors, and proportions exactly; do not redesign it.
Scene/backdrop: deep charcoal-black background with restrained indigo and violet glow, subtle waveform rhythm, no literal room or device scene.
Style/medium: polished macOS product campaign graphic, crisp flat typography, clean editorial spacing.
Composition/framing: large production logo balanced against left-aligned product copy, generous negative space, readable at GitHub README width.
Text (verbatim): "CODEX SPEAK"; "Your Codex speaks. Your voice stays on your Mac."; "macOS say · No TTS API · No API Key · No Network"; "Silent · Summary · Full"; "Local refers to the Codex Speak speech pipeline."
Constraints: render every line exactly once; make the headline dominant and the privacy qualifier small but legible; preserve the supplied logo; no extra text; no people; no fake UI; no watermark.
```

Expected: one cohesive 16:9 poster with all five exact text lines and the recognizable production logo.

- [ ] **Step 2: Inspect and correct only if necessary**

Inspect the generated image at original detail. Verify exact spelling, punctuation, logo silhouette, `>_` cutout, contrast, and 16:9 hierarchy. If one criterion fails, issue one targeted Image Gen edit that changes only the failed criterion and repeats all invariants.

Expected: all acceptance checks pass without introducing extra copy.

- [ ] **Step 3: Save the selected PNG**

Copy the selected generated output to `assets/posters/codex-speak-github-16x9.png`.

Expected: the file exists, is a PNG, and opens at the intended landscape ratio.

- [ ] **Step 4: Commit the GitHub poster**

```bash
git add assets/posters/codex-speak-github-16x9.png
git commit -m "art: add codex speak github poster"
```

Expected: one commit containing only the GitHub poster asset.

### Task 2: Xiaohongshu Portrait Poster

**Files:**
- Reference: `assets/codex-speak-github.png`
- Create: `assets/posters/codex-speak-xiaohongshu-3x4.png`

**Interfaces:**
- Consumes: the same production logo PNG and visual family established by Task 1.
- Produces: a standalone 3:4 mobile-feed cover PNG.

- [ ] **Step 1: Generate the portrait composition**

Use the built-in Image Gen tool with `assets/codex-speak-github.png` labeled as `Image 1: reference image; preserve this exact logo design`. Use this prompt:

```text
Use case: ads-marketing
Asset type: Xiaohongshu launch poster and mobile-feed cover
Primary request: Create a premium minimal 3:4 portrait launch poster for Codex Speak, emphasizing that its speech pipeline stays on the Mac.
Input images: Image 1 is the production Codex Speak logo reference. Preserve its speaker silhouette, embedded >_ prompt, indigo-to-violet colors, and proportions exactly; do not redesign it.
Scene/backdrop: deep charcoal-black background with restrained indigo and violet glow, subtle waveform rhythm, no literal room or device scene.
Style/medium: polished macOS product campaign graphic, crisp Chinese typography, clean editorial spacing.
Composition/framing: logo and headline dominate the top two thirds; proof points sit in a compact lower panel; text remains readable as a phone feed cover.
Text (verbatim): "CODEX SPEAK"; "让 Codex 开口说话"; "语音完全留在你的 Mac"; "只用 macOS say"; "无需 TTS API · 无需 API Key · 不联网"; "静音 · 摘要 · 全文"; "本地仅指 Codex Speak 的语音处理与播放链路"
Constraints: render every line exactly once; preserve the supplied logo; make the privacy qualifier small but legible; no extra text; no people; no fake UI; no watermark.
```

Expected: one cohesive 3:4 poster with all seven exact text lines and the recognizable production logo.

- [ ] **Step 2: Inspect and correct only if necessary**

Inspect the generated image at original detail. Verify every Chinese character, Latin token, separator, logo silhouette, `>_` cutout, contrast, and mobile hierarchy. If one criterion fails, issue one targeted Image Gen edit that changes only the failed criterion and repeats all invariants.

Expected: all acceptance checks pass without introducing extra copy.

- [ ] **Step 3: Save the selected PNG**

Copy the selected generated output to `assets/posters/codex-speak-xiaohongshu-3x4.png`.

Expected: the file exists, is a PNG, and opens at the intended portrait ratio.

- [ ] **Step 4: Commit the Xiaohongshu poster**

```bash
git add assets/posters/codex-speak-xiaohongshu-3x4.png
git commit -m "art: add codex speak xiaohongshu poster"
```

Expected: one commit containing only the Xiaohongshu poster asset.

### Task 3: Final Visual Verification

**Files:**
- Verify: `assets/posters/codex-speak-github-16x9.png`
- Verify: `assets/posters/codex-speak-xiaohongshu-3x4.png`

**Interfaces:**
- Consumes: both final poster PNGs.
- Produces: verified channel-ready assets with no additional repository changes.

- [ ] **Step 1: Open both images side by side**

Inspect both final images at original detail and confirm they share the same logo treatment, palette, lighting, typography character, and spacing system.

Expected: the two posters read as one brand family while retaining their channel-specific layouts.

- [ ] **Step 2: Verify the saved files**

```bash
file assets/posters/codex-speak-github-16x9.png assets/posters/codex-speak-xiaohongshu-3x4.png
git status --short
```

Expected: both files are PNG images and the worktree contains no uncommitted poster changes.
