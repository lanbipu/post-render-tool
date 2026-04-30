# Disguise 端 K-sweep 采集指引（Path A · UV 渐变 + 公式反推）

> **目的**：采集 transmission frame 反推 Disguise 的 distortion 公式（Path A ·
> system identification）。详见 `docs/distortion-investigation.md` 与
> `docs/distortion-precision-analysis.md`。
>
> 当前状态：
> - ✅ **Round 1 · K1 sweep（11 帧 1080p）已完成**（commit `0019ad3`）
>   - M_RAT6 rational 反推 + UE BrownConradyUDLensModel 落地 + Tier 1/2 验证全过
>   - 外圈 edge max 122 → 3.2 px（38× 改善）
>   - 但 fit residual 0.4 px ≈ noise floor、K=±0.5 测试边缘仍 max 3.2 px → **VFX 入门档次**
> - ⏳ **Round 2.0 · 高密度 4K K1 sweep（51 帧）已尝试，发现 K1>0 黑边问题**
>   - 跑完后 K1- 帧干净 (max ~3 px @ 4K), K1+ 帧 max 76-97 px
>   - 根因：K1>0 的枕形畸变把源像素拉到 LED 屏幕外面 (即源 UV 出 [0,1] 边界)，Disguise 在那些像素吐 fallback 脏数据
> - ⏳ **Round 2.1 · 1.5× over-scan K1 sweep（51 帧）下一步要做** ← **本文档当前指引**
>   - 探针 + 渲染分辨率从 3840×2160 改 **5760×3240** (1.5× over-scan)
>   - K1>0 时源像素仍落在 LED 范围内, 黑边问题消除
>   - 先做 K1 sweep 一轮验证, 通过后再考虑 K2/K3
>   - PostRenderTool 用户接口零变化，仅后端 `distortion_math.py` 系数更新

---

## 工作流通用准备（适用所有轮次）

### 探针图

**Round 1（旧）**：`scripts/distortion_calibration/uv_probe_1920x1080.exr`（1080p）
**Round 2.0（已用过, 4K 直渲, 黑边问题）**：`scripts/distortion_calibration/uv_probe_3840x2160.exr`
**Round 2.1（新, 1.5× over-scan, 当前指引）**：`scripts/distortion_calibration/uv_probe_5760x3240.exr`

Round 2.1 探针规格：

- **5760 × 3240（1.5× over-scan, 相机名义画面 3840×2160）**，**32-bit float OpenEXR**，3 通道
- R = (x + 0.5) / 5760、G = (y + 0.5) / 3240、B = 0（identity UV grid 覆盖完整 over-scan 区）
- camera 真实显示区域是 over-scan probe 的中心 3840×2160 (probe X ∈ [960, 4799], probe Y ∈ [540, 2699])
- 外面的"边缘缓冲带"(probe X ∈ [0, 959] ∪ [4800, 5759]) 给 K1>0 时的"出界"源像素提供有效数据

为什么改 over-scan：
- Round 2.0 直渲 4K 时, K1>0 的枕形畸变会把"源像素位置"拉到 LED 边界 (R/G ∈ [0,1] 的 [0,1] 范围) 外面
- 边界外没有 probe 数据, Disguise 渲管线就 fallback (clamp 边缘像素 / 镜像 / 别的奇怪行为) 产生脏值
- 1.5× over-scan 把 LED 物理范围扩大 50%, K1=±0.5 时所需源像素全部仍在有效 probe 区域内
- 对相机最终输出 (4K 3840×2160) 没有任何影响, 只是 calibration 过程中"渲得更大一点"

探针文件由 Mac 端用 `generate_uv_probe.py --resolution 5760x3240 --camera-resolution 3840x2160` 生成 (本仓库提供脚本), 然后传给 Disguise 工程师做 LED 内容. 如果手头没有, 联系 Mac 端生成发过来.

### d3 端

复用历史 stage、相机参数。**相机参数所有 51 帧严格一致**（焦距 / 传感器宽 / CenterShift 不能变），否则跨帧拟合系数无法比对。

