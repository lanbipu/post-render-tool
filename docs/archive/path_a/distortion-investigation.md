# Lens Distortion Investigation — 接力交班文档

> **状态**：Round 2.1 M_RAT6 系数已落地（commit `ecb997a`），production 精度 3.3× 改善。
> 下一步：lanPC UE Editor 端到端验证 production CSV。
>
> **2026-04-30 更新**：Round 2.1 完成 — 51 帧 4K + 1.5× over-scan K1 sweep → fit → 系数更新。
> Production |K1|≤0.1: RMS 1.09 px, max 3.5 px（vs Round 1 RMS 3.6 px, max 8.5 px）。
> 详见下方 §Round 2.1 进度。

## 目标

让 UE post_render_tool 渲染输出跟 d3 designer 端 compositor frame **逐像素一致**
（用户明确要求 pixel-perfect，不能接受残差）。

## 已知事实（commit 3468a67 落地）

| 已修 | commit |
|---|---|
| K3↔P2 数组槽位错位 | b6377e1 |
| zoom key 单位（应该 mm 不是归一化） | b6377e1 |
| evaluation_mode 默认 UseLiveLink → UseCameraSettings | b6377e1 |
| LensComponent 不 auto_activate（tick 不跑、MID 不挂） | d09cd84 |
| LensComponent.lens_model 没显式设 → handler 不创建 | d09cd84 |
| LensFile.LensInfo.lens_model 没写 | d09cd84 |
| K 系数方向（CSV K → UE K 要取反号 -K） | 3468a67 |

**这些修复的共同特点**：是 Bug，修了之后整条管线**通**。剩下的不是 Bug，是
**Disguise 跟 UE 的 distortion 数学模型本质不同**。

## K1 单变量扫描结果（今天做的）

Controlled experiment：相机不变，K2=K3=0，CenterShift=0，只调 K1：

| Disguise 端 K1 | UE 端最匹配的 K1 | scale factor |
|---|---|---|
| +0.5 | -0.75 | **1.5x** + 取反 |

差值图（用户在达芬奇做的 abs(A-B) 导出）显示残差**有结构性**：
- 画面中心区域几乎全黑 → K1=-0.75 在小 r 处匹配很好
- 画面边缘有红绿描边 → 大 r 处两边公式不一致
- 残差峰值在四角附近，~1-3 像素

**结论**：单一线性 scale factor (1.5x) 不能达到 pixel-perfect，因为两边
**polynomial 模型的高阶行为不同**。

## 关键资产 / 数据

### lanPC 上现有的

```
E:/temp/k_sweep_all/                          → 6 张 K1 sweep 图（已重命名 K1_neg_XpY.png）
  K1_neg_0p5.png   (UE K1=-0.5)
  K1_neg_0p75.png  (UE K1=-0.75)  ← 视觉最接近 Disguise K1=+0.5
  K1_neg_1p0.png
  K1_neg_1p5.png
  K1_neg_2p0.png
  K1_neg_3p0.png

E:/RenderStream Projects/test_0311/Plugins/post-render-tool/  → 主代码（P4 同步）

C:/temp/ue-remote/                            → Remote Execution bridge
  run_ue.py                                   → 接受文件路径参数，dispatch 到 UE
  diag*.py / sweep_*.py / probe*.py            → 历史诊断脚本（可参考）
```

### Mac 上现有的

```
/tmp/sweep_neg_*.png                         → 6 张 K1 sweep 图（缩略图缓存）
/tmp/ue_*.py                                 → 历史诊断脚本（可参考实现细节）
```

### Disguise 端（用户那边的）

- d3 designer 的 stage 测试场景：LED surface + 16:9 直线网格图 + Disguise camera 对准
- image 44：K1=K2=K3=0 / CenterShift=0 → 完美直线网格 ground truth
- image 45：K1=+0.5 / K2=K3=0 / CenterShift=0 → pincushion 单变量参考
- 差值图：K1=+0.5 (Disguise) - K1=-0.75 (UE) 的 abs diff，达芬奇导出

### UE LensFile 当前状态

