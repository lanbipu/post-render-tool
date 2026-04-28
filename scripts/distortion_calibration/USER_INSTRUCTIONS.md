# Disguise 端 K-sweep 采集指引（Path A · UV 渐变 + 公式反推）

> **目的**：采集 11 张 transmission frame，用来反推 Disguise 的 distortion 公式
> （Path A · system identification）。详见 `docs/distortion-investigation.md`。

## 准备

- 探针图：`scripts/distortion_calibration/uv_probe_1920x1080.exr`
  - 1920×1080 32-bit float EXR，3 通道
  - R = (x + 0.5)/W、G = (y + 0.5)/H、B = 0（identity UV grid）
  - 每个像素自带源坐标真值，不需要角点检测
- d3 端：复用 image 44/45 用过的 stage、相机参数

## 关键约束

1. **必须 EXR 32-bit float**，不要 PNG / JPG / 16-bit half。
   - 8-bit 量化误差 ±7 px → 直接报废
   - 16-bit half 精度边缘约 0.03 px，理论够用但保险起见全用 float
2. **LED surface 必须 linear pass-through**：gamma=1.0、无 LUT、无 color grading、
   无 tone mapping。任何 R/G 通道的非线性映射会让源 UV 失真，公式拟合废。
3. **必须是 transmission compositor frame export**，不是 calibration overlay
   （后者是 inverse / undistortion 方向，方向反，已踩过坑）
4. **分辨率严格 1920×1080**，不要 resize / scale

## 步骤

1. **探针上 LED**：把 `uv_probe_1920x1080.exr` 加进 d3 textures / video assets，
   1:1 像素映射到 LED surface。
2. **相机不变**：用 image 44/45 完全相同的相机（FOV、principal、CenterShift=0）。
3. **每个 K1 渲一帧**：固定 K2 = K3 = 0、CenterShift = 0，K1 取以下 11 个值各
   渲一次 transmission compositor frame，导出 1920×1080 EXR：

   | K1 值 | 文件名 |
   |---|---|
   | 0.0 | `disguise_K_zero.exr` |
   | +0.1 | `disguise_K_p0p1.exr` |
   | +0.2 | `disguise_K_p0p2.exr` |
   | +0.3 | `disguise_K_p0p3.exr` |
   | +0.4 | `disguise_K_p0p4.exr` |
   | +0.5 | `disguise_K_p0p5.exr` |
   | −0.1 | `disguise_K_n0p1.exr` |
   | −0.2 | `disguise_K_n0p2.exr` |
   | −0.3 | `disguise_K_n0p3.exr` |
   | −0.4 | `disguise_K_n0p4.exr` |
   | −0.5 | `disguise_K_n0p5.exr` |

   命名约定：`p` = positive，`n` = negative，第二个 `p` 是小数点。

4. **回传**：把 11 张 EXR 放到 Mac 的 `/tmp/disguise_renders/`（或任意目录，
   跑分析时 `--input-dir` 指过去就行）。

## 注意

- **K1=0 是 sanity 帧**（不是必须，但**强烈推荐**）。它应该等于探针自身（identity
  UV grid），analyze_renders 会自动校验 R/G 通道的 max deviation。如果 deviation > 1%，
  说明 LED gamma 没关 / 走 transmission overlay / 某环节出问题，先排查再继续。
- 高 K 帧外圈像素会被推出帧 → R/G 通道为 0 → analyze_renders 自动过滤
  （`VALID_UV_MIN/MAX` 阈值）；中圈数据照常进入拟合。
- 如果 d3 LED surface **不能直接吃 EXR**，告诉我，我换成 16-bit linear PNG
  （精度损失约 0.03 px，理论够用）。

## 后续（用户不用做，回到 Mac 后我跑）

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python analyze_renders.py --input-dir /tmp/disguise_renders
.venv/bin/python fit_distortion_models.py
```

Analyze 会从每帧采 30k 像素 × 11 帧 = 330k 数据点（vs ChArUco 旧版 3k 数据点，
密度 100 倍）。Fit 输出会指向 BIC-best 模型 + 参数（M1/M2/M3/M4/M5）。

然后我把这个公式投影到 UE LensFile 的 polynomial 形态（K1/K2/K3），更新
`lens_file_builder.py`，重渲 → A/B 比对 → 残差应归零（如果 Disguise 用的就是
polynomial）或 best-fit 近似（如果不是）。