**渲染分辨率改 5760×3240 但相机 FOV 不变**：实际操作上是给 LED 内容换大图, 给 Disguise 输出帧的 width/height 设为 5760×3240, 相机的 sensor / focal_length 全保持 Round 2.0 的设置。

### 关键约束（所有轮次都适用）

1. **必须 EXR 32-bit float**，不要 PNG / JPG / 16-bit half
   - 8-bit 量化误差 ±7 px → 直接报废
   - 16-bit half 精度边缘约 0.03 px，理论够用但保险起见全用 float

2. **LED surface 必须 linear pass-through**：gamma=1.0、无 LUT、无 color grading、
   无 tone mapping。任何 R/G 通道的非线性映射会让源 UV 失真，公式拟合废

3. **必须是 transmission compositor frame export**，不是 calibration overlay
   （后者是 inverse / undistortion 方向，方向反，已踩过坑）

4. **CenterShift = 0** 所有帧（K1/K2/K3 三组都是）

5. **分辨率严格匹配探针**：1080p 探针 → 1080p 渲染（Round 1）；
   4K 探针 → 4K 渲染（Round 2.0, 已废弃）；**5760×3240 探针 → 5760×3240 渲染（Round 2.1）**。**不能 resize / scale**

6. **每轮的 K=0 sanity check**：所有 K 都置 0 渲一帧（每组各一张 zero）。
   `analyze_renders` 自动校验 R/G 通道跟 identity UV grid 偏差；
   max deviation > 1% → LED gamma / color transform / overlay-vs-transmission 配置错，**先排查再继续**

---

## ✅ Round 1 · K1 sweep（已完成 2026-04-29，commit `0019ad3`）

**状态**：M_RAT6 公式反推完成（BrownConradyUD rational），BIC 全候选最优，
6 自由参数，RMS 0.401 px ≈ 噪声底。已写入 `distortion_math.py`，UE LensFile
切到 `BrownConradyUDLensModel`（commits `8164938..0019ad3`）。

**注**：历史 commit `4b3834f` + `34f5af0` 用的是 M6 polynomial（3 项），
在 r > 0.806 拐点崩盘（外圈 edge max 122 px）。M_RAT6 rational form 修复
（外圈 edge max 3.2 px，38× 改善）。详见 `docs/K1-implementation.md` §9。

**渲染过的 11 帧 1080p**（保留参考）：

| K1 值 | 文件名 |
|---|---|
| 0.0 | `disguise_K_zero.exr` |
| +0.1 ~ +0.5 | `disguise_K_p0p1.exr` ~ `disguise_K_p0p5.exr` |
| −0.1 ~ −0.5 | `disguise_K_n0p1.exr` ~ `disguise_K_n0p5.exr` |

命名约定：`p` = positive，`n` = negative，第二个 `p` 是小数点。

### M_RAT6 跟 UE 模型的对应关系

UE LensFile 的 `BrownConradyUDLensModel` shader 形态（`BrownConradyUDDistortion.usf:48-50`）：

```
r' = r · (1 + K1·r² + K2·r⁴ + K3·r⁶) / (1 + K4·r² + K5·r⁴ + K6·r⁶)
```

M_RAT6 直接展开成 8 系数（HW-norm → fx-norm 缩放因子 (2·fx)^(2k)）：

```
K1 = a · csv_K1 · (2·fx)²    K4 = d · csv_K1 · (2·fx)²
K2 = b · csv_K1² · (2·fx)⁴ - csv_K2 (legacy sign-flip)
K3 = c · csv_K1³ · (2·fx)⁶ - csv_K3 (legacy sign-flip)
K5 = e · csv_K1² · (2·fx)⁴
K6 = f · csv_K1³ · (2·fx)⁶
P1 = P2 = 0
```

其中 a..f 是 M_RAT6 fit 出的 6 系数（详见 `distortion_math.py M_RAT6_A..F`）：

