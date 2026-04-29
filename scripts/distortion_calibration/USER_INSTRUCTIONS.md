# Disguise 端 K-sweep 采集指引（Path A · UV 渐变 + 公式反推）

> **目的**：采集 transmission frame 反推 Disguise 的 distortion 公式（Path A ·
> system identification）。详见 `docs/distortion-investigation.md`。
>
> 当前状态（commit `0019ad3` 落地）：
> - ✅ **Round 1 · K1 sweep 完成** —— M_RAT6 rational 反推 + UE BrownConradyUDLensModel 落地 + Tier 1/2 验证全过（外圈 edge max 122→3.2 px）
> - ⏳ **Round 2/3/4 · K2/K3 sweep + 联合验证 待做**（如果 production CSV 残差 > 1 px 才必须做）

---

## 工作流通用准备

### 探针图

`scripts/distortion_calibration/uv_probe_1920x1080.exr`：

- 1920×1080 32-bit float EXR，3 通道
- R = (x + 0.5)/W、G = (y + 0.5)/H、B = 0（identity UV grid）
- 每个像素自带源坐标真值，不需要角点检测

### d3 端

复用 image 44/45 用过的 stage、相机参数。**相机参数所有轮次必须一致**，否则跨轮的拟合系数无法比对。

### 关键约束（所有轮次都适用）

1. **必须 EXR 32-bit float**，不要 PNG / JPG / 16-bit half
   - 8-bit 量化误差 ±7 px → 直接报废
   - 16-bit half 精度边缘约 0.03 px，理论够用但保险起见全用 float

2. **LED surface 必须 linear pass-through**：gamma=1.0、无 LUT、无 color grading、
   无 tone mapping。任何 R/G 通道的非线性映射会让源 UV 失真，公式拟合废

3. **必须是 transmission compositor frame export**，不是 calibration overlay
   （后者是 inverse / undistortion 方向，方向反，已踩过坑）

4. **分辨率严格 1920×1080**，不要 resize / scale

5. **CenterShift = 0** 所有帧（K2/K3 sweep 也是）

6. **每轮的 K=0 帧（sanity check）**：所有 K 都置 0 渲一帧。`analyze_renders` 会
   自动校验 R/G 通道跟 identity UV grid 的偏差；如果 max deviation > 1%，说明
   LED gamma / color transform / overlay-vs-transmission 哪儿出问题，**先排查再继续**

---

## ✅ Round 1 · K1 sweep（已完成 2026-04-29，commit `0019ad3`）

**状态**：M_RAT6 公式反推完成（BrownConradyUD rational），BIC 全候选最优，
6 自由参数，RMS 0.401 px ≈ 噪声底。已写入 `distortion_math.py`，UE LensFile
切到 `BrownConradyUDLensModel`（commits `8164938..0019ad3`）。

**注**：历史 commit `4b3834f` + `34f5af0` 用的是 M6 polynomial（3 项），
在 r > 0.806 拐点崩盘（外圈 edge max 122 px）。M_RAT6 rational form 修复
（外圈 edge max 3.2 px，38× 改善）。详见 `docs/K1-implementation.md` §9。

**渲染过的 11 帧**（保留参考）：

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

## ⏳ Round 2 · K2 sweep（待做）

**目的**：反推 CSV K2 → UE 系数的真实映射，替换当前 legacy sign-flip
（`ue_K2 = -csv_K2`）。

**触发条件**：production CSV 端到端测试残差 > 1 px 时必须做。如果 < 1 px，
说明 sign-flip 透传精度足够，可跳过。

**渲染清单**：固定 **K1 = K3 = 0、CenterShift = 0**，K2 取 11 个值各渲一次：

| K2 值 | 文件名 |
|---|---|
| 0.0 | `disguise_K2_zero.exr` |
| +0.1 | `disguise_K2_p0p1.exr` |
| +0.2 | `disguise_K2_p0p2.exr` |
| +0.3 | `disguise_K2_p0p3.exr` |
| +0.4 | `disguise_K2_p0p4.exr` |
| +0.5 | `disguise_K2_p0p5.exr` |
| −0.1 | `disguise_K2_n0p1.exr` |
| −0.2 | `disguise_K2_n0p2.exr` |
| −0.3 | `disguise_K2_n0p3.exr` |
| −0.4 | `disguise_K2_n0p4.exr` |
| −0.5 | `disguise_K2_n0p5.exr` |

