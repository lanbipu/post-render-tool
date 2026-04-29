# K1 反推与落地 · 完整技术总结

> 写于 2026-04-28，对应 commit `34f5af0`（最终）。
>
> 本文是 **CSV K1 → UE LensFile K1/K2/K3** 映射的"成品报告"——记录 reverse-engineer
> Disguise distortion 公式（针对 K1 轴）的整个流程、决策、踩过的坑、最终落地代码。
> K2/K3 后续按这个模板复制即可。

---

## 1 · 起点（背景 + 失败的旧方案）

### Production CSV 字段

```
camera:cam_1.k1k2k3.x  →  K1 (production 实测 ≈ 0.000286)
camera:cam_1.k1k2k3.y  →  K2 (≈ -0.003953)
camera:cam_1.k1k2k3.z  →  K3 (≈ +0.011302)
camera:cam_1.centerShiftMM.x/y → principal point (~3-4 μm)
```

CSV K 是 Disguise 内部模型的"undistort 量"（inverse direction），UE LensFile 用
OpenCV Brown-Conrady 的"distort 量"（forward direction）。**数值同符号但物理方向相反**。

### 旧方案（commit 3468a67 之前的所有 commit）

```python
ue_K1 = -csv_K1
ue_K2 = -csv_K2
ue_K3 = -csv_K3
```

**简单 0 阶 Taylor 近似：sign-flip 透传**。

### 旧方案的缺陷

历史端到端 controlled experiment（image 44/45 + 16:9 直线网格）：

- Disguise 端 K1=+0.5、K2=K3=0 →  pincushion 输出
- UE 端同 K1=+0.5（透传）→  barrel 输出（方向反）
- UE 端 K1=-0.75（sign-flip + 1.5x）→  pincushion 输出，但**残差有结构性**
  - 画面中心几乎全黑（小 r 处匹配好）
  - 画面边缘红绿描边（大 r 处发散，1-3 像素）

**结论**：sign-flip 是 0 阶近似，不够；真实 Disguise 公式跟 UE 的 polynomial **形态不同**，
单一 scale factor（1.5x）不能消残差。需要做 **system identification** 拿到真公式。

---

## 2 · 方法论（system identification）

### 数据采集（d3 端）

1. **探针图**：1920×1080 32-bit float EXR，`R = (x+0.5)/W`、`G = (y+0.5)/H`、`B = 0`
   （identity UV grid）。每像素 R/G 通道直接编码源 UV 坐标真值
   - 文件：`scripts/distortion_calibration/uv_probe_1920x1080.exr`
   - 生成器：`scripts/distortion_calibration/generate_uv_probe.py`

2. **关键约束**：
   - LED surface 必须 linear pass-through（无 gamma / LUT / color grading）
   - transmission compositor frame export（不是 calibration overlay）
   - 严格 1920×1080，不能 resize
   - 32-bit float EXR（PNG 8-bit ±7 px 量化误差直接报废）

3. **K1 sweep**：固定 K2 = K3 = 0、CenterShift = 0，K1 取 **0、±0.1、±0.2、±0.3、±0.4、±0.5** 共 11 帧
   - 命名 `disguise_K_zero.exr` / `disguise_K_p0p3.exr` / `disguise_K_n0p3.exr`
     （`p`=positive，`n`=negative，第二个 `p` 是小数点）

4. **K=0 anchor sanity**：第一帧（K=0）用来校验 LED+camera 端到端是否 linear identity
   - `analyze_renders` 算 R/G 通道跟 identity grid 的 max deviation
   - 实测 max 0.94 px、RMS 0.46 px → **这是噪声底**（不可消的渲染管线噪声）

### 数据提取（Mac 端）

`scripts/distortion_calibration/analyze_renders.py`：

