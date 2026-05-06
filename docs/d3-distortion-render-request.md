# Disguise Render Request — CenterShift Sweep

CenterShift 的 sign convention 已确认（`X` 用 +公式，`Y` 取反），但量级因 16-bit half-float 量化阶（≈2.8 px @ 4K）压扁。需要把步长从 ±0.10 mm 加大到 ±0.30 / ±0.50 mm，让信号超出量化阶 5–10 倍，拿到精确 mm/px 转换系数。

## Global Settings

- Plate: `scripts/distortion_calibration/uv_probe_3840x2160.exr`
- Output: `transmission frame`, OpenEXR (linear, no tone mapping / LUT / gamma / color management)
- Resolution: 3840 × 2160
- Lens over-scan: 1.5×
- Camera: same camera, focal, sensor, aspect, framing as Round 2.x
- Naming: lowercase, `p` = positive / decimal point, `n` = negative

## Frames

所有帧固定 `K1=+0.3, K2=0, K3=0`。X-sweep 帧固定 `centerShiftMM.y=0`；Y-sweep 帧固定 `centerShiftMM.x=0`。

### X axis (5 frames, blocker)

| centerShiftMM.x | filename |
|---:|---|
| 0.00 | `disguise_K1p3_centerShift_zero.exr` |
| -0.30 | `disguise_K1p3_centerShiftX_n0p30.exr` |
| -0.50 | `disguise_K1p3_centerShiftX_n0p50.exr` |
| +0.30 | `disguise_K1p3_centerShiftX_p0p30.exr` |
| +0.50 | `disguise_K1p3_centerShiftX_p0p50.exr` |

`disguise_K1p3_centerShift_zero.exr` 同时是 X 和 Y sweep 的内部 anchor。

### Y axis (4 frames, optional)

| centerShiftMM.y | filename |
|---:|---|
| -0.30 | `disguise_K1p3_centerShiftY_n0p30.exr` |
| -0.50 | `disguise_K1p3_centerShiftY_n0p50.exr` |
| +0.30 | `disguise_K1p3_centerShiftY_p0p30.exr` |
| +0.50 | `disguise_K1p3_centerShiftY_p0p50.exr` |

## Quick Sanity Check

渲完 1–2 帧先跑这个，确认 d3 真的把 centerShiftMM 写进去了：

```python
import os
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2

img = cv2.imread("disguise_K1p3_centerShift_zero.exr", cv2.IMREAD_UNCHANGED)
print(img.shape, img.dtype)                                          # (2160, 3840, 3+), float32
print("R", float(img[..., 2].min()), float(img[..., 2].max()))       # 比 [0.1667, 0.8333] 略宽
print("center", float(img[1080, 1920, 2]), float(img[1080, 1920, 1]))  # 接近 0.5
```

Anchor 帧 (`centerShift_zero`) 中心像素 R/G 必须接近 0.5；任何 sweep 帧的 R 通道 md5 hash 跟 anchor 完全一样 → centerShift 没生效，排查再继续。

## Return Layout

```
validation_results/custom_pp_gate_inputs/center_shift_sweep/
├── disguise_K1p3_centerShift_zero.exr
├── disguise_K1p3_centerShiftX_{n0p30,n0p50,p0p30,p0p50}.exr
└── disguise_K1p3_centerShiftY_{n0p30,n0p50,p0p30,p0p50}.exr
```

## 备注

- ±0.50 mm = 1.43% sensor 宽度偏移；K1=+0.3 anchor R 范围实测 [0.1338, 0.8657]，加 1.43% 应该不溢出 [0,1]。
- 渲完 ±0.50 没有大面积溢出（sanity check R/G 范围超出 [0,1] 的像素 < 1%），可补一组 ±1.0 mm 拿更干净的 mm/px 系数。
- d3 EXR 实测量化阶 = 1/2048（half-float 16-bit），KB 没看到 32-bit float 输出选项；如果 d3 端真有，渲 32-bit 比加大步长更优。