```
a = -3.18050   d = -2.93087
b = +7.24462   e = +6.30678
c = +5.12035   f = +7.51125
```

production CSV K1 ≈ 3e-4 时，K1-K3 的 M_RAT6 项贡献 sub-1e-7，主导项是
`-csv_K2` / `-csv_K3`（等于 legacy sign-flip 行为）；K=±0.5 测试值时
M_RAT6 系数主导，rational shader 天然在边缘 well-behaved（Newton 全程
收敛 4.44e-16，无 pole）。

---

## ⏳ Round 2.1 · 1.5× over-scan K1 sweep（51 帧, 当前要做）

**目的**：用 1.5× over-scan 修复 Round 2.0 直渲 4K 时 K1>0 帧的黑边/fallback 脏数据问题, 把 K1+ side fit residual max 从 76-97 px 拉回到跟 K1- side 同水平 (~3 px @ 4K)。

**为什么改 over-scan（重要 — 工程师必读）**：
- Round 2.0 直渲 4K 时, K1=+0.50 (枕形畸变) 把每个输出像素的"源采样位置"往画面中心拉
- 但 K1=+0.50 在外圈 (相机画面接近边缘的输出像素) 需要的源采样位置会**跑到 LED 屏幕的 [0,1] 外面去**
- LED 边界外没有 probe 数据, Disguise 在那些像素吐 fallback 脏数据 (clamp / 镜像 / 别的奇怪行为)
- **Mac 这边 fit pipeline 把这些脏数据当成真数据**, 公式系数被带偏到错误的局部最优
- **修复方法**：让 LED 比相机画面**大 50%**, 边缘留 **缓冲带**, K1>0 把源像素拉出"相机画面"范围时仍落在缓冲带内有 probe 数据
- Round 2.1 仅 K1 sweep 一组 (51 帧), 通过后再讨论 K2 / K3

**这次先只做 K1, K2/K3 暂不做** (用户决策: 控制变量, K1 验证通过再扩展)

### 全局相机参数（每帧严格一致）

| 参数 | 值 |
|---|---|
| 传感器宽度 | **35 mm** |
| 焦距 | **30.302 mm** |
| **渲染分辨率（即 LED + 输出 EXR）** | **5760 × 3240（1.5× over-scan）** ← Round 2.0 是 3840×2160, 这次必须改 |
| **相机名义画面（不变, 但本次渲染不用直接产出这个尺寸）** | 3840 × 2160（4K） |
| 长宽比 | 1.7778 (16:9) |
| 中心位移 (CenterShift X/Y) | **0 mm**（绝对不能动） |
| 文件格式 | **32-bit float OpenEXR**（PIZ 压缩可接受，ZIP 也可） |
| LED 内容 | **新 over-scan probe `uv_probe_5760x3240.exr`**（R = (x+0.5)/5760, G = (y+0.5)/3240, B = 0） |
| LED 设置 | **Linear pass-through**：gamma=1.0，无 LUT，无 color grading，无 tone mapping |
| 帧类型 | **transmission frame**（不是 calibration overlay） |

### Disguise 端 over-scan 配置

具体怎么把渲染分辨率从 3840×2160 改到 5760×3240, **取决于 Disguise 项目设置**:

- 如果 Disguise 工程支持显式 over-scan 参数: 把 over-scan factor 设 1.5×
- 如果支持自定义渲染分辨率: 渲染分辨率改 5760×3240, 探针 LED 内容也按这个尺寸贴
- 如果还不确定: 联系 Mac 端 (本文档作者), 一起远程对一下 Disguise 设置

**关键原则**：相机视野角 (FOV) **不要改**, 保持跟原来一致。改的是 LED 内容和渲染输出帧大小, 让相机"看到"的范围里包含更多 LED 缓冲带。

### 输出目录结构

```
output/distortion_round2_overscan/
└── k1_sweep_overscan/      # 51 张 disguise_K1_*.exr (5760×3240)
```

每帧 EXR 约 70-100 MB（5760×3240 UV gradient PIZ 压缩，比 4K 大约 2.25×），**51 帧总 ~3.5-5 GB**。