```
LensFile 资产路径: /Game/PostRender/shot_1_take_13_dense/LF_shot_1_take_13_dense
当前内容：K1=-3.0, K2=K3=0, principal=(0.5, 0.5)  ← K1 sweep 最后一帧设置
```

**注意**：LensFile 处于"测试 mode"，**不是生产数据**。明天开始前先重跑
`run_import` 让它写回生产 K（CSV 原值 -K）。

## 明天接着做：两条路径

### 路径 A · 黑盒反推 Disguise 真实公式（System Identification）

通过密集采样 + 候选公式拟合，反推 Disguise 内部 distortion 公式。

**实验设计**：
1. 选 5 个 r 位置（0.1、0.2、0.3、0.4、0.45）× 5 个 K 值（0.1、0.2、0.3、0.4、0.5）
2. 每个 (r, K) 组合：在 Disguise 端 controlled 渲染棋盘格 → OpenCV `findChessboardCornersSB`
   亚像素角点检测 → 测量 Δr(r, K)
3. 拟合候选公式：
   - Polynomial: `r·(1 + K·r²)` ← UE 当前用的
   - Division: `r/(1 + K·r²)`
   - Modified polynomial: `r·(1 + α·K·r²)` 含 scale α
   - 高阶 polynomial: `r·(1 + K·r² + β·K²·r⁴)`
   - 不同归一化的 polynomial: `r·(1 + K·(r/α)²)`
4. 拟合误差最小的 = Disguise 真公式
5. 在 UE 用 Newton 迭代精确反算

**优点**：找到真公式后能 closed-form 解决，所有 K 值自动正确。
**缺点**：~1 个工作日实验 + 拟合，依赖 Disguise 用确定性公式（不是查找表）。

### 路径 B · 棋盘格 → STMap（Black-box Direct Solve）

不管 Disguise 内部公式是什么，直接构造每像素位移真值。

**Disguise 没原生 STMap export，但可以这么干**：

1. **生成精密棋盘格 PNG**（Python/PIL 程序生成，比如 19×11 格子，角点位置精确到 0.0 像素）
2. **Disguise 端**：把棋盘格放到 LED surface → 设置 K（CSV 原值或单变量都行）→ 渲染 transmission frame → 导出
3. **OpenCV 角点检测**：`cv::findChessboardCornersSB` + `cornerSubPix` → 得每个角点亚像素位置
4. **配对**：(原棋盘格已知位置) ↔ (Disguise 渲染后位置) → 一组稀疏 displacement
5. **稀疏 → 稠密**：用 RBF / thin-plate spline 插值到全画面每个像素都有 displacement
6. **写入 UE LensFile**：用 `add_stmap_point` API（UE 5.7 LensFile 原生支持 STMap 表）

**关键 UE API**（待验证具体调用形式）：
- `unreal.LensFile.add_stmap_point(focus, zoom, undistortion_stmap, distortion_stmap)`
- 或用 `set_lens_data_table` 等

**优点**：完全绕开数学公式问题，pixel-perfect 直接达成。
**缺点**：每个 K 设置需要单独一张 STMap（不能像公式一样跨 K 通用）。
但因为我们做 post-render，一个 take 一组 STMap 也合理。

### 我推荐的执行顺序

**先做路径 B（STMap）**——不依赖任何假设，直接给出 pixel-perfect 结果。先把
"能做到 pixel-perfect"这件事落地，再考虑后续优化。

如果路径 B 不通（UE LensFile API 不支持 STMap 写入或别的卡点），再做路径 A。

### 2026-04-28：用户决定走 Path A（覆盖上面的推荐）

理由由用户掌握。Path A 的 Mac 端工具链已落地。

**第一版（已废弃）**：标准棋盘格（17×9 × 64 px，128 角点，r_max=0.55）。
用户指出"四周白边浪费空间"，重新审视后发现根本约束是
`findChessboardCornersSB` 全或无检测：K=+0.5 pincushion 把外圈角点推出帧 →
整张图检测失败。**plain chess 不能铺满全帧**。

**最终版：ChArUco**（2026-04-28 切换）：