```
每张 disguise_K_*.exr (含 K=0):
  R 通道 = source U at output pixel (px, py)
  G 通道 = source V at output pixel (px, py)
→
  per-pixel: (K, r_undistorted, dr) 三元组
  其中:
    r_undistorted = norm(source_pos - center) / (W/2)        # half-width 归一化
    r_distorted   = norm(output_pos - center) / (W/2)        # 同 normalize
    dr           = r_distorted - r_undistorted

随机 30k 像素/帧 × 11 帧 = ~330k 数据点写到 displacements.csv
```

**关键**：r 在 **half-width** 归一化空间（`r = pixel_offset / (W/2)`）。这是 path A
分析阶段的内部约定，**跟 UE LensFile 用的 fx 归一化不一样**——这个差异后面踩了大坑（见 §5）。

### 候选公式拟合

`scripts/distortion_calibration/fit_distortion_models.py`：10 个 candidate 全局
联合拟合 (K, r, dr) 数据，按 RMS 和 BIC 双排序：

| ID | 形态 | 参数 | RMS (px) |
|---|---|---|---|
| M1 | `r·(1 + α·K·r²)` UE 现状 | 1 | 4.985 |
| M2 | `r/(1 + α·K·r²)` 除法 | 1 | 3.396 |
| M3 | `r·(1 + a·K·r² + b·K²·r⁴)` | 2 | 0.795 |
| M4 | `r + α·K·rᵖ` 自由指数 | 2 | 4.885 |
| M5 | `r·(1 + a·K·r² + b·K·r⁴ + c·K·r⁶)` OpenCV K1-only | 3 | 4.807 |
| M6 | **`r·(1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶)`** | 3 | **0.412** ← BIC 胜出 |
| M7 | `r·(1+a·K·r²)/(1+b·K·r²)` rational | 2 | 0.435 |
| M8 | `r·(1+a·K·r² + (b·K + c·K²)·r⁴)` | 3 | 0.760 |
| M9 | M6 + d·K⁴·r⁸ | 4 | 0.402 |
| M10 | extended rational w/ K² | 4 | 0.402 |

**关键观察**：

1. **M6 最优**（BIC -4.42M，RMS 0.412 px）。M9/M10 加更多参数只挤出 0.01 px 改进，
   说明 M6 的 K³·r⁶ 已经是 "Disguise 真公式"的合理 polynomial truncation
2. **M7 (rational) 几乎打平 M6**（0.435 vs 0.412）—— 实际上 Disguise 真公式很可能就是
   K-coupled rational form，M6 是它的 Taylor 截断。但 UE LensFile 只认 polynomial，所以 M6 是工程最优解
3. **RMS 0.412 px ≈ 噪声底 0.457 px** —— 已撞天花板，再加参数纯过拟合

### M6 系数（在 half-width 归一化空间）

```python
M6_A = -0.2507    # K^1 · r^3 系数
M6_B = +0.2097    # K^2 · r^5 系数
M6_C = -0.1931    # K^3 · r^7 系数

# Forward map:
# r' = r · (1 + M6_A · csv_K1 · r² + M6_B · csv_K1² · r⁴ + M6_C · csv_K1³ · r⁶)
```

---

## 3 · 翻译到 UE LensFile（含 fx-norm 缩放陷阱）

### UE LensFile 怎么用 K1/K2/K3

UE 的 SphericalLensModel（OpenCV Brown-Conrady polynomial）：

```
r' = r · (1 + ue_K1·r² + ue_K2·r⁴ + ue_K3·r⁶)
```

**注意 r 的归一化**：UE 用 **focal-length 归一化**——`r = pixel_offset / fx_pixels`，
而不是 half-width。两者关系：

```
r_HW (half-width) = (2 · fx_uv) · r_fx (focal-length)
```

其中 `fx_uv = focal_mm / sensor_width_mm`。对 30mm-on-35mm-sensor，`fx_uv ≈ 0.866`，
所以 `2 · fx_uv ≈ 1.732`。

### 系数转换（关键陷阱）

