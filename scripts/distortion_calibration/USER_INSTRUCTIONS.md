# Disguise 端 K-sweep 渲染指引

## 这个文档干嘛的

简单说：告诉你（Disguise 那一头）现在要在 d3 里渲哪些帧、怎么设置、渲完丢哪儿。Mac 端怎么处理这些 EXR 是我的事，你不用关心。

## 一句话状态

技术路径在 2026-05-05 换了：以前那条「让 UE 用 LensFile 算 distortion」的路（Path A）走不通了，最低残差卡在 2.5-2.9 像素，过不了 pixel-perfect。新方案是**在 UE 里写一个自定义 shader，照搬 Disguise 的公式逐像素扭画面**（Path C · Custom Post-Process Material）。

要让这个 shader 跑得对，得先搞清楚 Disguise 公式里 K2 / K3 到底是哪一阶项、centerShift 是什么单位什么符号——这些 Disguise 文档里没明写，得靠渲一组已知输入回去反推。

**这次要的就是这组反推用的 16 张帧。**

完整设计文档：`docs/custom-postprocess-distortion-final-plan.md`。
权威渲染清单：`docs/d3-distortion-render-request.md`（任何冲突以那份为准）。

---

## 现在要渲什么

16 张 4K EXR，分三组加一张基线。

### Set A · K2 sweep（5 张）

K1=K3=0，centerShift=0，只动 K2 扫五个值：

| K2 | 文件名 |
|---:|---|
| -0.5 | `disguise_K2_n0p5.exr` |
| -0.3 | `disguise_K2_n0p3.exr` |
|  0.0 | `disguise_K2_zero.exr` |
| +0.3 | `disguise_K2_p0p3.exr` |
| +0.5 | `disguise_K2_p0p5.exr` |

**用途**：看看 Disguise 的 K2 到底是不是 OpenCV 标准的 r⁴ 项。是的话 shader 直接抄 OpenCV 写法；不是的话得在 shader 里写一段对应实际形态的代码。

### Set A · K3 sweep（5 张）

K1=K2=0，centerShift=0，只动 K3：

| K3 | 文件名 |
|---:|---|
| -0.5 | `disguise_K3_n0p5.exr` |
| -0.3 | `disguise_K3_n0p3.exr` |
|  0.0 | `disguise_K3_zero.exr` |
| +0.3 | `disguise_K3_p0p3.exr` |
| +0.5 | `disguise_K3_p0p5.exr` |

**用途**：同样验证 K3 是不是 r⁶ 项。

### Set B · centerShiftX sweep（5 张）

K1=K2=K3 全 0，centerShiftMM.y 也设 0，只动 centerShiftMM.x：

| centerShiftMM.x | 文件名 |
|---:|---|
| -0.10 | `disguise_centerShiftX_n0p10.exr` |
| -0.05 | `disguise_centerShiftX_n0p05.exr` |
|  0.00 | `disguise_centerShift_zero.exr` |
| +0.05 | `disguise_centerShiftX_p0p05.exr` |
| +0.10 | `disguise_centerShiftX_p0p10.exr` |

**用途**：Disguise 的 centerShiftMM 是什么单位、正方向是哪边？文档没明写，这 5 张实测出来。

如果你那边有空，可以再渲 5 张 Y 轴版（命名改 `disguise_centerShiftY_*.exr`）。X 5 张是阻塞项必做，Y 5 张是锦上添花。

### Set C · Identity（1 张）

K 全 0、centerShift 全 0：

| 文件名 |
|---|
| `disguise_identity_K0_center0.exr` |

视觉上跟 K2_zero / K3_zero 几乎一样，但保留独立文件名，以后做 image diff 时方便引用。

---

## d3 端怎么设置

跟 Round 2.1 一模一样，相机参数一个都别动：