- `charuco_1920x1080.png`：DICT_5X5_250 字典，24 cols × 13 rows × 80 px squares，
  marker 48 px（60% 比例，留 16 px 角点周围空白给 cornerSubPix），垂直留 20 px 白边。
- **23 × 12 = 276 内角点，r 覆盖 0.04 ~ 1.03**（几乎全帧）。
- 每个角点自带 ChArUco ID —— 部分检出可用、不依赖拓扑、抗 tangential。
- cornerSubPix 自定义 winSize=(11,11) 提升单点精度从默认的 0.05-0.10 px 到 0.02-0.05 px。
- CharucoParameters 调参：`checkMarkers=False`（绕过 quadrilateral integrity check，
  在 K=-0.5 重 barrel 下 markers 会被压扁但 hamming distance 仍可识别）、
  `minMarkers=1`（让外圈只有 1 个邻 marker 的角点也能插值）。
- `generate_charuco_board.py` → `analyze_renders.py` → `fit_distortion_models.py`
  端到端跑通；3 个 self-test 全过：
    - 角点检测 RMS = 0.0000 px（无噪声 reference 完全归零）
    - 合成 K=±0.3 畸变反测：K=-0.3 inner_rms 0.33 px、K=+0.3 inner_rms 0.06 px
      （median 都在 0.05-0.10 px；max 偶尔 8 px 是 cv2.remap LANCZOS4 在外圈
      severely-aliased markers 上 cornerSubPix 飘的合成 artifact，不是真实 pipeline 问题）
    - synthetic α=1.5 polynomial + 0.5 px 噪声拟合，BIC 选回 M1，α 反推 1.5005
- 拟合候选模型 5 个（M1 polynomial / M2 division / M3 mixed-K-order / M4 free radial
  exponent / M5 OpenCV K1-only style），全局对所有 (K, r, dr) tuple 联合拟合，
  自带 robust outlier 过滤（trim top 5% residuals 在 baseline M1 fit 之后），
  按 RMS + **BIC**（带复杂度惩罚）双排序——避免 M3/M5 这种含 M1 作为特例的过拟合
  candidate "白白胜出"。
- venv 隔离在 `scripts/distortion_calibration/.venv/`（cv2 4.13、scipy、numpy、Pillow），
  跟项目 UE Python 互不干扰。

接下来等用户：

1. 把 `charuco_1920x1080.png` 上 LED（1:1 像素，不要 resize）**或直接 mapping 到
   d3 相机的 image overlay**（后者推荐，外圈数据更全，不被 LED 边缘问题污染）
2. 用 image 44/45 那个相同相机
3. 渲 11 张 transmission frame：K1 ∈ {0, ±0.1, ±0.2, ±0.3, ±0.4, ±0.5}，
   K2 = K3 = 0，CenterShift = 0
4. 命名照 `disguise_K_zero.png` / `disguise_K_p0p3.png` / `disguise_K_n0p3.png`
   (`p`=positive、`n`=negative，第二个 `p` 是小数点)
5. 放 `/tmp/disguise_renders/`

详细步骤见 `scripts/distortion_calibration/USER_INSTRUCTIONS.md`。

收到后跑：

```bash
cd scripts/distortion_calibration
.venv/bin/python analyze_renders.py --input-dir /tmp/disguise_renders
.venv/bin/python fit_distortion_models.py
```

输出会指向 BIC-best model + 参数。然后把这个公式注入 `lens_file_builder.py`
（可能需要 Newton 迭代反算把 Disguise forward 变成 UE 期望的 K1/K2/K3 三阶
polynomial 系数；或者直接在 lens_file_builder 里换一套公式生成 distortion table）
→ 重渲 → 跟 Disguise 端 A/B → 残差应该 ≈ 全黑。

**附记 K2/K3**：本轮工具只测 K1（K2=K3=0 sweep）。等 K1 公式确认后，再决定是否
做第二轮 K2 sweep + 第三轮 K3 sweep + 第四轮联合验证。如果 K1 sweep 直接
证明 Disguise 是标准 OpenCV polynomial（M5 胜出且 a≈1, b≈0, c≈0），那 K2/K3
大概率自动正确，只需联合验证 5 帧；否则还需 ~12 帧扫 K2/K3 形态。

