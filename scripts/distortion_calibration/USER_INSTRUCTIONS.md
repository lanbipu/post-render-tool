# Disguise 端 ChArUco 采集指引（Path A）

> **目的**：采集 11 张 transmission frame，用来反推 Disguise distortion 公式（Path A
> system identification）。详见 `docs/distortion-investigation.md`。

## 准备

- 标定图：`scripts/distortion_calibration/charuco_1920x1080.png`
  - 1920×1080 灰度，ChArUco 板（DICT_5X5_250 字典）
  - 24 cols × 13 rows × 80 px squares，板覆盖 1920 × 1040，垂直留 20 px 白边
  - **每个白方块里嵌一个唯一 ID 的 5×5 ArUco 标记** —— 角点检测自带 ID，部分检出依然能用
  - 23 × 12 = **276 个内角点**，r 范围 0.04 ~ 1.03（覆盖几乎全帧）
- d3 端：复用 image 44/45 用过的 stage、相机参数

## 关于"贴 LED" vs "直接 mapping 到相机"

两种方式都可以，**都用同一个 PNG**。看你 d3 端哪种好操作：

- **贴 LED surface**（你之前用的）：把 PNG 加进 textures / video assets，1:1 铺到 LED 上；相机对准 LED 渲。需要保证 LED 在画面里铺满（边角不要有黑或漏出）。
- **直接 mapping 到相机**（今天讨论的新办法）：把 PNG 当 d3 相机的 image overlay / camera input，让 distortion 直接作用在整张 PNG 上。**外圈数据更全**，推荐用这个。

## 渲染

固定 K2 = K3 = 0、CenterShift = 0，K1 取以下 11 个值各渲一次 transmission compositor frame，导出 1920×1080 PNG（不要 jpg、不要色彩转换、不要 resize）：

| K1 值 | 文件名 |
|---|---|
| 0.0 | `disguise_K_zero.png` |
| +0.1 | `disguise_K_p0p1.png` |
| +0.2 | `disguise_K_p0p2.png` |
| +0.3 | `disguise_K_p0p3.png` |
| +0.4 | `disguise_K_p0p4.png` |
| +0.5 | `disguise_K_p0p5.png` |
| −0.1 | `disguise_K_n0p1.png` |
| −0.2 | `disguise_K_n0p2.png` |
| −0.3 | `disguise_K_n0p3.png` |
| −0.4 | `disguise_K_n0p4.png` |
| −0.5 | `disguise_K_n0p5.png` |

命名约定：`p` = positive，`n` = negative，第二个 `p` 是小数点（避免 `+`/`.` 在路径里出问题）。

**回传**：把 11 张 PNG 放到 Mac 的 `/tmp/disguise_renders/`（或者任意目录，跑分析时 `--input-dir` 指过去就行）。

## 注意

- ChArUco 板**必须 1:1 像素**——任何缩放都会让角点位置不准、ArUco ID 解码不出来、污染拟合。
- **K1=0 是 anchor，必须存在**——没它拿不到 dr 基线。
- transmission frame 是 d3 真正应用 K 后送 LED 的画面，不是 calibration overlay
  （后者方向反，已经踩过坑）。
- 高 |K| 帧外圈角点会被裁掉是预期的（K=+0.5 大概丢 30-80 个外圈点），ChArUco 自带 ID 让中圈角点照常可用，不会污染数据。
- 如果某帧整张都解码失败，会被忽略并报警告，其余帧照常进入拟合。

## 后续（用户不用做，回到 Mac 后我跑）

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python analyze_renders.py --input-dir /tmp/disguise_renders
.venv/bin/python fit_distortion_models.py
```

输出会告诉我 Disguise 真实公式是 M1/M2/M3/M4/M5 哪一个，对应参数也会打出来（按 BIC 排序，自带 robust outlier 过滤）。然后我再把这个公式注入 `lens_file_builder.py`，重新写 LensFile，跟 Disguise 端做 A/B 比对，检查残差是否归零。
