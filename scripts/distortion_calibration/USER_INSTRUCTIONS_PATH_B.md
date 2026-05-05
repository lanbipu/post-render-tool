# Disguise 端 STMap 采集指引（Path B · 已搁置）

> **2026-05-05 状态**：⏸️ **搁置备胎，不再启用**。技术路径已转向
> **Path C · Custom Post-Process Material**（详见
> `docs/custom-postprocess-distortion-final-plan.md`）。
> 当前要做的 Disguise 端渲染清单是 16 张 Custom PP Gate Inputs，详见
> `USER_INSTRUCTIONS.md` 顶部的 **Round 3.0** 章节，或
> `docs/d3-distortion-render-request.md`。
>
> 本文档保留作 Path B 的参考说明：万一 Path C 端到端验证失败需要回退到
> STMap 字典法，再按这里的指引启动采集（同时启用
> `USER_INSTRUCTIONS.md` 里的 Round 2.3）。

> **目的（Path B 历史）**：用 Disguise 自己渲染一张已知输入图，输出直接当
> distortion STMap 用。一次出真值，绕开 K 公式拟合。详见
> `docs/distortion-investigation.md`。

## 准备

两个文件，**Mac 已经生成好**，等 session 时给你：

| 文件 | 角色 |
|---|---|
| `uv_probe_1920x1080.exr` | **主探针**：32-bit float 红绿渐变，渲染后输出就是 distortion STMap |
| `charuco_1920x1080.png` | **验证用**：渲染同一组 K，跟 uv_probe 比对方向 |

**d3 端**：复用生产用的 stage / 相机 / LED surface，K1/K2/K3/CenterShift 全部按
CSV 原值开着（不要清零，不要单变量扫描）。

## 操作

### Step 1 · 渲染 uv_probe（必做）

1. 把 `uv_probe_1920x1080.exr` 加进 d3 textures 或 video assets
2. 把它贴到生产用的 LED surface，**1:1 像素映射**
   - 不要走 mapper / warp / projection 变换
   - 不要走 color grading / LUT / tone mapping —— surface 必须 linear pass-through
3. 用生产同款相机渲染 transmission compositor frame
   - K / CenterShift 跟 CSV 原值一致
4. **输出 EXR 32-bit float**，不要 PNG / JPG（精度丢光就废了）
5. 命名：`disguise_uvprobe.exr`，回传 Mac 的 `/tmp/disguise_stmap/`

### Step 2 · 渲染 charuco（推荐做，方向验证）

同样 K + 同样相机，把内容换成 `charuco_1920x1080.png`，渲染 transmission frame。

- 这个允许 PNG（角点检测对量化误差不敏感）
- 命名：`disguise_charuco_atK.png`，放同一目录

## 注意

- **Surface pass-through 必须是 linear**。如果 d3 给 LED 的内容做了 gamma / sRGB
  转换，输出 EXR 里 R/G 通道就不再是原始 UV 坐标，STMap 直接报废。
  - 检查方式：在 d3 里把 surface gamma 设 1.0 / no color transform
  - 如果不确定，渲一帧没接 distortion 的 baseline frame 回传，Mac 端先验
    `output ≈ input`（最大差 < 0.001）再继续

- **必须是 transmission frame export，不是 calibration overlay**
  （overlay 是 inverse / undistortion 方向，方向反，CLAUDE.md 里踩过坑）

- **EXR 必须 32-bit float**（`PIXEL_TYPE = FLOAT`），不要 16-bit half。
  半精度 1/65000 量化对 1920px 横向 ≈ 0.03 px 误差，理论够用但保险起见全用 float

- **分辨率必须 1920×1080**，跟 LED transmission feed 一致；不要 resize / scale

- 如果 d3 LED surface 不接受 EXR 输入，告诉我，我换成 16-bit linear PNG（精度
  会损失少许但仍够用）

## 后续（用户不用做，Mac 端我跑）

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python build_stmap.py --input-dir /tmp/disguise_stmap
# 验证：output ≈ pixel-perfect identity（除 anti-aliasing 边缘）
# 写入 UE LensFile 走 unreal.LensFile.add_stmap_point 通道
```