**注意**：K2 sweep 范围（±0.5）是测试用极端值，比 production 实际 K2≈0.004 大
两个数量级。极端值能让公式形态显现；production 直接拟合不出形态。

**回传**：放 Mac 的 `/tmp/disguise_renders_K2/`。

---

## ⏳ Round 3 · K3 sweep（待做）

**目的**：反推 CSV K3 → UE 系数的真实映射。

**触发条件**：跟 Round 2 同（production 残差 > 1 px 时必须做）。

**渲染清单**：固定 **K1 = K2 = 0、CenterShift = 0**，K3 取 11 个值：

| K3 值 | 文件名 |
|---|---|
| 0.0 | `disguise_K3_zero.exr` |
| ±0.1 ~ ±0.5 | `disguise_K3_p0p1.exr` ~ `disguise_K3_n0p5.exr` |

命名约定同 Round 1/2。

**回传**：放 Mac 的 `/tmp/disguise_renders_K3/`。

---

## ⏳ Round 4 · 联合验证（待做）

**目的**：验证 K1/K2/K3 三轴反推后的合成预测跟 Disguise 真渲染一致（即三个
单变量公式可以"加性叠加"或者发现需要 cross-term 修正）。

**触发条件**：Round 2 + Round 3 完成后必做。

**渲染清单**：从 production CSV 里挑 **5 组真实 (K1, K2, K3) 三元组**（涵盖
不同 take / 不同 focal length / 不同畸变量级），每组渲一帧：

| 标签 | csv_K1 | csv_K2 | csv_K3 | 文件名 |
|---|---|---|---|---|
| sample1 | （从 CSV 挑） | | | `disguise_KKK_sample1.exr` |
| sample2 | | | | `disguise_KKK_sample2.exr` |
| sample3 | | | | `disguise_KKK_sample3.exr` |
| sample4 | | | | `disguise_KKK_sample4.exr` |
| sample5 | | | | `disguise_KKK_sample5.exr` |

**配套**：每组提供对应的 K1/K2/K3 数值（写在 CSV 文件或 README 里），让分析
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

输出 BIC-best 模型 + 系数。M6 形态: `r' = r·(1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶)`。

### Round 2/3（待做时扩展工具）

需要扩展 `analyze_renders.py` 支持 `disguise_K2_*` / `disguise_K3_*` 命名，
扩展 `fit_distortion_models.py` 加 K2 / K3 候选模型族。预估改造工作量 1-2 小时。

### Round 4（待做时实现验证逻辑）

需要写 `_validate_joint_KKK.py`：
- 读每帧的 (K1, K2, K3) 元组
- 用三个反推系数 (M6_K1 + M_K2 + M_K3) 加性预测 source UV
- 跟 Disguise EXR R/G 通道逐像素比
- 残差 > noise floor 说明三个轴有 cross-term 耦合，单变量假设不成立

---

## 后续：把反推结果落地到 UE

每轮反推完成后，更新 `Content/Python/post_render_tool/distortion_math.py` 里
`compute_normalized_distortion`，把对应的 K2/K3 sign-flip 替换成反推的多项式。

**重要**：所有反推的 r 在 half-width 归一化空间，要乘 `(2·fx_uv)^(2k)` 转换到
UE LensFile 的 fx 归一化空间（参见 `distortion_math.py` 注释，commit `34f5af0`
踩过这个坑）。

---

## 流程触发图

```
Plan A: production CSV 端到端真渲染对比
        ↓
   残差 < 1 px ?
   ├─ YES: ship-ready，K2/K3 sign-flip 透传够用，Round 2/3/4 不用做
   └─ NO:  K2/K3 mapping 是真瓶颈
           ↓
        Round 2 (K2 sweep) → 拟合 K2 → 落地 distortion_math.py
        Round 3 (K3 sweep) → 拟合 K3 → 落地 distortion_math.py
        Round 4 (联合验证) → 确认加性合成成立 / 是否要 cross-term
        ↓
        重做 Plan A → 再看残差
```
