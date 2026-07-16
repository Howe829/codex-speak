# Codex Speak Icon Family Design

> **Superseded (2026-07-16):** The user selected the integrated speaker-container
> concept with an embedded `>_` prompt. Use the
> [speaker-prompt design](2026-07-16-codex-speak-speaker-prompt-icon-design.md)
> and its [implementation plan](../plans/2026-07-16-codex-speak-speaker-prompt-icon.md)
> instead of this three-pulse direction.

## Goal

Create an original, compact icon family for Codex Speak that works as both a
public GitHub/App identity and a native macOS menu-bar template icon. The
family should communicate voice activity through rhythm and motion without
copying ChatGPT's Use Voice asset or turning the menu-bar mark into two joined
logos.

## Design Direction

The core mark is a **three-pulse stair**: exactly three rounded vertical bars
with unequal heights and deliberately offset vertical positions. The bars rise
from lower left to upper right as one compact rhythmic silhouette. Their
spacing, lengths, and baselines are asymmetric so the mark does not resemble a
centered equalizer or the five-bar ChatGPT Use Voice icon.

The mark contains no terminal chevron, cursor underscore, microphone, speaker
cone, radiating arcs, enclosing circle, text, or separate secondary symbol.
Codex identity comes from the product context, name, color system, and
consistent use of the pulse rather than from combining a terminal logo with an
audio logo.

## Originality Constraints

- Use exactly three bars, never five.
- Keep the composition asymmetric rather than mirrored around a center bar.
- Offset both the bar heights and their vertical positions.
- Do not use the white circular container from the reference image.
- Do not trace or reproduce the reference image's bar lengths, spacing, or
  overall silhouette.
- Do not use the OpenAI knot logo or other third-party brand marks.

The provided ChatGPT Use Voice image is a reference only for simplicity,
rounded stroke quality, and small-size clarity.

## Menu-Bar Icon

The menu-bar asset is a monochrome macOS template image built directly from
the three-pulse stair. It has no colored background or container. The optical
bounding box is close to square and comparable in apparent weight to standard
macOS status icons.

The master geometry must remain distinct and legible at 16, 18, and 22 pixels.
At 16 pixels, no bar may merge with another and the asymmetric stair rhythm
must remain visible. Light and dark menu bars use the same template mask so
macOS supplies the appropriate foreground color.

## App and GitHub Icon

The App/GitHub version places the same three-pulse stair, without geometric
changes, inside a macOS-style rounded square. The background uses a restrained
deep-indigo-to-violet gradient. The pulse uses white or a very light icy cyan
with sufficient contrast at small avatar sizes.

The mark receives generous optical padding and remains centered by visual
weight rather than by raw geometric bounds. It must still read clearly when
cropped to a circular GitHub avatar.

## Image Generation and Finalization

Image Gen will produce a focused concept board containing only this approved
direction: the primary App/GitHub icon, the isolated monochrome template mark,
and realistic 16, 18, and 22 pixel previews on light and dark menu bars. The
prompt must include every originality constraint above.

The selected generated concept is a visual reference, not the production
master. Production geometry will be reconstructed as a deterministic vector
asset so stroke widths, spacing, template behavior, and exports are exact.

## Deliverables

- One editable vector master for the three-pulse stair.
- One monochrome macOS template asset for the menu-bar helper.
- One App icon set covering required macOS sizes.
- One square high-resolution PNG for GitHub and README use.
- Light-menu-bar, dark-menu-bar, and circular-avatar preview images.

## Acceptance Criteria

- The icon reads as one mark, not multiple adjacent symbols.
- The menu-bar mark is legible and balanced at 16, 18, and 22 pixels.
- The icon remains recognizable in both light and dark menu bars.
- The GitHub icon survives circular cropping without clipping or imbalance.
- The family contains exactly three asymmetric pulse bars and none of the
  prohibited reference geometry.
- No generated raster is shipped as the only production source; a vector
  master exists for reproducible exports.