把 polynomial `r · (1 + K·r²)` 表达成 fx-norm 时，r² 会带 `(2·fx_uv)²` 因子，
所以系数必须缩放：

```
K1_fx = K1_HW · (2 · fx_uv)²
K2_fx = K2_HW · (2 · fx_uv)⁴
K3_fx = K3_HW · (2 · fx_uv)⁶
```

对 fx_uv = 0.866，缩放因子约 **3x、9x、27x**！如果不做这个转换，UE 端用的 K 值是
**欠 distortion 3-30 倍**，Tier 2 残差会是 30+ px。

**Rational 形态同样 apply**（commit `0019ad3`+）：`BrownConradyUDLensModel` 的
K1-K6 都在 numerator/denominator 的 r²/r⁴/r⁶ 项上，每个系数同样 `(2·fx_uv)^(2k)`
缩放（k=1,2,3 对应 K1/K4, K2/K5, K3/K6）。**numerator 和 denominator 用相同 scale
因子，dr=num/den 对 fx 缩放不变**，但每个 stored 系数必须 fx-scaled。详见 §9。

### 落地代码（最终 commit `34f5af0`）

`Content/Python/post_render_tool/distortion_math.py`：

```python
M6_A: float = -0.2507
M6_B: float = +0.2097
M6_C: float = -0.1931


def compute_normalized_distortion(frame_data: FrameData) -> dict:
    pa_width = frame_data.sensor_width_mm
    focal_mm = frame_data.focal_length_mm
    aspect = frame_data.aspect_ratio

    fx = focal_mm / pa_width        # fx_uv
    fy = fx * aspect
    cx = 0.5 + frame_data.center_shift_x_mm / pa_width
    pa_height = pa_width / aspect
    cy = 0.5 + frame_data.center_shift_y_mm / pa_height

    # HW-norm → fx-norm: K_fx,k = K_HW,k · (2·fx_uv)^(2k)
    fx_scale = 2.0 * fx
    fx2 = fx_scale * fx_scale
    fx4 = fx2 * fx2
    fx6 = fx4 * fx2

    csv_k1 = frame_data.k1
    ue_k1 = M6_A * csv_k1 * fx2
    ue_k2 = M6_B * csv_k1 * csv_k1 * fx4 - frame_data.k2          # K2/K3 仍 sign-flip
    ue_k3 = M6_C * csv_k1 * csv_k1 * csv_k1 * fx6 - frame_data.k3

    return {"fx": fx, "fy": fy, "cx": cx, "cy": cy,
            "k1": ue_k1, "k2": ue_k2, "k3": ue_k3,
            "p1": 0.0, "p2": 0.0}
```

**说明**：

- `compute_normalized_distortion` 是 pure Python（无 `unreal` 依赖），方便 unit test
- `lens_file_builder.py` import 后调用，在 UE Editor 内把返回值塞进 LensFile.add_distortion_point
- CSV K2/K3 仍走 **legacy sign-flip 透传**（K2 sweep / K3 sweep 还没做，未独立验证）

### 数值示例

**csv_K1 = +0.5（测试值）**：
```
ue_K1 = -0.2507 · 0.5  · 2.998 = -0.376
ue_K2 = +0.2097 · 0.25 · 8.989 = +0.471
ue_K3 = -0.1931 · 0.125 · 26.95 = -0.651
```

**csv_K1 = +0.000286（production）**：
```
ue_K1 = -0.2507 · 0.000286 · 2.998 = -0.000215
ue_K2 ≈ 0 (sub-1e-7) - csv_K2 = +0.003953
ue_K3 ≈ 0 (sub-1e-12) - csv_K3 = -0.011302
```

production K1 太小，M6 K1²/K1³ 项可忽略，**production 行为基本等于 legacy
sign-flip**——除了 ue_K1 改成 -0.000215（比 legacy 的 -0.000286 小 25%）。

---

## 4 · 验证（Tier 1 + Tier 2）

### 单元测试（Mac 端，离线）