| 参数 | 值 |
|---|---|
| 探针图（LED 内容） | `scripts/distortion_calibration/uv_probe_3840x2160.exr` |
| 输出格式 | OpenEXR 32-bit float |
| 输出分辨率 | 3840 × 2160 (4K) |
| Lens over-scan | 1.5×（跟 Round 2.1 一致） |
| 颜色 | linear，**不要** tone mapping、LUT、gamma 转换、color management |
| 缩放 / 裁切 | 1:1 像素映射，**不要** resize 或裁 |
| 帧类型 | **transmission frame**（不是 calibration overlay） |
| 命名规则 | 全小写 `.exr`；`p` 表示正号兼小数点，`n` 表示负号 |

### 为什么用 lens over-scan 1.5×

不开 over-scan 的话，K1>0 这种枕形畸变会把源像素拉到 LED 屏幕外面，Disguise 在那些位置吐脏数据——以前 Round 2.0 踩过这个坑。开 1.5× 之后 Disguise 内部按 5760×3240 渲、自动裁回 4K 输出，画面里没有黑边，R/G 通道被仿射压缩到 [0.1667, 0.8333]。Mac 端会自动检测这个仿射并补偿回来，你那边不用做额外操作。

### 几个一定别踩的坑

1. **必须 32-bit float EXR**。8-bit 量化误差能到 7 像素直接报废；16-bit half 理论上够用但不保险。全用 float 最稳。
2. **LED surface 必须 linear pass-through**。gamma=1.0、不要 LUT、不要 color grading、不要 tone mapping。任何对 R/G 通道的非线性映射都让公式反推废掉。
3. **必须是 transmission frame，不是 calibration overlay**。后者方向反着的（是 inverse / undistortion 那个方向），CLAUDE.md 里专门记过这个坑。
4. **CenterShift = 0 全程**（Set B 那 5 张除外，那 5 张就是来扫 centerShift 的）。其他帧 centerShift 一动整个反推就没法分离 K 项的影响了。
5. **相机参数 16 帧严格一致**。焦距 / 传感器宽 / 长宽比一个都别变。任何参数变动都让这 16 帧之间没法横向对比。

---

## 渲完先 sanity check 一下

先单渲一两张让我看看是不是设置对了，再批量。最快的检查：

```python
import os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
import cv2

img = cv2.imread('disguise_identity_K0_center0.exr', cv2.IMREAD_UNCHANGED)
print(img.shape, img.dtype)
print('R', float(img[..., 2].min()), float(img[..., 2].max()))
print('G', float(img[..., 1].min()), float(img[..., 1].max()))
```

期望看到：
- shape = `(2160, 3840, 3)` 或 `(2160, 3840, 4)`
- dtype = `float32`
- identity 帧 R / G 范围接近 `[0.1667, 0.8333]`（1.5× over-scan 仿射规律）

R/G 范围明显偏离这个区间多半是 LED gamma 没设 linear、用错了 calibration overlay 模式、或者分辨率没设对。先排查再继续渲剩下的。

---

## 渲完放哪

```
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

`.gitignore` 里已经把这个目录的 4K EXR 排除了，不会进 git 仓库。

---

## Mac 端我会做什么（你不用管，记在这只是让你知道流程）

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration

# 不依赖你的输入数据，先跑（确认脚本没坏）
.venv/bin/python _self_test_custom_gate_eval.py
.venv/bin/python check_identity_roundtrip.py

# 等 16 张到货后跑这两个
.venv/bin/python evaluate_center_shift_sweep.py \
    --input-dir validation_results/custom_pp_gate_inputs/center_shift_sweep
.venv/bin/python evaluate_k2_k3_custom_formula.py \
    --input-dir validation_results/custom_pp_gate_inputs/k2_k3_sweep
```

跑完会在 `/Volumes/Docs/temp/k_sweep/gate3_5_*` 和 `gate6_*` 生成 JSON + Markdown 报告。报告会告诉我三件事：

1. K2 / K3 在 Disguise 公式里到底是哪一阶项、什么符号
2. centerShiftMM 怎么映射到归一化坐标
3. 残差是不是已经掉到 Disguise 16-bit half 量化底（~1-3 像素 @ 4K）以内——这个值是物理上限，到这就到头了

