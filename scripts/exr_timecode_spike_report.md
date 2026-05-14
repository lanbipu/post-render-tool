# Task 9 EXR Writer Spike — Report

**Date**: 2026-05-14
**Status**: Backend selected — **oiiotool**

## Goal

Pick the backend Task 10 ships for writing typed SMPTE `timeCode` +
`framesPerSecond` attributes to MRQ-rendered EXR files (for P1 G2 — DaVinci
19+ / Nuke / Resolve auto-conform).

Three candidates considered:
- **(a) PyPI `OpenEXR` + `Imath`** — cross-platform Python wheel
- **(b) `oiiotool` (OpenImageIO CLI)** — industry-standard attribute ops
- **(c) UE-side `UMoviePipelineImagePassBase` subclass** — write during MRQ render

Acceptance criterion: `exrheader` reports a typed `timeCode` attribute
(not a `string` display alias) AND the rational `framesPerSecond` attribute
survives, on **both** single-part and multipart EXR layouts.

## Result

### (b) oiiotool — **PASS, ships in Task 10**

Tooling: `brew install openimageio` → `/opt/homebrew/bin/oiiotool` (also
ships `exrheader`).

Command pattern:
```bash
oiiotool render.0625994.exr \
  --attrib:type=timecode "smpte:TimeCode" "10:00:00:00" \
  --attrib:type=rational FramesPerSecond "50/1" \
  -o render.0625994.exr
```

**Single-part EXR** (mock RGB):
```
FramesPerSecond (type rational): 50/1 (50)
timeCode (type timecode):
```
- Typed `timecode` confirmed (not string)
- Rational `50/1` confirmed
- Other attributes (`compression`, `pixelAspectRatio`) preserved

**Multipart EXR** (mock RGB + alpha layered with `--siappendall`):
```
FramesPerSecond (type rational): 50/1 (50)
timeCode (type timecode):
```
- Typed `timecode` confirmed on multipart file
- Channel layout preserved

### (a) PyPI OpenEXR + Imath — **DEFERRED**

- Not installable on macOS system Python under PEP 668 (`pip install`
  refuses to write to `/Library/Frameworks/...`)
- Even with the wheel, in-place rewrite of multipart EXR is fragile in
  pre-3.3 versions — requires reading all channels and constructing a new
  `OutputFile` with merged header
- Revisit only if oiiotool fails on real MRQ output

### (c) UE-side `UMoviePipelineImagePassBase` — **DEFERRED**

- Cleanest design but requires plugin C++ change to MRQ output path
- Scope creep for P1; revisit if oiiotool can't be installed on user
  machines

## Decision: ship oiiotool in Task 10

Rationale:
- Both critical attributes are typed correctly per `exrheader`
- Multipart preservation confirmed
- No Python wheel install pain (brew / scoop CLI install is one command)
- Aligns with industry conform tools' attribute conventions

## Remaining manual verification (Task 13)

1. **Real MRQ-rendered EXR**: Spike used mock EXR. First user-driven
   render on lanPC must repeat verification on actual `UnrealEditor`-
   generated EXR — MRQ-specific header attrs (`compression`, AOV layout)
   must survive oiiotool rewrite.
2. **DaVinci 19+ import**: drag patched EXR sequence into DaVinci Media
   Pool; Inspector → File → Time Code must show the SMPTE start value
   (final P1 G2 gate).
3. **Nuke import** (if available): same check via Read node → Metadata
   viewer.

These belong in Task 13 (P1 integration), not this spike.