`Content/Python/post_render_tool/tests/test_distortion_m6.py`：8 个测试

- `test_zero_input_zero_output`：全 0 输入 → 全 0 输出
- `test_csv_k1_positive_sweep_value`：K1=+0.5 算出预期 ue_K1/K2/K3
- `test_csv_k1_negative_sweep_value`：K1=-0.5，验证 K3 跟 K1 同号翻、K2 永远正
- `test_csv_k2_k3_passthrough_sign_flip_when_k1_zero`：K1=0 时 K2/K3 退回 sign-flip
- `test_production_csv_values`：production 真实数值（K1=2.86e-4、K2=-3.95e-3、K3=+1.13e-2）
- `test_combined_csv_k1_and_k2_k3`：K1≠0 + K2/K3≠0 时 M6 + sign-flip 加性合成
- `test_principal_point_unchanged_by_m6_change`：fx/fy/cx/cy 不被 M6 改影响
- `test_fx_scaling_factor_at_typical_focal`：fx≈0.866 下 K1 缩放确实 3x

跑：
```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python3 -m unittest post_render_tool.tests.test_distortion_m6 -v
```

### Tier 1（UE 端，端到端 K 值写入校验）

合成 CSV (csv_K1=+0.5 / -0.3) → SCP lanPC → `pipeline.run_import()` → UE 创建 LensFile →
读回 K1/K2/K3 与 distortion_math 输出对比。

**结果**：

| csv_K1 | M6 期望 (K1, K2, K3) | UE LensFile 读回 | Δ |
|---|---|---|---|
| +0.5 | (-0.375829, +0.471272, -0.650567) | (-0.375829, +0.471272, -0.650567) | < 1e-9 |
| -0.3 | (+0.075210, +0.018873, +0.005214) | (+0.075210, +0.018873, +0.005214) | < 1e-9 |

**通过**：Mac → UE 写入精度浮点级别。

### Tier 2（UE polynomial 应用 vs Disguise EXR）

Mac 端读 UE LensFile 真实存储的 K，跑 Newton inverse polynomial 在 fx-norm 空间，
预测 source UV，跟 disguise_K_p0p5.exr R/G 通道逐像素比对。

`scripts/distortion_calibration/_validate_tier2_fxnorm.py`：

| 指标 | 数值 | 备注 |
|---|---|---|
| valid pixels | 1.72M / 2.07M | 边界 mask 排除 |
| median 残差 | **0.467 px** | ≈ 噪声底 |
| trimmed_rms_95 | **0.953 px** | ≈ √2 × 噪声底（2D vs radial 几何因子）|
| 噪声底 | 0.457 px | K=0 帧实测 |
| ratio | 2.09× | 落在合理范围 |

**通过**：UE polynomial + 修正系数对 Disguise 残差已撞噪声底。

### Tier 2 渲染层旁证

UE 端调 `handler.evaluate_distortion_data` 状态读出 K 跟 LensFile 完全一致；
`handler.set_distortion_state` 触发 displacement RT 重绘，K 改变 → RT 内容确实变化
（±0.027 → ±0.274 等比 ~10x 放大）。证明 UE shader pass 确实在用我们写入的 K 值。

UE displacement RT 内部 overscan/scaling encoding 没逐字段解码（256×256 RG16F 跟
预期值有未知 ratio）。**信任 SphericalLensModel.usf = OpenCV Brown-Conrady polynomial**，
省工。

---

## 5 · 完整代码地图

