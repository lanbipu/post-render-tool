# Disguise Render Request - Custom PostProcess Gates

目标: 补齐 `Custom Post-Process Material` 公式冻结前必须的数据。当前 Gate 0 已证明简单
`official_sensor_inverse` polynomial 不能直接冻结; 下面这些帧用于判断 K2/K3 公式形态、
`centerShiftMM` 单位/符号、以及 identity baseline。

## Global Settings

- Plate: `scripts/distortion_calibration/uv_probe_3840x2160.exr`
- Output: `transmission frame`
- Format: `OpenEXR`, 32-bit float, RGB/RGBA accepted
- Resolution: `3840 x 2160`
- Lens over-scan: `1.5x`
- Color: linear, no tone mapping, no LUT, no gamma transform, no color management
- Scaling: 1:1 pixel mapping, no resize, no crop beyond the existing Round 2.1 camera setup
- Camera: same camera, focal length, sensor size, aspect, and framing as Round 2.1 K1 sweep
- Naming: use lowercase `.exr`; use `p` for positive and decimal point, `n` for negative

## Set A - K2/K3 Sweep (10 Frames)

Purpose: check whether K2/K3 share the same simple radial polynomial semantics as K1.

For all K2 frames: `K1=0`, `K3=0`, `centerShiftMM=(0,0)`.

| K2 | filename |
|---:|---|
| -0.5 | `disguise_K2_n0p5.exr` |
| -0.3 | `disguise_K2_n0p3.exr` |
| 0.0 | `disguise_K2_zero.exr` |
| +0.3 | `disguise_K2_p0p3.exr` |
| +0.5 | `disguise_K2_p0p5.exr` |

For all K3 frames: `K1=0`, `K2=0`, `centerShiftMM=(0,0)`.

| K3 | filename |
|---:|---|
| -0.5 | `disguise_K3_n0p5.exr` |
| -0.3 | `disguise_K3_n0p3.exr` |
| 0.0 | `disguise_K3_zero.exr` |
| +0.3 | `disguise_K3_p0p3.exr` |
| +0.5 | `disguise_K3_p0p5.exr` |

## Set B - CenterShift Sweep (5 Frames)

Purpose: validate `centerShiftMM.x` sign and unit before wiring `CenterUV`.

For all frames: `K1=0`, `K2=0`, `K3=0`, `centerShiftMM.y=0`.

| centerShiftMM.x | filename |
|---:|---|
| -0.10 | `disguise_centerShiftX_n0p10.exr` |
| -0.05 | `disguise_centerShiftX_n0p05.exr` |
| 0.00 | `disguise_centerShift_zero.exr` |
| +0.05 | `disguise_centerShiftX_p0p05.exr` |
| +0.10 | `disguise_centerShiftX_p0p10.exr` |

Optional if time allows: repeat the same 5 values for `centerShiftMM.y` with filenames
`disguise_centerShiftY_*.exr`. The 5 X-axis frames above are the minimum blocker.

## Set C - Identity Round-Trip (1 Frame)

Purpose: clean no-distortion baseline for Gate 1.5 and future image diff.

| K1 | K2 | K3 | centerShiftMM | filename |
|---:|---:|---:|---|---|
| 0 | 0 | 0 | `(0,0)` | `disguise_identity_K0_center0.exr` |

This may match the K2/K3 zero frame visually, but keep the separate filename so reports can
reference it without ambiguity.

## Return Layout

```text
validation_results/custom_pp_gate_inputs/
├── k2_k3_sweep/
│   ├── disguise_K2_n0p5.exr
│   ├── disguise_K2_n0p3.exr
│   ├── disguise_K2_zero.exr
│   ├── disguise_K2_p0p3.exr
│   ├── disguise_K2_p0p5.exr
│   ├── disguise_K3_n0p5.exr
│   ├── disguise_K3_n0p3.exr
│   ├── disguise_K3_zero.exr
│   ├── disguise_K3_p0p3.exr
│   └── disguise_K3_p0p5.exr
├── center_shift_sweep/
│   ├── disguise_centerShiftX_n0p10.exr
│   ├── disguise_centerShiftX_n0p05.exr
│   ├── disguise_centerShift_zero.exr
│   ├── disguise_centerShiftX_p0p05.exr
│   └── disguise_centerShiftX_p0p10.exr
└── identity/
    └── disguise_identity_K0_center0.exr
```

## Quick Sanity Check

Run this after exporting any 1-2 frames:

```python
import os
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

import cv2

img = cv2.imread("disguise_identity_K0_center0.exr", cv2.IMREAD_UNCHANGED)
print(img.shape, img.dtype)
print("R", float(img[..., 2].min()), float(img[..., 2].max()))
print("G", float(img[..., 1].min()), float(img[..., 1].max()))
```

Expected:

```text
shape: (2160, 3840, 3+) or (2160, 3840, 4)
dtype: float32
R/G range near [0.1667, 0.8333] for the identity frame with 1.5x lens over-scan
```