## 路径 B 的明天第一步

明天 session 开始就这么干：

```python
# 1. 生成棋盘格（Mac 上跑）
# /tmp/checkerboard_1920x1080.png — 19×11 格子，黑白棋盘，pixel-precise corners

# 2. 把棋盘格发给用户，让用户：
#    - 在 d3 designer 里把它放到 LED surface（textures 或 video assets）
#    - 用 image 44/45 那个相同相机对准
#    - 用 image 45 那个相同 K（K1=0.5/K2=K3=0/CenterShift=0）渲染 transmission frame
#    - 把渲染结果发回 Mac

# 3. Mac 上跑 OpenCV：
import cv2
import numpy as np

source = cv2.imread('/tmp/checkerboard_1920x1080.png', cv2.IMREAD_GRAYSCALE)
rendered = cv2.imread('/tmp/disguise_K1_0p5_render.png', cv2.IMREAD_GRAYSCALE)

# 已知棋盘格规格
pattern_size = (18, 10)  # 19×11 格 = 18×10 内角点

# 检测两边角点
ret_s, corners_s = cv2.findChessboardCornersSB(source, pattern_size)
ret_r, corners_r = cv2.findChessboardCornersSB(rendered, pattern_size)
# Refine to subpixel
criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
corners_s = cv2.cornerSubPix(source, corners_s, (5,5), (-1,-1), criteria)
corners_r = cv2.cornerSubPix(rendered, corners_r, (5,5), (-1,-1), criteria)

# 现在 corners_s[i] 和 corners_r[i] 是配对的（原始 vs 渲染后位置）
# displacement[i] = corners_r[i] - corners_s[i]

# 4. 插值成 dense STMap（用 scipy thin-plate spline）
from scipy.interpolate import Rbf

# 5. 写 STMap 到 UE LensFile（需要先确认 UE 5.7 Python API 支持哪种 STMap 写入）
```

## 命令快速复用

### Remote Execution（已就绪）

```bash
# 测试连接
echo 'import unreal; print("hello")' | ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py'

# 执行任意脚本
scp /tmp/your_script.py lanpc:C:/temp/ue-remote/your_script.py
ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/your_script.py'
```

### 重置 LensFile 到生产模式（明天先做）

```bash
# 让用户在 UE Editor 里 hot-reload + 重跑 import
# 或者通过 RE 让代码重新执行 run_import
```

## 还要做的（继任清单）

- [ ] 路径 B 第一步：生成棋盘格 PNG，发给用户
- [ ] 路径 B 第二步：用户 d3 端渲染对照
- [ ] 路径 B 第三步：OpenCV 角点检测 + STMap 构造
- [ ] 路径 B 第四步：UE LensFile STMap 写入 API 调研 + 实现
- [ ] 路径 B 第五步：渲染验证 → 跟 Disguise 端做 diff，应该 ≈ 全黑
- [ ] CenterShift 单变量验证（task #7，还没做）
- [ ] 如果路径 B 不通，回退路径 A

## 投入历史回顾（避免重复踩坑）

**注意：跟 Disguise 端 K 系数对照实验时，不要被 d3 designer 里的
calibration overlay 误导**。Calibration overlay 显示的是 inverse / undistortion grid，
方向跟 compositor 实际输出相反。判断真实方向必须用 transmission feed 的
"export compositor frame"——这是 d3 真正应用 K 后送出去的画面。

**不要做的**：
- 不要再做"Taylor 反演近似"了——那个数学上 0 阶近似就是单纯 -K，
  高阶反而把 K2/K3 削得更小，跟 Disguise 强度差更大
- 不要在不知道目标的情况下盲目"调 K scale factor"——已经验证 1.5x 有结构性残差
- 不要再说"够用了"——用户标准是 pixel-perfect

**继任 session 第一句话**：
> 你好，正在交接 distortion 调试。先读 docs/distortion-investigation.md。
> 当前状态：commit 3468a67 完成 -K 取反，UE 端跟 Disguise compositor 视觉
> 95-98% 匹配，还差最后 1-3 像素残差。今天确认了 1.5x 单一 scale factor
> 不能 pixel-perfect，明天走 STMap 路径（路径 B）从棋盘格反推每像素位移。