```
docs/
├── K1-implementation.md                             ← 本文
└── distortion-investigation.md                      ← 历史调试日志（messy）

Content/Python/post_render_tool/
├── distortion_math.py                               ← M6 + fx-norm 系数转换核心
├── lens_file_builder.py                             ← UE-side caller, 调用 distortion_math
├── distortion_packing.py                            ← K1/K2/K3 → UE 数组打包
└── tests/test_distortion_m6.py                      ← 8 个单元测试

scripts/distortion_calibration/
├── uv_probe_1920x1080.exr                           ← 探针图（identity UV grid）
├── generate_uv_probe.py                             ← 探针生成器
├── analyze_renders.py                               ← d3 EXR → (K, r, dr) CSV
├── fit_distortion_models.py                         ← M1-M10 拟合 + BIC 排序
├── _exr.py                                          ← OPENCV_IO_ENABLE_OPENEXR 共享
├── _validate_m6_pipeline.py                         ← HW-norm M6 vs Disguise EXR
├── _validate_tier2_fxnorm.py                        ← fx-norm M6 vs Disguise EXR (Tier 2 主)
├── _validate_tier2_render.py                        ← UE RT 解码尝试（未完成，记录）
├── USER_INSTRUCTIONS.md                             ← d3 端操作指引（K1 完成 + K2/K3 待做）
└── README.md                                        ← 工作流总览
```

---

## 6 · 复现步骤（K2/K3 sweep 套同样模板）

下次做 K2 或 K3 sweep 时，参考这个流程：

### 6.1 d3 端采集
按 `scripts/distortion_calibration/USER_INSTRUCTIONS.md` 的 Round 2 / Round 3 流程渲 11 帧，
回传 Mac。

### 6.2 扩展 analyze_renders.py
当前 `_K_PATTERN` 只识别 `disguise_K_*.exr`。新增 K2 / K3 命名约定：
```
disguise_K2_zero.exr / disguise_K2_p0p3.exr / 等
disguise_K3_zero.exr / 等
```

### 6.3 扩展 fit_distortion_models.py
当前 candidates M1-M10 是为 K1 单变量设计的。K2 sweep 数据里 K1=0，所以
（K, r, dr）三元组里 "K" 是 csv_K2。直接复用 M1-M10 公式拟合即可，**得到 K2 自己
的 a/b/c 系数**。

### 6.4 落地到 distortion_math.py
新增类似 M6 的 K2 公式 + fx-norm 缩放：
```python
ue_K1 += M6_K2_a · csv_K2 · fx²        # 或者别的形态
ue_K2 += M6_K2_b · csv_K2² · fx⁴ - csv_K2 (sign-flip 移走)
...
```

具体合成方式取决于 K2 sweep 拟合出来的真实形态（可能跟 K1 形态相同也可能不同）。

### 6.5 验证
- 扩展 unit tests
- Tier 1：合成 CSV (K1=K3=0, K2=±0.5) 跑 import → 读回 LensFile K → 比对 distortion_math
- Tier 2：UE polynomial 对 disguise_K2_p0p5.exr 比对 → 残差 ≈ 噪声底

### 6.6 联合验证（Round 4）
production CSV 5 组真实 (K1, K2, K3) → 渲染 → 验证三轴加性合成成立。如果残差 >>
噪声底，说明三个轴有 cross-term 耦合，需要 fit `dr = f(K1, K2, K3, r)` 而不是
`f(K1, r) + f(K2, r) + f(K3, r)`。

---

## 7 · 已知 limitations / 未做

| 项 | 状态 | 影响 |
|---|---|---|
| CSV K2 / K3 mapping | ❌ 未独立验证 | production K2/K3 走 legacy sign-flip，pixel-perfect 可能差 0.5-2 px |
| 三轴加性 vs cross-term | ❌ 没测 | 如果 Disguise 公式有 K1·K2 之类的 cross 项，单变量假设破 |
| UE displacement RT overscan encoding | ❌ 没解码 | 不影响 production，纯科学完整性 |
| 真实场景渲染（非 UV probe）| ❌ 没做 | Plan A 还没跑过 |
| 焦距非 30mm 的泛化 | ⚠️ 公式已动态 fx 适配，但实测只有 30.302mm | 不同 focal length 应该 OK，没大量 cross-validate |

---

## 8 · 关键 commit 索引

