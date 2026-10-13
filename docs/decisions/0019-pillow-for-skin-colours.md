# 0019. Pillow to read skin colours from their pictures

- **Status**: Accepted
- **Date**: 2026-10-14
- **Deciders**: owner
- **Tags**: backend | data

## Context and problem statement

The colour filter (spec `2026-10-14-skin-colors-design.md`) needs each skin's own colours.
ByMykel has no palette: its `rarity.color` is the grade's. The colours have to be read from the
Steam picture, a PNG with a transparent background, which means decoding PNG (and Steam's
occasional JPEG / WebP) in Python.

## Decision drivers

- Decode PNG with alpha reliably; shrink before scanning.
- Run in the scheduler, off the request path; no native toolchain in our images.
- One small, widely used dependency.

## Considered options

1. **Pillow** — the standard imaging library; wheels for our platforms.
2. **A pure-Python PNG decoder** (`pypng`) — PNG only, slow on ~10 000 pictures, no resize.
3. **A colour API / service** — another vendor, another key, per-call cost.

## Decision outcome

**Chosen option:** Pillow, in `apps/api` (the scheduler imports the module from there). Only
`modules/skins/colors.py` imports it.

### Positive consequences

- Decodes every format Steam serves, shrinks with good filtering, reads alpha.
- Prebuilt wheels: no build step in the images.

### Negative consequences

- A native library in the image (~4 MB). It parses images from the Steam CDN only, fetched by
  our own job, never uploaded by users.
- Security updates to follow (Dependabot covers it).

## Validation

The owner reviews the colours of the 102 most popular skins before the filter ships; the job's
backfill finishes in hours, not days.
