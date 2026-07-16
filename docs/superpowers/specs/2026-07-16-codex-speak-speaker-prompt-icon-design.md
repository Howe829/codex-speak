# Codex Speak Speaker-Prompt Icon Design

## Status and Selected Concept

This specification replaces the three-pulse direction. The user explicitly
selected `artwork/concepts/codex-speak-speaker-prompt-variant.png`, SHA-256
`aeb7c9a69acac3d0aa6e89750d1f09a49ebabde99552bbe1911fc43959ccff92`, as
the visual direction.

The generated raster is a concept reference only. It is not copied, traced,
or packaged as a production master. Production assets are reconstructed from
the deterministic geometry in this specification.

## Goal

Create one compact Codex Speak mark in which a loudspeaker/megaphone silhouette
is the only container and the exact terminal prompt `>_` is cut out inside it.
Use that same integrated mark for the App/GitHub icon and the macOS menu-bar
template icon.

## Unified Mark

- The speaker is one closed silhouette, not a speaker beside a terminal logo.
- The chevron and underscore are two separate negative-space cutouts inside
  the speaker. Neither cutout is an adjacent or overlaid second logo.
- The prompt is exactly `>_`; the underscore may not be removed, merged into
  the chevron, replaced with a dot, or hidden at the smallest size.
- The family has no enclosing circle, sound arcs, microphone, waveform bars,
  OpenAI mark, text label, or extra symbol.
- Normal and transient-error menu-bar states retain the same integrated mark;
  errors may change the tooltip but may not replace the mark with `!` or a
  system symbol.

## Deterministic Geometry

All mark geometry uses a `24 × 24` bottom-origin canvas. Coordinates below are
authoritative for both SVG and Swift; optical adjustments must update both
sources and their equality tests in the same change.

The speaker container is one closed cubic path:

```text
M 5.5 5
C 4.4 5 3.5 5.9 3.5 7
L 3.5 17
C 3.5 18.1 4.4 19 5.5 19
L 10 19
L 18.7 21.5
C 19.55 21.75 20.4 21.1 20.4 20.2
L 20.4 3.8
C 20.4 2.9 19.55 2.25 18.7 2.5
L 10 5
Z
```

The embedded prompt uses these separate cutouts:

- Chevron: polyline `(6.4, 14.6) → (9.5, 12) → (6.4, 9.4)`, round cap,
  round join, width `1.8`.
- Cursor: rounded rectangle `x = 10.8`, `y = 8.6`, `width = 4.0`,
  `height = 1.6`, corner radius `0.8`.

SVG uses its normal top-origin viewport while preserving the authoritative
bottom-origin coordinates. The standalone master must wrap the mark in
`transform="translate(0 24) scale(1 -1)"`. The `1024 × 1024` App/GitHub master
must use `transform="translate(176 848) scale(28 -28)"`, which maps a point
`(x, y)` to `(176 + 28x, 848 - 28y)` without rewriting the source geometry.

## Small-Size Legibility Gate

At `16 px`, the normalized scale is `16 / 24`. The chevron stroke therefore
renders at `1.2 px`, the cursor at approximately `2.67 × 1.07 px`, and the
horizontal gap between chevron vertex and cursor at approximately `0.87 px`.
Automated tests must lock those values and confirm that the container,
chevron cutout, and cursor cutout remain separate geometry.

The production mark must also be visually inspected at `16`, `18`, and
`22 px` on both light and dark appearances. If `>` and `_` are not both
distinct at `16 px`, implementation stops for a geometry revision. It must
not silently omit, shorten away, merge, or substitute the underscore.

## Menu-Bar Icon

The menu-bar icon is a monochrome macOS template `NSImage` with no background
and no enclosing circle. Swift draws the speaker silhouette in opaque black,
then clears the chevron and cursor from its alpha channel. Setting
`isTemplate = true` lets macOS tint the remaining pixels for light and dark
menu bars while the exact `>_` holes stay transparent.

The `24 × 24` geometry is scaled into an `18 × 18` point template image. macOS
may rasterize that template at the target display scale; the geometry tests
also validate the explicit `16 px` floor.

## App and GitHub Icon

The App/GitHub icon places the unchanged integrated mark on a `1024 × 1024`
rounded square:

- Background: linear gradient from deep indigo `#2636A7` to violet `#6D28D9`.
- Background bounds: `x = 32`, `y = 32`, `width = 960`, `height = 960`,
  corner radius `224`.
- Speaker: linear gradient from white `#FFFFFF` to icy cyan `#C7F2FF`.
- Prompt: the same true cutout used by the menu icon, revealing the dark
  indigo/violet background beneath it.
- Mark transform: `translate(176 848) scale(28 -28)` with no geometric
  changes to the speaker or prompt.

The mark remains centered within a `448 px` safe circular-crop radius around
`(512, 512)`, leaving additional room inside a GitHub avatar crop.

## Production and Packaging

- `artwork/codex-speak-speaker-prompt.svg` is the monochrome vector master.
- `artwork/codex-speak-app-icon.svg` is the App/GitHub vector master.
- `CodexSpeakCore` owns pure `Double` geometry types and constants without
  importing AppKit.
- `CodexSpeakMenu` converts those types to `NSBezierPath` and performs the
  alpha cutout.
- A local Swift/AppKit renderer exports the SVG master to the GitHub PNG and
  required ICNS representations.
- `CFBundleIconFile` is exactly `AppIcon`, and the build script copies
  `AppIcon.icns` into `Contents/Resources` before ad-hoc signing.
- Image Gen and the selected raster are not read by build, render, package,
  or runtime code.

## Runtime Constraints

- Runtime requirements remain macOS 13.0 or newer and Python 3.10 or newer.
- Runtime uses only the Python standard library and macOS frameworks.
- Runtime adds no third-party dependency, network service, download, API key,
  or generated-asset service.
- Asset generation is a local development/build step and performs no network
  access.

## Deliverables

- The selected concept raster tracked as design history.
- One deterministic monochrome SVG master.
- One deterministic App/GitHub SVG master.
- One AppKit template image generated from matching Swift geometry.
- One `1024 × 1024` GitHub/README PNG.
- One complete macOS `AppIcon.icns`, packaged into the universal helper app.
- Automated SVG, Swift geometry, metadata, packaging, and README tests.

## Acceptance Criteria

- The loudspeaker/megaphone is the single container and reads as one compact
  silhouette.
- The exact `>_` is embedded inside the container as separate negative-space
  chevron and cursor cutouts.
- App/GitHub and menu-bar variants use identical normalized mark geometry.
- The App/GitHub icon uses the specified indigo-to-violet rounded square,
  white-to-icy-cyan speaker, and dark prompt cutout.
- The menu-bar mark is a monochrome template image whose `>_` is an alpha
  cutout and remains correct under light and dark macOS tinting.
- Both `>` and `_` remain distinct at `16 px`; otherwise work stops rather
  than shipping a simplified prompt.
- The mark survives a circular avatar crop with no clipping or imbalance.
- No enclosing circle, arcs, microphone, waveform bars, OpenAI mark, text
  label, or extra symbol appears in the icon family.
- Production is reproducible from deterministic SVG and Swift geometry; the
  Image Gen raster remains reference-only.
- The packaged helper keeps macOS 13.0+, Python 3.10+, no runtime dependencies,
  and no network access.