### 命名约定

`p` = positive，`n` = negative，第二个 `p` 是小数点。文件名 4 位精度（`p0p02`, `p0p10`, `p0p50`）。

---

### 组 1：K1 sweep（51 帧）

**固定 K2 = 0，K3 = 0**，K1 从 -0.50 步进 **0.02** 到 +0.50：

| K1 值 | 正向文件名 | 负向文件名 |
|---|---|---|
| 0.00 | `disguise_K1_zero.exr` | — |
| ±0.02 | `disguise_K1_p0p02.exr` | `disguise_K1_n0p02.exr` |
| ±0.04 | `disguise_K1_p0p04.exr` | `disguise_K1_n0p04.exr` |
| ±0.06 | `disguise_K1_p0p06.exr` | `disguise_K1_n0p06.exr` |
| ±0.08 | `disguise_K1_p0p08.exr` | `disguise_K1_n0p08.exr` |
| ±0.10 | `disguise_K1_p0p10.exr` | `disguise_K1_n0p10.exr` |
| ±0.12 | `disguise_K1_p0p12.exr` | `disguise_K1_n0p12.exr` |
| ±0.14 | `disguise_K1_p0p14.exr` | `disguise_K1_n0p14.exr` |
| ±0.16 | `disguise_K1_p0p16.exr` | `disguise_K1_n0p16.exr` |
| ±0.18 | `disguise_K1_p0p18.exr` | `disguise_K1_n0p18.exr` |
| ±0.20 | `disguise_K1_p0p20.exr` | `disguise_K1_n0p20.exr` |
| ±0.22 | `disguise_K1_p0p22.exr` | `disguise_K1_n0p22.exr` |
| ±0.24 | `disguise_K1_p0p24.exr` | `disguise_K1_n0p24.exr` |
| ±0.26 | `disguise_K1_p0p26.exr` | `disguise_K1_n0p26.exr` |
| ±0.28 | `disguise_K1_p0p28.exr` | `disguise_K1_n0p28.exr` |
| ±0.30 | `disguise_K1_p0p30.exr` | `disguise_K1_n0p30.exr` |
| ±0.32 | `disguise_K1_p0p32.exr` | `disguise_K1_n0p32.exr` |
| ±0.34 | `disguise_K1_p0p34.exr` | `disguise_K1_n0p34.exr` |
| ±0.36 | `disguise_K1_p0p36.exr` | `disguise_K1_n0p36.exr` |
| ±0.38 | `disguise_K1_p0p38.exr` | `disguise_K1_n0p38.exr` |
| ±0.40 | `disguise_K1_p0p40.exr` | `disguise_K1_n0p40.exr` |
| ±0.42 | `disguise_K1_p0p42.exr` | `disguise_K1_n0p42.exr` |
| ±0.44 | `disguise_K1_p0p44.exr` | `disguise_K1_n0p44.exr` |
| ±0.46 | `disguise_K1_p0p46.exr` | `disguise_K1_n0p46.exr` |
| ±0.48 | `disguise_K1_p0p48.exr` | `disguise_K1_n0p48.exr` |
| ±0.50 | `disguise_K1_p0p50.exr` | `disguise_K1_n0p50.exr` |

**总计：1 + 25×2 = 51 张 EXR @ 5760×3240**

---

### 组 2：K2 sweep（暂不做）

**Round 2.1 阶段不渲 K2 sweep**, 等 K1 over-scan 验证通过 (max < 1 px @ 4K) 再决定 K2 / K3 是否需要。

如果将来要做 K2 / K3, 文件名规则跟 K1 一致 (替换前缀 K1 → K2 / K3), K 值步长一致, 同样用 5760×3240 over-scan 渲染。

---

### 组 3：K3 sweep（暂不做）

同组 2, 暂不渲。

---

### 渲染前 sanity check（必须先做, 不要直接渲全套）

**先单独渲一张 K1=0**（`disguise_K1_zero.exr`，5760×3240），上传 Mac 给我用 OpenCV 验证：