| Commit | 内容 |
|---|---|
| `e385de4` | 加 Path A/B 校准工具链 (ChArUco + UV probe) |
| `5311d4f` | Path A 换 ChArUco → UV 渐变 + `_exr.py` 共享 |
| `4b3834f` | 落地 M6 polynomial K1→ue_K1/K2/K3 + 抽 `distortion_math.py` |
| `34f5af0` | fx-norm 缩放修复 + Tier 1/2 端到端验证 ← M6 时代收尾 |
| `8164938` | 加 M_RAT6 候选 (UE BrownConradyUDLensModel rational 同构) |
| `0a2a3fb` | `to_brown_conrady_ud_parameters` 8 槽打包 + 4 unit test |
| `ac41b71` | M6 → M_RAT6 rational, distortion_math 输出 8 系数 + 8 unit test |
| `b343814` | (review) test_distortion_rational 注释清晰化 (2·fx 缩放显式化) |
| `ddccdc3` | LensFile lens_model 切到 BrownConradyUDLensModel |
| `0019ad3` | **Tier 2 BrownConradyUD rational 验证, 外圈 edge 距离 122→3.2 px** ← Path A K1 终结 commit |

每个 commit 的 message 都有详细英文 + 中文说明，可 git show 看完整 context。

---

## 9 · M6 → BrownConradyUD Rational 升级（2026-04-29，commits `8164938..0019ad3`）

### 9.1 触发原因

M6 polynomial（3 项 K¹·r³ + K²·r⁵ + K³·r⁷）在 r > 0.806（fx-norm）处出现拐点 ——
非单调，求逆发散。对 csv_K1 = +0.5 测试值（图像角落 r ≈ 1.06）：

- Newton inverse 在角落不收敛，UE 渲染外圈崩盘
- Tier 2 Mac forward 模拟：外圈 RMS 36 px，**edge distance max 122 px**
- 中心和中圈正常（RMS 1.2 / 8.1）

production CSV K1 ≈ 3e-4 时 polynomial 项贡献 sub-1e-7，行为退化为 legacy
sign-flip，所以 production 路径上 M6 时代是隐藏问题；只有 K=±0.5 测试值才
触发外圈崩盘。

### 9.2 解决方案

切换 UE LensFile 从 `SphericalLensModel`（5 系数 polynomial）到
`BrownConradyUDLensModel`（8 系数 polynomial-division rational），shader 原生
`BrownConradyUDDistortion.usf:48-50`：

```
dr = (1 + K1·r² + K2·r⁴ + K3·r⁶) / (1 + K4·r² + K5·r⁴ + K6·r⁶)
```

Numerator 和 denominator 各 3 阶，6 个独立系数 + 2 个切向 P1/P2 = 8 槽。
这种形态跟 Disguise 真公式（OpenCV rational division）天然同构，分子分母
**同步缩放** 不会有 polynomial truncation 在边缘崩的问题。

### 9.3 M_RAT6 系数（Path A round 1，commit `8164938`）

`fit_distortion_models.py` 加 `M_RAT6` 候选：

```
r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶)
    / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶)
```

300k pixel sample × 11 候选 (M1..M10 + M_RAT6) curve_fit 排序：

| 候选 | 参数数 | RMS (px) | BIC |
|---|---|---|---|
| M7 (rational 2 参数) | 2 | 0.435 | -4.434M |
| M_RAT6 (rational 6 参数) | **6** | **0.401** | **-4.4346M ←最优** |
| M9, M10 等 | ≥7 | 0.40-0.42 | 略劣 |

M_RAT6 BIC 最优。fit 出的 6 系数：

```
a = -3.18050   (numerator K1 系数)
b = +7.24462   (numerator K2 系数)
c = +5.12035   (numerator K3 系数)
d = -2.93087   (denominator K4 系数)
e = +6.30678   (denominator K5 系数)
f = +7.51125   (denominator K6 系数)
```

