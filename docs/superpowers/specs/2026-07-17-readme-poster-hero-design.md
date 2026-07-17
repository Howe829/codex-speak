# Codex Speak README Poster Hero Design

## Goal

Replace the standalone production icon at the top of the GitHub README with the
approved GitHub v2 landscape poster so visitors immediately see both the local
speech privacy message and the menu bar controls.

## Scope

- Modify only the top image reference in `README.md`.
- Replace `assets/codex-speak-github.png` with
  `assets/posters/codex-speak-github-16x9-v2.png`.
- Use standard Markdown image syntax so GitHub scales the poster to the README
  content width without custom HTML.
- Use the alt text `Codex Speak`.
- Keep the `# Codex Speak` heading and all following README content unchanged.
- Keep the Marketplace production logo, both v1 posters, and both v2 posters
  unchanged.

## Resulting README Header

```markdown
# Codex Speak

![Codex Speak](assets/posters/codex-speak-github-16x9-v2.png)
```

## Acceptance Criteria

- The README renders the approved v2 GitHub poster directly below the title.
- The referenced poster path exists with exact casing.
- The standalone icon no longer appears as the README header image.
- No custom HTML, width attribute, link wrapper, or duplicate hero image is
  introduced.
- No README text outside the image line changes.
- No raster or Marketplace metadata changes.
