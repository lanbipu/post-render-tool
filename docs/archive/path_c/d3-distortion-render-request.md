# Disguise Render Request — 12 帧扩展版 normalization gate

> **EXECUTED 2026-05-07** — commit `f027a46`。12 帧 EXR 已渲完(focal_length_sweep
> 6 帧 + k2_k3_sweep 2 帧 + center_shift_sweep 4 帧),fit harness 已跑,结论:
>
> - **K1/K2/K3 normalization = full-width**(focal=30.302 K1_eff +0.5015,
>   focal=50 +0.5009,跨焦距 spread 0.0006);diagonal/height/half-width 候选是
>   full-width 真值的几何影子(影子定理预测精度 < 0.32%);focal-length 候选被
>   K_eff 跨焦距漂移 0.376→1.022 直接证伪。
> - **centerShift 公式漏一项 source UV 平移** — K=0+csx≠0 时 d3 把源 UV 平移
>   `-csx_uv`,shader 已修。
> - focal=24mm 帧因 over-scan margin≈0 数据剔除,30.302mm→50mm(1.65× 跨度)
>   足够定型。
>
> 完整 fit 报告:`validation_results/normalization_gate/20260507_150346_*`。
> take_5 静态帧 diff 后续验证(`validation_results/take_5_diff/summary.md`)
> 进一步坐实结论。

## 目的

Path C shader (`M_PRT_OfficialSensorInverse`) 当前用 sensor 全宽归一化(`r=(px-cx)/W`),这是从 normalization gate(`docs/distortion-investigation.md` § 2026-05-06)选出来的,但当时只排掉了半宽公式,**没排除焦距归一化(`r=(px-cx)/fx`)、对角线归一化、高度归一化等候选**——因为现有 take(take_4 / take_5)的镜头规格让 `fx ≈ W`,这些候选公式数值上重合,看不出差异。

production diff 已经在 take_4 上通过(commit `5f2fa2b`),但藏的二义性会在以下任一条件下暴露:

- 变焦镜头 take(focal 中途变化)
- fx 远离 W 的镜头(超长焦 / 广角 / 不同 sensor 规格)
- 大 K2 / K3 值 take
- centerShift 非零 take

这次请求的 12 帧 EXR 一次性把这 4 条潜在阻塞**全部用同一批数据反推证伪**:

| 维度 | 帧数 | 解决的问题 |
|---|---|---|
| 焦距 sweep × K1 | 6 帧 | focal-length 归一化二义性 |
| K2 单独 sweep | 1 帧 | K2 阶项是否跟 K1 同归一化 |
| K3 单独 sweep | 1 帧 | K3 阶项是否跟 K1 同归一化 |
| centerShift sweep | 4 帧 | centerShift 跨焦距 / 单位一致性 |
| **合计** | **12 帧** | |

## Global Settings(每帧统一)

- Plate: `scripts/distortion_calibration/uv_probe_3840x2160.exr`
- Output: `transmission frame`
- Format: **OpenEXR,32-bit float 优先**;half-float 仅在 32-bit 不可用时接受
- Resolution: `3840 × 2160`
- Lens over-scan: `1.5×`
- Color: linear,无 tone mapping / LUT / gamma / color management
- Scaling: 1:1 像素映射,不要 resize,不要额外 crop
- Sensor 宽高:跨 sweep 保持固定(focal 变,sensor 不变)
- Naming: 小写 `.exr`,正数用 `p`,小数点也用 `p`,负数用 `n`

## Required Set A — 焦距 sweep × K1(6 帧)

**目的**:分离 sensor 全宽归一化(A)、焦距归一化(B)、对角线归一化(D)、高度归一化(E)等候选。

每帧固定:

- `K2 = 0`,`K3 = 0`
- `centerShiftMM = (0, 0)`