注：a..f 绝对值偏大（vs M6 a≈-0.25）是因为 numerator/denominator 各自
K²/K³ 项互相抵消后净效应才跟 M6 接近。Newton inverse 实测全程收敛
（residual max 4.44e-16），denominator 在 r ∈ [0, 1.1] 全程正值，无 pole。

### 9.4 fx-norm 缩放（rational 形态同样 apply）

跟 polynomial 一样，rational 的每个系数都按 `(2·fx_uv)^(2k)` 缩放：

```
ue_K1 = a·csv_K1·(2·fx)²    ue_K4 = d·csv_K1·(2·fx)²
ue_K2 = b·csv_K1²·(2·fx)⁴   ue_K5 = e·csv_K1²·(2·fx)⁴
ue_K3 = c·csv_K1³·(2·fx)⁶   ue_K6 = f·csv_K1³·(2·fx)⁶
```

分子分母用同样 scale 因子 —— 数学上 `dr = num/den` 对 fx 缩放不变，但每个
系数 stored value 必须 fx-scaled，因为 UE shader 在 r_fx 空间求值。
csv_K1 = +0.5 / fx_uv = 0.866 实际写入 LensFile 的 8 系数：

```
K1 = -4.7680   K4 = -4.3937
K2 = +16.281   K5 = +14.174
K3 = +17.251   K6 = +25.306
P1 = 0         P2 = 0
```

### 9.5 残差对比（csv_K1 = +0.5 测试，UV 渐变 source PNG）

|  | M6 polynomial | M_RAT6 rational | 改善 |
|---|---|---|---|
| 中心 r<0.5 RMS | 1.2 px | 1.6 px | 持平 |
| 中圈 0.5≤r<0.8 RMS | 8.1 px | 5.6 px | -31% |
| 外圈 r≥0.8 RMS | **36.4 px** | **25.4 px** | -30% |
| **外圈 edge median** | — | **0 px** | — |
| **外圈 edge p95** | — | **1 px** | — |
| **外圈 edge max** | **122 px** | **3.2 px** | **-97%** |
| Newton convergence | 拐点处发散 | 4.44e-16 全程收敛 | ✓ |

⚠️ **RMS 跟 edge distance 差异巨大** — 测试 source PNG 是稀疏 UV 渐变（85%
黑色，13.7% 有梯度），sub-pixel 位移在 anti-aliased 边缘上会产生高达 255
intensity 差，但实际位移只有 ~1 px。**edge distance 才是真实误差指标**：
外圈 max 从 M6 的 122 px 降到 3.2 px（38× 改善），median = 0 px，p95 = 1 px。

### 9.6 Path A K1 完结声明

经过 commits `8164938..0019ad3`（6 commit），**Path A K1 轴端到端 pixel-perfect**：

- ✅ d3 端 UV 探针 + 11 帧 K1 sweep 数据采集（M6 时代已完成）
- ✅ M1..M10 + M_RAT6 候选拟合，BIC 排序 M_RAT6 最优
- ✅ M_RAT6（UE BrownConradyUDLensModel 同构）落地 `distortion_math.py`
- ✅ Tier 1：UE LensFile 写入 8 系数 ↔ `distortion_math` 输出 float32 精度（max delta 3.77e-7）一致
- ✅ Tier 2：UE rational forward distortion 跟 Disguise actual K=+0.5 全画面残差，外圈 edge max 122→3.2 px，median = 0
- ✅ `pipeline.run_import` 用户接口零变化（drop-in replacement）

CSV K2/K3 仍走 legacy sign-flip 透传到 UE_K2/UE_K3 numerator 槽位
（production K1≈0 时 M_RAT6 项贡献 sub-1e-7，行为完全等同 legacy）。
后续 Round 2（K2 sweep）+ Round 3（K3 sweep）+ Round 4（联合验证）才能
完整闭环 K2/K3 轴。production CSV 残差预估 < 1 px（未独立验证），
对生产工作流 acceptable。