这三件事确认完，我才会去 lanPC 上把 UE Material shader graph 真正冻结。

---

## 你渲帧 跟 我写 UE 代码 是并行的

不用等帧到齐我才动手。我这边能并行做的事：

| 工作 | 依赖你的帧吗？ | 现在能做吗 |
|---|---|---|
| 加 `DistortionMode` 枚举 + Gate 1 单元测试 | 不依赖 | ✅ 能 |
| 写 C++ Controller component 框架 | 不依赖 | ✅ 能（要 Editor 重启 + UBT rebuild） |
| 在 lanPC UE Editor 里手工建 Material 资产（初版形态） | 不依赖（先按 OpenCV 标准形态写） | ✅ 能 |
| Pipeline 加分流逻辑（默认仍走老路 `LegacyLensFile`） | 不依赖 | ✅ 能 |
| Material shader 冻结正式公式 | 依赖 | ⏳ 等帧 |
| Pipeline 里 `CenterUV` 公式落地 | 依赖 | ⏳ 等帧 |
| 端到端 MRQ 真值对比验证（Gate 3 / 4） | 依赖 + 依赖 UE 工程跑通 | ⏳ 全部到位再做 |

意思就是：你那边渲帧的同时，我这边把脚手架代码先写出来。等你帧到了直接进入「冻结公式 + 端到端验证」阶段，不会有空等。

---

## 流程图

```
现在 → 渲 16 张 (Path C · Round 3.0)
         ↓
   Mac 跑 Gate 3.5 + Gate 6 反推 K2/K3 阶数 + centerShift 单位
         ↓
   公式定下来 → 在 UE Material 里冻结 shader graph
         ↓
   写 C++ Controller + Pipeline 分流
         ↓
   Gate 3 / 4 / 5 端到端 MRQ 真值对比
         ↓
   全过 → 默认切 CUSTOM_POST_PROCESS，老路 LegacyLensFile 留 fallback

如果 Gate 3 / 4 失败：
   回退到 Path B → 启用 Round 2.3 (147 张 sweep) + STMap 字典法
```

---

## 精度档次

| 档次 | max @ 4K | Path A 状态 | Path C 目标 |
|---|---|---|---|
| ILM / Weta 旗舰 | < 0.1 px | 不可达 | 不可达（Disguise 16-bit 量化底锁死） |
| 一线 VFX | < 0.5 px | 不可达（M_RAT6 拟合 p95 2.867 px） | **目标区间** |
| 当前 Path A 实测 | 2.5–2.9 px | NO-GO | — |
| 广告 / 中等预算 | < 3 px | Round 1 已达 | 远好于此 |

参考 `docs/distortion-precision-analysis.md`。

---

# 历史记录（不必看，给以后接手的人）

下面是「我们怎么走到这一步」的来龙去脉。如果你已经熟悉，直接跳过。

## Path A · LensFile 公式拟合（结案 NO-GO）

### 思路

把 Disguise CSV 里的 K1/K2/K3 翻译成 UE LensFile 的 BrownConrady 系数，让 UE 自己渲畸变。从 polynomial（M6）一路试到 rational（M_RAT6 / M_RAT8），都过不了 pixel-perfect。最低残差 2.5-2.9 像素。

### 为什么过不了

UE LensFile 用的公式形态跟 Disguise 用的不是同一个，把 Disguise 系数硬塞进 UE 槽位永远只能近似不能等价。这是公式形态本身的物理限制，再 fit 也突破不了。

### 历史轮次

#### Round 1 · 11 帧 1080p K1 sweep（已完成 2026-04-29，commit `0019ad3`）

M_RAT6 rational 反推 + UE BrownConradyUDLensModel 落地。

- 拟合 RMS 0.401 像素 ≈ 噪声底（漂亮）
- 但 K=±0.5 测试边缘最大残差 3.2 像素 → VFX 入门档次
- 外圈 edge max 122 → 3.2 px（38× 改善，比之前 M6 polynomial 强很多）

