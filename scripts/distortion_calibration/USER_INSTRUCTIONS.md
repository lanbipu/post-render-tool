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
> - ⏳ **Round 2.1 · Disguise lens over-scan 1.5× K1 sweep（51 帧 4K）下一步要做** ← **本文档当前指引**
>   - 用 Disguise lens over-scan 1.5× 修复 K1>0 黑边问题, 输出仍是 4K, 不需要换探针图
>   - Mac 端自动从 K=0 anchor 检测 over-scan factor + R/G 反仿射补偿
>   - 先做 K1 sweep 一轮验证, 通过后再考虑 K2/K3
>   - PostRenderTool 用户接口零变化，仅后端 `distortion_math.py` 系数更新

---

## 工作流通用准备（适用所有轮次）

### 探针图

**Round 1（旧）**：`scripts/distortion_calibration/uv_probe_1920x1080.exr`（1080p）
**Round 2.0（已用过, 4K 直渲, 黑边问题）**：`scripts/distortion_calibration/uv_probe_3840x2160.exr`
**Round 2.1（当前指引, Disguise lens over-scan 1.5×）**：仍用 `uv_probe_3840x2160.exr`（**不需要换**）

实测确认 (2026-04-30): Disguise lens over-scan 1.5× 渲染输出仍是 nominal 4K (3840×2160), R/G 通道被仿射拉伸到 [0.1667, 0.8333]. Mac 端 `analyze_renders.py` 自动检测 over-scan factor + R/G 反仿射补偿, 无需手动操作.

为什么用 lens over-scan 而不是大探针图:
- Round 2.0 直渲 4K 时, K1>0 的枕形畸变把源像素拉到 LED 边界外, Disguise fallback 产生脏数据
- Disguise lens over-scan 1.5× 在内部扩大渲染范围, 但**导出 EXR 仍是 4K**, R/G 被仿射压缩
- K=0 anchor: R/G 范围 [0.1667, 0.8330] (margin = 1/6, factor = 1.5, 完美仿射)
- K1=+0.5 帧: R/G 范围 [0.1119, 0.8877], **全画面无黑边** (over-scan 提供了合法缓冲)
- Mac 端自动检测 + 数学补偿, 物理畸变系数跟 over-scan 设置无关

不需要生成新探针图, 不需要换 LED 内容分辨率, 不需要改 Disguise 输出分辨率 — 只需要开 lens over-scan 1.5× 开关.

### d3 端

复用历史 stage、相机参数。**相机参数所有 51 帧严格一致**（焦距 / 传感器宽 / CenterShift 不能变），否则跨帧拟合系数无法比对。

**渲染分辨率仍是 4K (3840×2160), 开 lens over-scan 1.5×**：相机 sensor / focal_length / FOV 全保持 Round 2.0 的设置. Disguise 内部以 5760×3240 渲染, 但自动裁回 4K 导出. LED 内容仍是 `uv_probe_3840x2160.exr`.

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
   4K 探针 → 4K 渲染（Round 2.0 和 Round 2.1）。Round 2.1 用 lens over-scan 1.5×, 输出仍是 4K, 探针仍用 4K。**不能 resize / scale**

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

## ⏳ Round 2.1 · Disguise lens over-scan 1.5× K1 sweep（51 帧 4K, 当前要做）

**目的**：用 Disguise lens over-scan 1.5× 修复 Round 2.0 直渲 4K 时 K1>0 帧的黑边问题, 不需要换探针图。

**Disguise 端配置（已实测确认 2026-04-30）**:
- **相机分辨率**: 5760×3240 (over-scan 内部渲染分辨率, 自动)
- **导出 EXR 分辨率**: 仍是 3840×2160 (4K, Disguise 自动裁回 nominal)
- **lens over-scan ratio**: 1.5
- **探针图**: 仍用现有 `uv_probe_3840x2160.exr` (4K 探针, 不需要换)
- 其他 (sensor / focal_length / FOV / CenterShift): 全部跟 Round 2.0 一致

