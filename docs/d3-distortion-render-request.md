# Disguise Render Request - Next Data Suggestions

## Purpose

This request is not a blocker for the current Path C UE validation.

The current Path C gate already selected sensor full-width normalization for
`M_PRT_OfficialSensorInverse`. The next Disguise render batch should target the
remaining normalization confound: whether Disguise is truly normalized by sensor
full width or by focal length in a setup where `fx` is close enough to image
width to hide the difference.

## Global Settings

- Plate: `scripts/distortion_calibration/uv_probe_3840x2160.exr`
- Output: `transmission frame`
- Format: `OpenEXR`, 32-bit float preferred; half-float accepted only if 32-bit is unavailable
- Resolution: `3840 x 2160`
- Lens over-scan: `1.5x`
- Color: linear, no tone mapping, no LUT, no gamma transform, no color management
- Scaling: 1:1 pixel mapping, no resize, no extra crop beyond the stated camera setup
- Sensor size: keep sensor width and height fixed across the sweep
- Center shift: `centerShiftMM=(0,0)` for every required frame
- Naming: lowercase `.exr`; use `p` for positive and decimal point, `n` for negative

## Required Set A - Focal-Length Sweep

Purpose: separate `sensor full-width` normalization from `focal-length`
normalization.

For all required frames:

- `K2=0`
- `K3=0`
- `centerShiftMM=(0,0)`

| focal_length_mm | K1 | filename |
|---:|---:|---|
| 24.0 | 0.0 | `disguise_focal24_K1_zero.exr` |
| 24.0 | +0.5 | `disguise_focal24_K1_p0p5.exr` |
| 30.302 | 0.0 | `disguise_focal30p302_K1_zero.exr` |
| 30.302 | +0.5 | `disguise_focal30p302_K1_p0p5.exr` |
| 50.0 | 0.0 | `disguise_focal50_K1_zero.exr` |
| 50.0 | +0.5 | `disguise_focal50_K1_p0p5.exr` |

## Optional Set B - K2/K3 Spot Checks

Purpose: keep a small independent check that K2/K3 use the same normalization
as K1 after the focal-length confound is resolved.

For all optional frames:

- `focal_length_mm=30.302`
- `centerShiftMM=(0,0)`

| K1 | K2 | K3 | filename |
|---:|---:|---:|---|
| 0 | +0.5 | 0 | `disguise_focal30p302_K2_p0p5.exr` |
| 0 | 0 | +0.5 | `disguise_focal30p302_K3_p0p5.exr` |

## Optional Set C - Higher Precision Probe

Purpose: reduce the current half-float / sampling floor before tightening
acceptance below the 1-3 px range.

Accept either:

- 32-bit float EXR UV probe output, or
- a structured-light / multi-frame probe where decoded source coordinates can
  exceed half-float UV precision.

Keep the same naming prefix and include a short note describing the export bit
depth and color pipeline.

## Return Layout

```text
validation_results/disguise_next_data/
├── focal_length_sweep/
│   ├── disguise_focal24_K1_zero.exr
│   ├── disguise_focal24_K1_p0p5.exr
│   ├── disguise_focal30p302_K1_zero.exr
│   ├── disguise_focal30p302_K1_p0p5.exr
│   ├── disguise_focal50_K1_zero.exr
│   └── disguise_focal50_K1_p0p5.exr
├── optional_k2_k3/
│   ├── disguise_focal30p302_K2_p0p5.exr
│   └── disguise_focal30p302_K3_p0p5.exr
└── optional_precision_probe/
    └── README.md
```

## Quick Sanity Check

```python
import os
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

import cv2

img = cv2.imread("disguise_focal30p302_K1_zero.exr", cv2.IMREAD_UNCHANGED)
print(img.shape, img.dtype)
print("R", float(img[..., 2].min()), float(img[..., 2].max()))
print("G", float(img[..., 1].min()), float(img[..., 1].max()))
```

Expected for a 1.5x over-scan identity frame: R/G range near `[0.1667, 0.8333]`.