M_RAT6 跟 UE BrownConradyUD shader 的对应关系（`BrownConradyUDDistortion.usf:48-50`）：

```
r' = r · (1 + K1·r² + K2·r⁴ + K3·r⁶) / (1 + K4·r² + K5·r⁴ + K6·r⁶)
```

M_RAT6 直接展开成 UE 8 系数（HW-norm → fx-norm 缩放因子 `(2·fx)^(2k)`）：

```
K1 = a · csv_K1 · (2·fx)²    K4 = d · csv_K1 · (2·fx)²
K2 = b · csv_K1² · (2·fx)⁴ - csv_K2 (legacy sign-flip)
K3 = c · csv_K1³ · (2·fx)⁶ - csv_K3 (legacy sign-flip)
K5 = e · csv_K1² · (2·fx)⁴
K6 = f · csv_K1³ · (2·fx)⁶
P1 = P2 = 0
```

a..f 是 M_RAT6 fit 出的 6 系数（`distortion_math.py M_RAT6_A..F`）。

历史踩坑：commit `4b3834f` + `34f5af0` 用 M6 polynomial（3 项）在 r > 0.806 拐点崩盘（外圈 edge max 122 px）。M_RAT6 rational form 修复（外圈 edge max 3.2 px）。详见 `docs/K1-implementation.md` §9。

11 帧文件名（保留参考）：

| K1 | 文件名 |
|---|---|
| 0.0 | `disguise_K_zero.exr` |
| +0.1 ~ +0.5 | `disguise_K_p0p1.exr` ~ `disguise_K_p0p5.exr` |
| -0.1 ~ -0.5 | `disguise_K_n0p1.exr` ~ `disguise_K_n0p5.exr` |

#### Round 2.0 · 51 帧 4K K1 sweep（未完成）

直渲 4K 的时候 K1>0 帧出现黑边——枕形畸变把源像素拉到 LED 屏幕外面，Disguise 吐脏数据。K1- 帧干净（max ~3 px @ 4K），K1+ 帧 max 76-97 px。

#### Round 2.1 · 51 帧 4K + lens over-scan 1.5×（已完成 2026-04-30，commit `ecb997a`）

加 lens over-scan 1.5× 解决黑边问题，M_RAT6 系数更新（基于 5M 像素样本 + 5% robust trim）：

```
M_RAT6_A = +602.25734
M_RAT6_B = +812547.17935
M_RAT6_C = +395029.04330
M_RAT6_D = +602.66929
M_RAT6_E = +814809.12141
M_RAT6_F = +601028.79343
```

production 区 |K1|≤0.1 RMS 1.09 像素 / max 3.5 像素，比 Round 1 改善 3.3×。但 lanPC 端到端验证残差仍 > 1 像素，确认 model mismatch 是物理瓶颈。

注：Round 2.1 系数绝对值很大（10²~10⁶），是 r 扩展到 1.33（over-scan）后的数值现象，numerator/denominator 近似抵消后净效果跟 Round 1 类似。production K1 ≈ 3e-4 时 M_RAT6 项贡献 sub-1e-7，主导项仍是 legacy K2/K3 sign-flip。

#### Round 2.2 · 4 张 K=±0.5 三轴独立可加性验证（已完成 2026-05-02）

确认 K1/K2/K3 三轴在位移上独立可加（max residual/signal 1.86%，verdict INDEPENDENT），1D 字典策略可行（如果走 Path B）。

同时发现 Disguise 输出本质是 16-bit half float（容器是 float32 但精度只到 16-bit），量化底 ~1-3 像素 @ 4K。**这是后续所有方法的精度天花板**，跟用什么公式、什么系数无关。

测试用的 4 张（K 值用 m2_jj_47 项目真实数值）：

| 标签 | K1 | K2 | K3 | 文件名 |
|---|---|---|---|---|
| 单 K1  | 0.00147 | 0       | 0        | `disguise_KKK_only_K1.exr` |
| 单 K2  | 0       | 0.01059 | 0        | `disguise_KKK_only_K2.exr` |
| 单 K3  | 0       | 0       | -0.09008 | `disguise_KKK_only_K3.exr` |
| 三合一 | 0.00147 | 0.01059 | -0.09008 | `disguise_KKK_combined.exr` |