---

## 2026-04-28（晚）：用户改回 Path B + UE LensFile STMap API 完成调研

> 上面 4-28 决定走 Path A 的笔记不删除，留作历史。当前最新决策：**用 Path B**，
> 用 UV 渐变图代替棋盘格做密集位移测量。Path A Mac 端工具链保留为 fallback。

### 关键决策：用 UV 渐变图代替棋盘格

棋盘格法只有 ~200 个稀疏角点，靠 RBF / TPS 插值到 200 万像素，引入额外插值误差。
**UV 渐变图法**：把 identity STMap 自身（红绿渐变图）扔到 LED，Disguise 渲染后输出
直接就是 distortion 真值，不需要插值。

实施细节：
- 探针文件：`scripts/distortion_calibration/uv_probe_1920x1080.exr`
  （32-bit float，R=(x+0.5)/W、G=(y+0.5)/H、B=0；pixel-center 约定）
- 必须 EXR 32-bit float，不能 PNG 8-bit（量化误差 ±7 px）
- LED surface 必须 linear pass-through（无 gamma / LUT），否则 R/G 通道废
- 必须 transmission compositor frame export（不是 calibration overlay，方向反）
- ChArUco 板（`charuco_1920x1080.png`）保留作为方向验证副本
- 用户操作指引：`scripts/distortion_calibration/USER_INSTRUCTIONS_PATH_B.md`

### B4 调研结论：UE 5.7 LensFile STMap API（已验证）

**UFUNCTION**：`ULensFile::AddSTMapPoint(float NewFocus, float NewZoom, const FSTMapInfo& NewPoint)`
（LensFile.h:190-191）→ Python: `lens_file.add_stmap_point(new_focus, new_zoom, new_point)`。
存在调用范例：`SLensDataAddPointDialog.cpp:876`。

**FSTMapInfo 结构**（LensData.h:194-206，BlueprintType）：
- `DistortionMap: TObjectPtr<UTexture>`  ←  4 通道 RGBA 纹理
- `MapFormat: FCalibratedMapFormat`       ←  通道布局元数据

**FCalibratedMapFormat 默认值**（CalibratedMapFormat.h:32-48）：
- `PixelOrigin = TopLeft`
- `UndistortionChannels = RG`  ← 默认 R/G 是 undistortion direction
- `DistortionChannels = BA`    ← 默认 B/A 是 distortion direction

**Shader 语义**（DistortionSTMapProcessor.usf:32-61）确认：
- 在均匀 UV grid 上采样 STMap 纹理
- `RG` 槽 → 在 distorted 输出 pixel 位置上，给出 undistorted 源 UV
- `BA` 槽 → 在 undistorted CG pixel 位置上，给出 distorted 输出 UV
- 输出 displacement = 采样值 - 当前 UV

**关键洞察**：Disguise 渲染我们的 identity-UV 探针时，输出 R/G 直接就是 UE 期望的
**undistortion direction**（在 distorted 像素位置看 undistorted 源在哪）。
distortion direction（在 undistorted 像素位置看 distorted 输出在哪）需要做 inverse
interpolation（输入空间在 undistorted UV 上不是均匀分布），结果存到 B/A。

**纹理导入**：`unreal.AssetImportTask` + `AssetTools.import_asset_tasks()` 走 EXR
（UE 内置 ExrImageWrapper 支持），产生 UTexture2D 资产。然后构造 `unreal.STMapInfo()`
赋 `distortion_map = texture`，MapFormat 走默认。

### Mac 端 STMap 构造（已落地）

`scripts/distortion_calibration/build_stmap.py`：
- 输入：3 通道 EXR（Disguise 渲染产物）
- 输出：4 通道 BGRA EXR
  - cv2 storage [B, G, R, A] = [distortion_U, undistortion_V, undistortion_U, distortion_V]
  - EXR 内部按通道名存（A/B/G/R），UE 按名读取，不需要 RGBA reorder