```python
import cv2, numpy as np, os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
img = cv2.imread('disguise_K1_zero.exr', cv2.IMREAD_UNCHANGED)
# 期望：shape (3240, 5760, 3 or 4)，dtype float32
# R 通道：x=0 → R≈0.0000868；x=5759 → R≈0.999913（左→右水平梯度）
# G 通道：y=0 → G≈0.000154；y=3239 → G≈0.999846（上→下垂直梯度）
# B 通道：全 0
# max deviation from identity grid 应 < 0.001（即 < 6 px-equivalent error）
```

如果 sanity 不通过 (max deviation > 0.001 / shape 不对 / dtype 不对)，**先排查 LED gamma/color transform/overlay-vs-transmission 配置错在哪，或者渲染分辨率没切到 5760×3240, 再继续渲全套**。Sanity 通过再批量渲剩下 50 帧。

### 同步验证: 渲一张 K1=+0.50 看黑边消失

K1=+0.50 是最容易暴露 over-scan 是否生效的极值。**也单独先渲一张 `disguise_K1_p0p50.exr`** 上传 Mac:

```python
import cv2, numpy as np, os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
img = cv2.imread('disguise_K1_p0p50.exr', cv2.IMREAD_UNCHANGED)
# 期望: shape (3240, 5760, 3 or 4), dtype float32
# 检查相机画面区域 (centred 3840x2160) 内有没有 R=0 或 G=0 的像素
# 中心 3840×2160 区域: probe Y ∈ [540, 2700), probe X ∈ [960, 4800)
center_R = img[540:2700, 960:4800, 2]
center_G = img[540:2700, 960:4800, 1]
print(f'center R range: [{center_R.min():.4f}, {center_R.max():.4f}]')
print(f'center G range: [{center_G.min():.4f}, {center_G.max():.4f}]')
# 期望: R/G 都在 (0, 1) 内, max ≠ 0, min ≠ 0
# 如果 min ≈ 0 → 仍有黑边/出界, over-scan factor 不够大或 Disguise 配置不对
```

K1+ 极值帧没有黑边了 (R/G min > 0.001), 才能继续渲全套 51 帧。

---

### 回传位置

**Round 2.1 只需上传 K1 sweep 51 帧 5760×3240 over-scan EXR**, 建议路径:

```
/Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration/validation_results/k1_sweep_overscan/
├── disguise_K1_zero.exr
├── disguise_K1_p0p02.exr
... (51 帧)
└── disguise_K1_n0p50.exr
```

或者放到 /tmp 也行。Mac 端 .gitignore 已配置不入库这些大文件。

**(不需要传 K2 / K3, Round 2.1 只做 K1)**

历史 153 帧路径 (Round 2.0 已废弃, 仅供参考):
```
/tmp/disguise_renders_round2/
├── k1_sweep/
├── k2_sweep/
└── k3_sweep/
```

---

## ⏳ Round 3 · 联合验证（Round 2 完成后做）

**目的**：验证 K1/K2/K3 三轴反推后的合成预测跟 Disguise 真渲染一致——确认三个
单变量公式可以"加性叠加"，或者发现需要 cross-term 修正（K1·K2·r² 类项）。

**触发条件**：Round 2 完成 + fit 系数更新 + production CSV 端到端测试残差仍 > 1 px 时做。
Round 2 fit 已经包含 cross-term 候选（M_RAT_K1K2K3_CROSS），如果 BIC 选中 cross-term
形态，Round 3 就只是双重验证而已，不必须做。

**渲染清单**：从 production CSV 里挑 **5 组真实 (K1, K2, K3) 三元组**（涵盖不同
take / 不同 focal length / 不同畸变量级），每组渲一帧 4K：