| focal_length_mm | K1 | filename |
|---:|---:|---|
| 24.0 | 0.0 | `disguise_focal24_K1_zero.exr` |
| 24.0 | +0.5 | `disguise_focal24_K1_p0p5.exr` |
| 30.302 | 0.0 | `disguise_focal30p302_K1_zero.exr` |
| 30.302 | +0.5 | `disguise_focal30p302_K1_p0p5.exr` |
| 50.0 | 0.0 | `disguise_focal50_K1_zero.exr` |
| 50.0 | +0.5 | `disguise_focal50_K1_p0p5.exr` |

## Required Set B — K2 / K3 单变量 sweep(2 帧)

**目的**:验证 K2、K3 高阶项是否跟 K1 用同一种归一化。

每帧固定:

- `focal_length_mm = 30.302`
- `centerShiftMM = (0, 0)`

| K1 | K2 | K3 | filename |
|---:|---:|---:|---|
| 0 | +0.5 | 0 | `disguise_focal30p302_K2_p0p5.exr` |
| 0 | 0 | +0.5 | `disguise_focal30p302_K3_p0p5.exr` |

## Required Set C — centerShift sweep(4 帧)

**目的**:验证 `centerShiftMM` 单位 / 符号 / 跨焦距一致性。当前 Path C shader 公式:

```
CenterU = 0.5 + centerShiftMM.x / sensorWidthMM
CenterV = 0.5 + centerShiftMM.y / sensorHeightMM
```

是猜的,用真实数据反推。

每帧固定:

- `focal_length_mm = 30.302`
- `K1 = K2 = K3 = 0`
- `centerShiftMM.y = 0`(只 sweep x 方向)

| centerShiftMM.x | filename |
|---:|---|
| -0.10 | `disguise_focal30p302_csx_n0p10.exr` |
| -0.05 | `disguise_focal30p302_csx_n0p05.exr` |
| +0.05 | `disguise_focal30p302_csx_p0p05.exr` |
| +0.10 | `disguise_focal30p302_csx_p0p10.exr` |

## Return Layout

放置到:

```text
validation_results/disguise_next_data/
├── focal_length_sweep/        ← Set A,6 帧
│   ├── disguise_focal24_K1_zero.exr
│   ├── disguise_focal24_K1_p0p5.exr
│   ├── disguise_focal30p302_K1_zero.exr
│   ├── disguise_focal30p302_K1_p0p5.exr
│   ├── disguise_focal50_K1_zero.exr
│   └── disguise_focal50_K1_p0p5.exr
├── k2_k3_sweep/               ← Set B,2 帧
│   ├── disguise_focal30p302_K2_p0p5.exr
│   └── disguise_focal30p302_K3_p0p5.exr
└── center_shift_sweep/        ← Set C,4 帧
    ├── disguise_focal30p302_csx_n0p10.exr
    ├── disguise_focal30p302_csx_n0p05.exr
    ├── disguise_focal30p302_csx_p0p05.exr
    └── disguise_focal30p302_csx_p0p10.exr
```

## Quick Sanity Check

每帧拿到后跑一次确认通道范围正常:

```python
import os
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

import cv2

img = cv2.imread("disguise_focal30p302_K1_zero.exr", cv2.IMREAD_UNCHANGED)
print(img.shape, img.dtype)
print("R", float(img[..., 2].min()), float(img[..., 2].max()))
print("G", float(img[..., 1].min()), float(img[..., 1].max()))
```

`K=0` identity 帧(over-scan 1.5×)期望 R/G 范围接近 `[0.1667, 0.8333]`。

## 验收

数据到位后会跑 `scripts/distortion_calibration/fit_normalization_candidates.py`(待写),输入 12 帧 EXR + uv_probe plate,输出 `validation_results/normalization_gate/<timestamp>_fit_report.{json,md}`,每个候选公式(A/B/D/E…)的拟合残差 + 最终建议是否要改 shader 公式。

通过标准:

- 至少有一个候选跨 3 个焦距 + 跨 K1/K2/K3/centerShift 全部 sweep 的拟合残差接近 EXR 量化地板(亚像素)
- 该候选确定为 d3 真公式
- shader HLSL 直接换成对应公式(不建运行时切换开关)

如果所有候选残差都 > 5 px,需要扩展候选名单或改走 STMap 路径。