- 距离方向通过 `scipy.interpolate.griddata` cubic 反插（NaN 区域 nearest 兜底）
- 自带 sanity report（avg / max 像素误差 vs identity）
- `_self_test_stmap.py` 合成 K=0.3 barrel 验证：in-frame 64% 区域内 max 0.7 px、avg 0.0 px

### UE 端 STMap 写入（已落地，待远程实测）

`Content/Python/post_render_tool/stmap_writer.py`：
- `add_stmap_to_lensfile(lens_file_path, stmap_exr_path, focus=0, zoom=0, ...)`
- 经 `AssetImportTask` 导入 EXR → UTexture2D
- 构造 `unreal.STMapInfo()`，`distortion_map = texture`，MapFormat 用默认
- `lens_file.add_stmap_point(new_focus, new_zoom, new_point=info)`
- `EditorAssetLibrary.save_loaded_asset(lens_file)` 持久化
- AST 语法已通过；`unreal` 调用形式待 lanPC 远程实测确认（`unreal.STMapInfo` /
  `unreal.CalibratedMapFormat` 是否完整暴露字段，以及 `add_stmap_point` 的关键字
  参数名是否与 `add_distortion_point` 同款）

### 当前 Path B 进度清单

- [x] B1：生成 UV 渐变探针 EXR（`generate_uv_probe.py` + EXR roundtrip 0 误差）
- [x] B4：UE 5.7 LensFile STMap API 调研 + 路径文档化
- [x] B3：Mac 端 STMap 构造工具（`build_stmap.py` + 合成自测）
- [x] B5 雏形：UE 端写入脚本（`stmap_writer.py`，待远程实测）
- [ ] B2：用户在 d3 端渲两帧 transmission frame 回传
- [ ] 远程实测 B5：lanPC 上跑 import + add_stmap_point，验证 API 形参
- [ ] 闭环验证：UE 渲染同帧 → 跟 Disguise transmission frame diff，应 ≈ 全黑

---

## Round 2.1 进度记录（2026-04-30）

### 完成的工作

1. **51 帧 4K EXR 数据采集** — Disguise lens over-scan 1.5×，K1 ∈ {-0.50, ..., +0.50} 步进 0.02
   - 存放位置：`/Volumes/Docs/temp/k_sweep/`（已重命名为项目命名规范 `disguise_K1_*.exr`）
   - Over-scan 检测：factor=1.505×，margin=0.1677（理论 1/6=0.1667，偏差 0.001）
   - R/G 反仿射补偿自动应用

2. **analyze_renders.py 运行** — 100k samples/frame × 50 non-zero 帧 = 5M rows
   - 输出：`/Volumes/Docs/temp/k_sweep/displacements.csv`（467 MB）

3. **fit_distortion_models.py 运行** — 13 候选模型
   - BIC 最优：**M_RAT8**（-70.99M，RMS 1.091 px，max 4.426 px）
   - 次优：**M_RAT6**（-70.62M，RMS 1.135 px，max 5.786 px）
   - M_RAT8 有 r⁸ 项，但 UE BrownConradyUDLensModel shader 只有 K1-K6 槽位 → **无法部署**
   - **M_RAT6 是能完整映射到 UE shader 的最高阶 rational 模型**

4. **distortion_math.py 系数更新**（commit `ecb997a`）
   - Round 1 旧系数：a=-3.18, b=+7.24, c=+5.12, d=-2.93, e=+6.31, f=+7.51
   - Round 2.1 新系数：a=+602.26, b=+812547.18, c=+395029.04, d=+602.67, e=+814809.12, f=+601028.79
   - 绝对值很大是 r 扩展到 1.33（over-scan）的数值现象，num/den 近似抵消后净效果跟 Round 1 类似
   - Production K1≈3e-4 时 M_RAT6 项贡献 sub-1e-7，主导项仍是 legacy K2/K3 sign-flip

5. **Tier 1 验证**（通过）
   - 无极点（min denominator 0.89 @ K=-0.5, r=0.03）
   - Production K1=3e-4：dr sub-1e-4，行为正常