**实测验证（2026-04-30）**:
- K=0 anchor 帧: R/G 范围 [0.1667, 0.8330] (1.5× over-scan 仿射规律)
- K1=+0.5 帧: R/G 范围 [0.1119, 0.8877], 全画面无黑边 ✓

**Mac 端处理**:
- `analyze_renders.py` 自动从 K=0 anchor 检测 over-scan factor (1.5×) + margin (0.1667)
- 对所有帧 R/G 通道做反仿射补偿, 把 over-scan 拉伸还原到 [0, 1] 等价坐标
- fit pipeline 不用改, 直接跑

**这次先只做 K1, K2/K3 暂不做** (用户决策: 控制变量, K1 验证通过再扩展)

### 全局相机参数（每帧严格一致）

| 参数 | 值 |
|---|---|
| 传感器宽度 | **35 mm** |
| 焦距 | **30.302 mm** |
| **导出 EXR 分辨率** | **3840 × 2160（4K, Disguise 自动）** |
| **lens over-scan** | **1.5×** |
| 长宽比 | 1.7778 (16:9) |
| 中心位移 (CenterShift X/Y) | **0 mm**（绝对不能动） |
| 文件格式 | **32-bit float OpenEXR**（PIZ 压缩可接受，ZIP 也可） |
| LED 内容 | **`uv_probe_3840x2160.exr`**（R = (x+0.5)/3840, G = (y+0.5)/2160, B = 0）|
| LED 设置 | **Linear pass-through**：gamma=1.0，无 LUT，无 color grading，无 tone mapping |
| 帧类型 | **transmission frame**（不是 calibration overlay） |

### 渲染前 sanity 验证

先单渲 K1=0 + K1=+0.5 两张, 上传 Mac 验证:

```python
import cv2, numpy as np, os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'

# K=0 帧应当 R/G 范围 [0.1667, 0.8333] (1.5× over-scan 仿射规律)
img = cv2.imread('disguise_K1_zero.exr', cv2.IMREAD_UNCHANGED)
print(f'K=0 R range: [{img[..., 2].min():.4f}, {img[..., 2].max():.4f}]')
# 期望: [0.1667, 0.8333]

# K1=+0.5 帧应当无黑边 (R/G 全 > 0.005)
img = cv2.imread('disguise_K1_p0p50.exr', cv2.IMREAD_UNCHANGED)
center_R = img[540:1620, 960:2880, 2]
print(f'K1=+0.5 中心区 R 范围: [{center_R.min():.4f}, {center_R.max():.4f}]')
# 期望: [~0.11, ~0.89], 无 R<0.005 黑边
```

Sanity 通过再渲全套 51 帧。

### 命名约定

`p` = positive, `n` = negative, 第二个 `p` 是小数点。文件名 4 位精度。

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

**总计：1 + 25×2 = 51 张 EXR @ 3840×2160**

---

### 组 2：K2 sweep（暂不做）

**Round 2.1 阶段不渲 K2 sweep**, 等 K1 over-scan 验证通过 (max < 1 px @ 4K) 再决定 K2 / K3 是否需要。

如果将来要做 K2 / K3, 文件名规则跟 K1 一致 (替换前缀 K1 → K2 / K3), K 值步长一致, 同样用 4K + lens over-scan 1.5× 渲染。

---

### 组 3：K3 sweep（暂不做）

同组 2, 暂不渲。

---

### 回传位置

```
validation_results/k1_sweep_overscan/
├── disguise_K1_zero.exr
├── disguise_K1_p0p02.exr
... (51 帧 4K, 文件名跟 Round 2.0 一致)
└── disguise_K1_n0p50.exr
```

Mac 端 .gitignore 已配置不入库大文件。

**Note**: 这跟上一版指引的 "5760×3240 探针图 + 5760×3240 渲染" 路线**不一样**。实测确认 Disguise 端不需要换探针图, 仅靠 lens over-scan 1.5× 设置就够。

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
