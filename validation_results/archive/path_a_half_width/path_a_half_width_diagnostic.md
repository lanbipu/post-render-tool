# Path A Half-Width Diagnostic

## Verdict

`DEFERRED`: Path A is confirmed to use camera half-width normalization, but this change set does not rewrite fitted coefficients.

## Evidence

- `scripts/distortion_calibration/analyze_renders.py` computes:
  - `half_w = W_camera / 2.0`
  - `out_x_norm = (x + 0.5 - cx) / half_w`
  - `src_x_norm = (R * W - cx) / half_w`
- `scripts/distortion_calibration/README.md` documents the same Path A convention.
- Path C now uses sensor full-width UV normalization:
  - `r = (d.x, d.y / aspect)`

## Decision

Path A residuals must not be used as shader correctness evidence for Path C.

The next Path A decision is separate from UE Path C validation:

1. Refit Path A coefficients under full-width semantics, or
2. Mark Path A as legacy-only and keep it out of current Path C acceptance gates.