6. **Tier 2 验证**（production 范围通过，极端 K 有退化）
   - Production |K1|≤0.1：RMS **1.09 px**，max **3.5 px**（Round 1: RMS 3.6 px, max 8.5 px → **3.3× 改善**）
   - Full K∈[-0.5,0.5]：RMS 1.9 px，max 39.5 px（K=-0.5 极端帧外圈，production 不会遇到）
   - 验证对比图：`scripts/.../mrq_v2_r21_validation.png`

### 关键数据对比

| 指标 | Round 1 (1080p) | Round 2.1 (4K) | 改善 |
|---|---|---|---|
| Production RMS | 3.6 px | 1.1 px | 3.3× |
| Production max | 8.5 px | 3.5 px | 2.4× |
| Fit data量 | 300k (11 帧) | 5M (50 帧) | 17× |
| r 范围 | [0, 1.0] | [0, 1.33] | 33% 扩展 |

### 明天要做

- [ ] **lanPC UE Editor 端到端验证**：用真实 production CSV 跑完整 pipeline（parse → transform → LensFile → render），跟 Disguise 直渲帧 diff
- [ ] **如果端到端残差仍 > 2 px**：排查是 K1 M_RAT6 残差还是 K2/K3 sign-flip 误差，决定是否需要 K2/K3 sweep
- [ ] **更新 distortion-precision-analysis.md**：加入 Round 2.1 的实际精度档次定位
- [ ] **如果精度满意**：更新 `docs/K1-implementation.md` 加 Round 2.1 章节，关闭 distortion 调试

### 注意事项

- fit 报告的 "max 5.786 px" 是 **5% robust trim 后**的指标；全量数据 max 39.5 px（K=-0.5 极端帧）
- Over-scan margin 精度 0.1677 vs 理论 0.1667 → 引入 ~5 px 系统性 scale 误差（K=0 帧）
- 这个 scale 误差对 production（K1≈3e-4）无影响（M_RAT6 项贡献 sub-1e-7）

## 2026-05-06 — Normalization Gate

Ran K1+K2+K3 sweep against `(forward, full-width) / (forward, half-width) / (division, full-width)` candidates with delta-residual scoring. Report: `/Volumes/Docs/temp/k_sweep/gate6_compare.md`.

**Per-axis p95 (delta_residual) across all sweep frames:**

| axis | full-width / forward | half-width / forward | full-width / division |
|---|---:|---:|---:|
| K1 | 1.522 | 708.874 | 26.800 |
| K2 | 1.975 | 926.000 | 2.611 |
| K3 | 1.739 | 986.715 | 1.744 |

**Verdict:**

1. Normalization: **full-width wins — confident.** Ratio over half-width: K1 ×466, K2 ×469, K3 ×567. The half-width candidate (r = (px−cx) / (W/2)) blows up because d3 uses full-image-width normalization; the half-width factor double-counts the radius and the error scales linearly with |K|. No ambiguity.

2. Formula (within full-width normalization): **forward wins — confident on K1, borderline on K2/K3.** K1 ratio forward/division = 1.522 / 26.800 = ×17.6 (confident). K2 ratio = 1.975 / 2.611 = ×1.32 (borderline). K3 ratio = 1.739 / 1.744 = ×1.003 (effectively tied — within quantization noise). Division formula degrades badly at high K1 because the denominator `1 + K·r²` moves far from 1, but K2/K3's narrower sweep range keeps both candidates in similar territory. Forward is the safer lock across all axes.

**Implications for shader landing (`Content/Python/post_render_tool/distortion_math.py`):**

- Current `distortion_math.py` uses **half-width** normalization (`r = (px - cx) / (W / 2)`). This is the losing candidate by ×466–567×. Switch to **full-width** with **isotropic** divisor — both axes divided by image full width `W`, not by their own dimension: `r_x = (px - cx) / W`, `r_y = (py - cy) / W`. In UV form (UV ∈ [0, 1]): `r = (d.x, d.y / aspect)` where `d = UV - (CenterU, CenterV)`. This is the split-brain Codex flagged earlier — the shader and d3 are computing different radii, which is the dominant source of residual error.
- The existing forward dispatch (`displacement = K · r² · r_vec`) can be retained. Division formula does not show an advantage and degrades at moderate-to-high K1.
- Priority order: fix normalization first (highest-impact), then re-evaluate formula if residual is still above floor.

