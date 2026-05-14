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

---

## 2026-05-14 update — backend swapped to `oiio-static-python`

**Trigger:** P1 G2 lanPC deployment surfaced two gaps the original
spike missed:

1. **conda-forge `openimageio` on Windows ships the C++ library only —
   no `oiiotool.exe` CLI.** scoop main/extras + winget have no
   openimageio package. The original spike picked `oiiotool` assuming
   `brew install openimageio` (Mac) / `scoop install openimageio`
   (Win), the latter not being a real install path on Windows.

2. **PyPI `OpenEXR` 3.x API did not match the assumptions of an
   intermediate revision of the migration plan.** Empirical probe in a
   Python 3.11 venv with `OpenEXR==3.4.11`:
   - `OpenEXR.TimeCode(hours=..., dropFrame=...)` kwarg constructor:
     not supported (fields are descriptors, not kwargs).
   - `OpenEXR.Rational(50, 1)` assigned to `header["framesPerSecond"]`:
     raises `unrecognized type of attribute 'framesPerSecond'`.
   - tuple `(50, 1)` writable but read-back type is not `Rational`.

**Swap:** Replaced subprocess+`oiiotool` with in-process
`import OpenImageIO as oiio` via the `oiio-static-python` PyPI wheel
(OpenImageIO 3.0.8 + OpenColorIO statically linked, ~11 MB cp310–cp313
win_amd64 / macOS / Linux wheels). Pin: `oiio-static-python==3.0.8.1.1`.

**Why this is equivalent to the original `oiiotool` choice:** OIIO's
Python binding wraps the **same C++ library** that `oiiotool` is built
on top of. Preservation guarantees (multipart, channels, compression,
pixelAspectRatio) come from the library, not the CLI wrapper. Calling
the library directly through its Python binding has the same on-disk
effect.

**Empirical API findings (probe `scripts/probe_oiio_static_python.py`):**

- No `oiio.TimeCode` helper class in this wheel — encode the SMPTE `time`
  field manually (SMPTE 12M BCD packing, ~10 lines). See
  `exr_timecode_writer._smpte_encode_time_field`.
- `ImageBuf.write` has no multipart-append semantics — calling it
  per-subimage to the same tmp path collapses multipart EXR to the last
  subimage written. Must use `ImageOutput.open(file, [specs])` to
  declare layout, then `open(file, spec, "AppendSubimage")` (string
  mode, not enum) for each subsequent subimage.
- Authoritative subimage count via `ImageInput.seek_subimage(i, 0)`;
  `ImageBuf(file, i, 0).has_error` is unreliable past last subimage.
- Typed attribute write: `spec.attribute(name, oiio.TypeTimeCode,
  (time_uint32, user_uint32))` and `spec.attribute(name,
  oiio.TypeRational, (num, den))`. Read back via
  `spec.getattribute(name)` returns a tuple.
- Atomic rewrite needs the temp filename to retain `.exr` extension
  (OIIO infers format from extension); use `<file>.partial.exr` not
  `<file>.tmp`.

**Validation:**

- `scripts/probe_oiio_static_python.py` runs three phases:
  - Phase A — synthetic 4×4 RGB EXR API contract.
  - Phase A.7 — multipart write API (`ImageOutput` + `'AppendSubimage'`).
  - Phase B — real MRQ EXR preservation (channels / compression /
    multipart / dims survive a typed-attribute rewrite). Phase B is
    mandatory; missing `/tmp/mrq_sample.exr` fails with exit 30 — no
    "skip" path (per Codex adversarial review).

- All three phases passed against real take_15 MRQ EXR (1920×1080
  RGBA half + piz + PAR=1.0) on 2026-05-14.

- lanPC `integration_p1.py` 14/14 PASS end-to-end on UE 5.7 with
  oiio-static-python 3.0.8.1 + Miniforge3 exrheader:
  - smpte:TimeCode = `(155460880, 0)` (BCD-encoded 09:44:25:10)
  - FramesPerSecond = `(50, 1)`
  - exrheader confirms `type timecode` + `type rational` ground truth.

**Production gate:** DaVinci 19+ Inspector reading the patched EXR
sequence + OTIO sidecar import — final P1 G2 + G4 acceptance, covered
by Tasks 13–14 of the migration plan.

**What did NOT change across the swap:**

- `patch_exr_timecode_in_dir` public signature.
- `_frame_to_timecode` drop-frame inverse algorithm + its 6 unit tests.
- Filename regex + MRQ-token validation + their 2 unit tests.
- Output attribute names: `smpte:TimeCode` and `FramesPerSecond` — same
  as `oiiotool` wrote.