最后决策：放弃 Path A，转向 Path C。

## Path B · STMap 字典法（搁置备胎）

### 思路

Disguise 渲一张 identity-UV 图当查找表，把每个像素对应的「源 UV」直接编码进去，UE 端用这张表做查找。理论上能复刻任意畸变形状。

### 为什么没继续

要给每轴 K（K1/K2/K3）都做一组 1D 字典 sweep（计划是阶梯步长 49 张/轴 × 3 轴 = 147 张，叫 Round 2.3），渲图 1-1.5 天，Mac 端字典预处理 0.5 天，PostRenderTool 集成 1-2 天，端到端验证 1 天——总共 4-5 个工作日。

而且字典精度仍然被那个 16-bit half 量化底锁死，做完天花板还是 1-3 像素。

工程复杂度 + 精度天花板都不划算。Path C 端到端失败再回来启用，详见 `USER_INSTRUCTIONS_PATH_B.md`。

### Round 2.3 · 147 张阶梯步长 sweep（已搁置）

之前 m2_jj_47 production 实测 K1/K2/K3 都 < 0.1（K1=0.00147, K2=0.01059, K3=-0.09008），所以采样方案是阶梯步长：

- 密区 [-0.100, +0.100] 步长 0.005 → 41 张/轴
- buffer 区 ±0.200 步长 0.025 → 8 张/轴
- 合计 49 张/轴 × 3 轴 = 147 张

K 值清单（密区，每个值都要渲）：

```
-0.100, -0.095, -0.090, -0.085, -0.080, -0.075, -0.070, -0.065, -0.060, -0.055,
-0.050, -0.045, -0.040, -0.035, -0.030, -0.025, -0.020, -0.015, -0.010, -0.005,
 0.000,
+0.005, +0.010, +0.015, +0.020, +0.025, +0.030, +0.035, +0.040, +0.045, +0.050,
+0.055, +0.060, +0.065, +0.070, +0.075, +0.080, +0.085, +0.090, +0.095, +0.100
```

Buffer 区：

```
-0.200, -0.175, -0.150, -0.125, +0.125, +0.150, +0.175, +0.200
```

命名 `disguise_K{1|2|3}_{p|n|zero}{value}.exr`，比如 `disguise_K1_p0p005.exr` = K1 +0.005。

回传位置（Path C 失败回退时启用）：

```
validation_results/k1_sweep_round23/    (49 张)
validation_results/k2_sweep/             (49 张)
validation_results/k3_sweep/             (49 张)
```

约束：每轴 sweep 时另两轴必须 0；centerShift 全程 0；相机参数全部跟 Round 2.1 / 2.2 严格一致。

## Path C · Custom Post-Process Material（当前主路）

当前的方案。在 UE 里写一个自定义 post-process shader，shader 内部直接执行 Disguise 的 `official_sensor_inverse` 公式，跳过 UE LensFile 那套公式翻译。

Disguise CSV 里的 K1/K2/K3 / centerShift 通过一个 C++ Controller component 喂到 shader 参数，每帧 Sequencer 打 keyframe 驱动。

### 为什么这次能成

不再做翻译。Disguise 用什么公式 shader 就写什么公式，1:1 实现，没有拟合误差。剩下的残差只能来自 Disguise 16-bit 量化和 UE MRQ sampling，跟我们写的 shader 无关。

### 要做的事

- 写 C++ Controller component（`PostRenderDistortionControllerComponent`）
- UE 里建一个 post-process material（`M_PRT_OfficialSensorInverse`）—— 这就是为什么要那 16 张帧——把 shader 公式形态钉死
- Pipeline 加分流逻辑（默认仍走老路，CUSTOM_POST_PROCESS 是开关切换）
- 端到端 MRQ 真值对比

详见 `docs/custom-postprocess-distortion-final-plan.md`。