**Caveats still in play:**

- focal-length normalization confound (Codex P2 #6) — not addressed by this gate; would require new d3 renders at different focal lengths to disambiguate `r=(px-cx)/W` vs `r=(px-cx)/fx` when `fx ≈ W`.
- Half-float quantization floor (~3 px residual) — limits absolute accuracy. This gate compares candidates relative to the floor, not as absolute measurements. Sub-pixel residuals require either 32-bit float EXR (unavailable per KB search) or structured-light probes.
- Plan's acceptance threshold `p95 < 1.5 px` is **not** met by any axis: K1 narrowly misses by 0.022 px (1.522 vs 1.5) — plausibly quantization-floor limited; K2 (1.975) and K3 (1.739) sit above. Expected — driven by half-float quantization floor, not by candidate choice. Releasing this threshold or moving to 32-bit/structured-light data is what would change verdict.

接下来阻塞在 B2（等用户在 d3 端渲帧）。Mac 与 UE 两端工具链已经准备就绪。

## 2026-05-06 — Path C UE MRQ Validation

This section supersedes the earlier "UE render still blocked" state for Path C.
The headless non-null `UnrealEditor-Cmd.exe` path still fails at D3D12 swapchain
creation on lanPC, but the already-open UE Editor remote execution path completed
the validation render.

**Evidence:**

- Material asset readback: `validation_results/path_c_material_readback/material_custom_nodes.csv`
- Summary matrix: `validation_results/path_c_validation/path_c_validation_summary.md`
- MRQ dispatch report: `validation_results/path_c_validation/path_c_mrq_render.json`
- Render outputs:
  - `validation_results/path_c_validation/renders/path_c_identity.png`
  - `validation_results/path_c_validation/renders/path_c_k1.png`
  - `validation_results/path_c_validation/renders/path_c_k2.png`
  - `validation_results/path_c_validation/renders/path_c_k3.png`

**Validated facts:**

1. `.uasset` HLSL readback is direct UE asset evidence, not `set_editor_property()`
   inference. `OfficialSensorInverse` contains:
   `float2 r = float2(d.x, d.y / Aspect);`
2. `PostRenderDistortionControllerComponent` binding passed in both `-nullrhi`
   transient smoke and open-Editor actor-spawn smoke.
3. MRQ rendered the dedicated `PathCValidation_*` test assets in the open UE Editor.
4. `DistortionWeight=0` identity self-reference compare is exactly zero:
   `valid_p95=0`, `rms=0`, `valid_mask_mismatch_ratio=0`.
5. K-axis geometry checks use `official_sensor_inverse_uv` against the UE identity
   render as `reference_base`, which cancels UE texture import / PNG / tonemapping
   color transforms. Valid-region `p95` channel diffs:

| case | valid_p95 | valid_rms | valid_mask_mismatch_ratio |
|---|---:|---:|---:|
| K1=+0.5 | 0.003921568 | 0.005035542 | 0.000497565 |
| K2=+0.5 | 0.003837347 | 0.005302472 | 0.000602334 |
| K3=+0.5 | 0.003404558 | 0.005680670 | 0.000576895 |

**Caveat:**

These MRQ compare metrics are normalized channel absolute differences in `[0,1]`,
not pixel displacement in px. Because the current MRQ evidence is 8-bit PNG and
the direct EXR source-vs-UE compare exposes render-pipeline color transforms, this
is a Path C shader geometry validation against the UE identity floor, not a final
sub-pixel production-frame calibration claim.

**Status:**

- Path C UE material/controller/render harness: **PASS** for geometry validation.
- Headless non-null RHI commandlet: **environment blocker only**, superseded by
  open UE Editor MRQ for this validation.
- Path A residuals remain legacy half-width evidence and must not be used as
  Path C shader correctness evidence.
- Next d3 data request is no longer the old centerShift blocker set. Use
  `docs/d3-distortion-render-request.md` for focal-length sweep data to resolve
  the remaining sensor-full-width vs focal-length normalization confound.