| 标签 | csv_K1 | csv_K2 | csv_K3 | 文件名 |
|---|---|---|---|---|
| sample1 | （从实拍 CSV 挑） | | | `disguise_KKK_sample1.exr` |
| sample2 | | | | `disguise_KKK_sample2.exr` |
| sample3 | | | | `disguise_KKK_sample3.exr` |
| sample4 | | | | `disguise_KKK_sample4.exr` |
| sample5 | | | | `disguise_KKK_sample5.exr` |

**配套**：每组提供对应的 K1/K2/K3 数值（写在 README 或 metadata 里），让分析
脚本知道每个文件对应的真实参数。

**回传**：放 Mac 的 `/tmp/disguise_renders_joint/`。

---

## Mac 端处理（用户不用做，分析时我跑）

### Round 1（已完成）

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python analyze_renders.py --input-dir /tmp/disguise_renders
.venv/bin/python fit_distortion_models.py
```

输出 BIC-best 模型 + 系数。M_RAT6 形态：
`r' = r · (1+a·K·r²+b·K²·r⁴+c·K³·r⁶) / (1+d·K·r²+e·K²·r⁴+f·K³·r⁶)`

### Round 2（待做，工具升级中）

我同步升级 `analyze_renders.py` + `fit_distortion_models.py` 支持：
- 4K 输入（dense sampling 100k+ pts per frame，不再硬编码 30k）
- `--half-width-px` 参数化（4K 数据用 1920，1080p 数据用 960）
- 新候选模型：
  - `M_RAT8`（8 参数 rational，更精细）
  - `M_RAT_K1K2K3_CROSS`（联合 K1/K2/K3 + cross-term）
  - `M_BCUD_FULL`（包含 P1/P2 切向）
- 命名规则识别 `disguise_K[1-3]_*.exr`（解析三轴）

数据来了直接跑 fit + 输出新系数。

### Round 3（待做时实现验证逻辑）

需要写 `_validate_joint_KKK.py`：
- 读每帧的 (K1, K2, K3) 元组
- 用 Round 2 fit 系数预测 source UV
- 跟 Disguise EXR R/G 通道逐像素比
- 残差 > noise floor 说明三个轴有 cross-term 耦合，单变量假设不成立

---

## 后续：把反推结果落地到 UE

每轮反推完成后，更新 `Content/Python/post_render_tool/distortion_math.py` 里
`compute_normalized_distortion`，把对应的 K2/K3 sign-flip 替换成反推的多项式
+ tangential 项。

**重要**：所有反推的 r 在 half-width 归一化空间，要乘 `(2·fx_uv)^(2k)` 转换到
UE LensFile 的 fx 归一化空间（参见 `distortion_math.py` 注释，commit `34f5af0`
踩过这个坑）。

---

## 流程触发图

```
Round 1 完成 (M_RAT6 + BCUD, 2026-04-29)
        ↓
   K=0.5 测试残差 max 3.2 px (VFX 入门档)
   production CSV ship-ready ✓
        ↓
   要 ILM 接近级 (max < 0.5 px)?
   ├─ NO:  停在 Round 1, 业务可上线
   └─ YES: 做 Round 2 (4K + 高密度)
           ↓
        Round 2 高密度 4K 153 帧 → 联合 K1/K2/K3 + tangential fit
        ↓
        预期 K=0.5 测试残差 max 0.5-1 px
        production CSV 残差 sub-pixel
        ↓
        production 还有问题? → Round 3 (联合验证 5 组真实 KKK 三元组)
```

---

## 当前精度档次定位（参考 `docs/distortion-precision-analysis.md`）

| 档次 | max @ 1080p | 状态 |
|---|---|---|
| ILM / Weta 旗舰 | < 0.05 px | 在 CSV-only 框架下物理不可达（CSV 信息论限制） |
| 影视后期 / 一线 VFX | < 0.3 px | Round 2 + UE 4K render 联合可达（VFX 旗舰级） |
| **当前 Round 1** | **3.2 px** | **VFX 入门档，production 可上线** |
| 广告 / 中等预算 | < 3 px | Round 1 已达 |
| 不能用 | > 5 px / 拐点崩 | M6 时代外圈 122 px 在这里（已修复） |
