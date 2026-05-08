# take_5 静态帧对比工作流

## 这条工作流要解决什么

之前 take_4 production diff 卡在"基准管道是不是 .seq feed"的疑点上。take_5
这条把变量收窄：

- **静态相机**：CSV 全程同一个机位，去掉 motion 变量
- **同套镜头校准**：K1/K2/K3/csx 跟 take_4 一致
- **干净基准**：Disguise Sequence Shot screenshot（≡ Transmission Frame 同管道）
  作参考 EXR，避开 .seq feed 的硬件信号链

跑出来的残差只反映 shader 公式本身，不夹带任何运动 / 信号链噪声。

## 数据源

```
validation_results/take_5_diff/
├── test_take_5.csv                     ← Disguise CSV(普通版)
├── test_take_5_dense.csv               ← Disguise CSV(dense 版,内容跟普通版一致)
└── reference/
    └── screen_mr_set_1_00000.exr      ← Disguise Sequence Shot screenshot
```

CSV 只有一个机位、两条数据行(frame 54304 / 54392 完全相同)。

## CSV 关键参数(只读这一行就够)

| 项 | 值 |
|---|---|
| Resolution | 1920 × 1080 |
| Position (Disguise) | x=0.5438, y=1.1070, z=−6.6509 |
| Rotation (Disguise) | x=359.243°, y=357.837°, z=358.050° |
| focal_length | 43.2886 mm |
| paWidth (sensor) | 50 mm |
| K1 / K2 / K3 | +0.000286 / −0.003953 / +0.011302 |
| centerShift X / Y | +0.004900 / +0.004673 mm |
| FOV (V / H) | 35.993° / 60.015° |
| Overscan | 1.3 × 1.3 → 2496 × 1404 |

## 参考 EXR 规格

| 项 | 值 |
|---|---|
| Shape | 1920 × 1080 × 4 (RGBA) |
| dtype | float32 |
| Range (R) | 0.2455 – 1.1016 |
| Range (G) | 0.2433 – 0.9600 |
| Range (B) | 0.3589 – 0.9570 |
| 渲染方式 | Disguise Sequence Shot (= Transmission Frame 同管道) |

## 对比流程

### 1. UE 端跑 pipeline

```python
# UE Editor Python console
from post_render_tool.pipeline import run_import
result = run_import(
    r"E:\…路径…\test_take_5_dense.csv",  # 或先 SCP 到 lanPC 本地
    fps=24.0,
)
```

CSV 同步到 lanPC P4 workspace 之后,从 UE Editor 跑一次:

- 走 Path C distortion(`M_PRT_OfficialSensorInverse` material)
- LensFile 仍生成但 dormant,不参与 distortion(详见 `camera_builder.py:218-226`)
- MRQ 渲一帧 EXR / PNG 输出到 `validation_results/take_5_diff/ue_out/`

### 2. 像素级对比

```python
import os
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2
import numpy as np

ref = cv2.imread(
    "validation_results/take_5_diff/reference/screen_mr_set_1_00000.exr",
    cv2.IMREAD_UNCHANGED,
)[..., :3]  # 丢掉 alpha
ue = cv2.imread(
    "validation_results/take_5_diff/ue_out/<filename>.exr",
    cv2.IMREAD_UNCHANGED,
)[..., :3]

diff = np.abs(ue.astype(np.float32) - ref.astype(np.float32))
print(f"RMS    : {np.sqrt((diff**2).mean()):.4f}")
print(f"median : {np.median(diff):.4f}")
print(f"p95    : {np.percentile(diff, 95):.4f}")
print(f"max    : {diff.max():.4f}")
```

## 验收门槛

| p95 | 含义 |
|---|---|
| < 0.02 | 亚像素级,公式正确 |
| 0.02 – 0.05 | 有小残差,可接受,等后续 K2/K3 单变量 sweep 收尾 |
| > 0.05 | shader 公式还有问题,需要回头查 |

通过(p95 < 0.05)→ 把 take_5 结果写进 `validation_results/take_5_diff/summary.md`,
作为新的 production baseline,take_4 production diff 残差问题搁置。

## Note

- CSV 只有 1 个机位,跑 UE pipeline 时 LevelSequence 会非常短。这次只关心**单帧
  几何对齐**,不用看 motion。
- 参考 EXR 文件名原本是 `screen_mr set 1_00000.exr`(带空格),SCP 过来已重命名
  为 `screen_mr_set_1_00000.exr`,免得后续脚本踩空格的坑。
- 镜头参数跟 take_4 完全一致 → 如果 take_5 通过、take_4 不通过,说明问题在
  motion 数据 / .seq feed 管道,跟 shader 无关。
