# Distortion Calibration Tooling

> **当前路线（2026-05-05 转向）**：**Path C · Custom Post-Process Material**。
> Path A（LensFile + 公式拟合）已结案 NO-GO，Path B（STMap）保留为备胎。
> 完整设计文档见 `docs/custom-postprocess-distortion-final-plan.md`，
> Disguise 端渲染清单见 `docs/d3-distortion-render-request.md`。

| Path | Strategy | 状态 |
|---|---|---|
| **A** — System ID | 反推 Disguise K 公式（11→51 张 K-sweep 拟合 M1..M_RAT8） | **Legacy / 结案 NO-GO**（仍使用 half-width 归一化；不得作为 Path C shader correctness 证据） |
| **B** — STMap direct | 用 Disguise 自渲一张 identity-UV 当 STMap | **搁置备胎**（Round 2.2 验证三轴独立可加，Round 2.3 147 张采集未启动） |
| **C** — Custom Post-Process Material（**当前**） | 写一张 UE post-process material，shader 里直接执行 Disguise 的 `official_sensor_inverse` 公式，绕开 LensFile 公式翻译损耗 | **进行中**（Python reference + HLSL 已切到 sensor full-width；UE validation 单独看 Path C harness） |

**为什么从 A/B 转到 C**：
- **Path A 死锁**：UE LensFile 内置的 BrownConradyUD 公式跟 Disguise 公式形态不同。把 Disguise 系数翻译成 UE 槽位（M_RAT6 / M_RAT8 拟合）做不到 1:1，最低残差 2.5~2.9 像素。模型 mismatch 是物理上限，再 fit 也突破不了。
- **Path B 复杂度过高**：每个镜头 / 每个变焦档要预计算字典，工程量大，量化抖动风险，变焦覆盖代价指数级。
- **Path C 直接路径**：把 Disguise 的公式原样搬进 UE shader（plan §2.4），不做翻译、不做拟合、零残差结构。代价是要建一个 post-process material + 一个 C++ controller component。

各路径共用 `generate_uv_probe.py` + `uv_probe_*.exr` 作为 d3 端探针图。三条路径处理已渲 EXR 的逻辑各自独立。

## Layout

### Shared (both paths)
| File | Role |
|---|---|
| `generate_uv_probe.py` | Produces 32-bit float identity-UV EXR + sanity metadata. |
| `uv_probe_1920x1080.exr` | The probe the user puts on the LED surface in d3. R = U, G = V, B = 0. |
| `uv_probe_truth.npz` | Image dimensions + 4-corner expected R/G values for sanity check. |

### Path A · System identification (UV gradient + curve fitting, legacy half-width)
| File | Role |
|---|---|
| `analyze_renders.py` | Reads each `disguise_K_*.exr`, samples ~30k random valid pixels per frame, emits per-pixel `(K, r_anchor, dr)` records to `displacements.csv`. |
| `fit_distortion_models.py` | Fits 5 candidate formulas globally over all `(K, r, dr)` tuples, with sigma-clipping outlier filter; ranks by RMS and BIC. |
| `USER_INSTRUCTIONS.md` | What the user does in d3 to deliver the 11 K-sweep transmission EXRs. |
| `_self_test_truth.py` | Verifies `uv_probe_1920x1080.exr` matches its identity-grid truth. |
| `_self_test_analyze.py` | Synthesizes K=±0.3 distortion via `cv2.remap`, runs `analyze_renders` end-to-end, checks recovered dr matches `K·r³`. |
| `_self_test_fit.py` | Fits M1-M5 on synthetic α=1.5 polynomial + 0.5 px noise, expects M1 to win on BIC. |

### Path B · STMap direct solve（备胎，未启用）
| File | Role |
|---|---|
| `build_stmap.py` | Reads disguise-rendered EXR, builds bidirectional STMap via scipy griddata cubic. |
| `build_stmap_dict.py` | Round 2.3 字典法构建器（搁置中，等 147 张 sweep 数据）。 |
| `apply_stmap_offline.py` | 离线 STMap 应用 / 验证。 |
| `stmap_lookup.py` | K-indexed 字典查表逻辑。 |
| `_self_test_stmap.py` | `build_stmap` synthetic-data validation. |
| `_self_test_stmap_dict.py` | `build_stmap_dict` synthetic-data validation. |
| `USER_INSTRUCTIONS_PATH_B.md` | Path B 的 Disguise 端采集指引（已搁置）。 |

### Path C · Custom Post-Process Material（当前主路）
| File | Role |
|---|---|
| `check_identity_roundtrip.py` | **Gate 1.5**：cv2.remap identity warp，验证离线 harness 在 K=0 / DistortionWeight=0 时与输入完全一致（已 PASS：max_abs_diff = 0）。 |
| `evaluate_center_shift_sweep.py` | **Legacy Gate 3.5**：旧 `centerShiftMM → CenterUV only` 假设验证；当前已被 D3/UE centerShift 实渲判为语义不足。 |
| `evaluate_k_sweep_custom_formula.py` | **Gate 6**：K2 / K3 在 Disguise 公式里的阶数与符号验证；处理 K2 sweep 5 张 + K3 sweep 5 张 EXR。 |
| `_self_test_custom_gate_eval.py` | 上述三个 gate 评估脚本的自测（K2/K3 公式、CenterUV 公式、p95 stats、文件名解析），离线 PASS。 |
| `../../docs/custom-postprocess-distortion-final-plan.md` | Path C 完整设计文档（1048 行：material graph、C++ controller、pipeline 分流、Gate 0-6 验证体系）。 |
| `../../docs/d3-distortion-render-request.md` | Path C 当前要的 16 张 Disguise 渲染清单。 |

### Environment
| File | Role |
|---|---|
| `.venv/` | Local Python env (cv2 4.13 + scipy + numpy + Pillow); separate from project UE Python. |

## Why UV gradient (vs ChArUco / chess board)

Earlier iterations of Path A used a ChArUco board with corner detection. Rationale for switching to UV gradient:

| | ChArUco corners | **UV gradient** |
|---|---|---|
| Per-frame samples | 276 corners | **2,073,600 pixels** (random subsample to 30k for fit tractability) |
| 11-frame total data | ~3,000 | **~330,000** (100× denser) |
| Per-point precision | 0.02-0.05 px (cornerSubPix saddle-point fit) | **0.001 px** (direct R/G channel read, EXR float quantization) |
| r coverage | r ≤ 0.95 (partial detection at high pincushion K) | **r ≤ 1.13** (full frame, edge-clipped pixels filtered automatically via `VALID_UV_MIN/MAX`) |
| Topology / ordering | sort-by-y bin (fragile under tangential distortion) | **N/A** — each pixel is self-identifying via its position |
| Detection algorithm | `CharucoDetector` + `cornerSubPix` (multiple failure modes under heavy distortion) | **None** — read R/G channel directly |

The high-r data points are critical: candidate distortion models diverge most at r > 0.7. UV gradient samples the full radial range natively.

## Probe specs (locked)

- 1920×1080 grayscale-float EXR, 3 channels
- R channel = (x + 0.5) / W (pixel-center U coord, identity in [0, 1])
- G channel = (y + 0.5) / H (pixel-center V coord)
- B channel = 0
- 32-bit float; PNG and 16-bit half are NOT supported (quantization error >0.5 px)
- File: `uv_probe_1920x1080.exr` (~220 KB), `uv_probe_truth.npz` (sanity metadata)

## Usage

### One-off setup
```bash
cd scripts/distortion_calibration
python3 -m venv .venv
.venv/bin/pip install --quiet numpy scipy opencv-python-headless pillow
.venv/bin/python generate_uv_probe.py
```

### Validate pipeline (rerun after any edit)
```bash
.venv/bin/python _self_test_truth.py
.venv/bin/python _self_test_analyze.py
.venv/bin/python _self_test_fit.py
```

### Process a Path C delivery（16 张 EXR，当前主路）

放在 `validation_results/custom_pp_gate_inputs/` 下，按 `docs/d3-distortion-render-request.md` 的目录布局。

```bash
# 先跑 self-test（无需输入数据）
.venv/bin/python _self_test_custom_gate_eval.py
.venv/bin/python check_identity_roundtrip.py     # Gate 1.5（已 PASS）

# 等 16 张到货后跑：
.venv/bin/python evaluate_center_shift_sweep.py \
    --input-dir validation_results/custom_pp_gate_inputs/center_shift_sweep
.venv/bin/python evaluate_k_sweep_custom_formula.py \
    --validation-root validation_results
```

输出 JSON + Markdown 写到 `/Volumes/Docs/temp/k_sweep/gate3_5_*` 与 `gate6_*`，供冻结 shader 公式形态使用。

### Process a Path A delivery（结案，仅作历史参考）
```bash
# Round 1 / Round 2.1 用过；不再继续采集
.venv/bin/python analyze_renders.py --input-dir /tmp/disguise_renders
.venv/bin/python fit_distortion_models.py
```

`fit_distortion_models.py` ranks by **BIC**（penalizes free parameters）。M_RAT6 / M_RAT8 在 Round 2.1 已确认 **NO-GO**。

### Process a Path B delivery（搁置）
```bash
.venv/bin/python build_stmap.py --input /tmp/disguise_stmap/disguise_uvprobe.exr
# 后续 UE 端走 stmap_writer.py 注入 LensFile（备胎，未启用）
```

## Candidate models (Path A)

| Model | Forward map (undist r → dist r') | # free params |
|---|---|---|
| M1 | `r * (1 + α·K·r²)`                          UE-current shape | 1 (α) |
| M2 | `r / (1 + α·K·r²)`                          division model | 1 (α) |
| M3 | `r * (1 + a·K·r² + b·K²·r⁴)`               mixed K-order | 2 |
| M4 | `r + α·K·rᵖ`                                free radial exponent | 2 |
| M5 | `r * (1 + a·K·r² + b·K·r⁴ + c·K·r⁶)`       OpenCV K1-only style | 3 |

If M5 wins with `a≈1, b≈0, c≈0`, Disguise is standard OpenCV polynomial — Path A's reverse calc reduces to copying coefficients into UE LensFile K1/K2/K3.
If M2/M3/M4 wins, Disguise's formula doesn't match UE's polynomial form — UE LensFile can only best-fit-approximate, not pixel-perfect (this is the known polynomial ceiling).

## Conventions

- **Pixel coordinates**: OpenCV pixel-center origin (pixel (0,0) = top-left **center**).
- **r normalization**: `r = sqrt(dx² + dy²) / (W/2)`, so `r = 1` at the horizontal image edge.
- **K sign**: matches Disguise CSV (`K1=+0.5` means pincushion in Disguise convention).
  Sign-flip into UE LensFile happens later in `lens_file_builder.py`, not here.

## Path A — analyze_renders details

Path A 是 legacy system-identification pipeline，当前仍按 camera half-width
归一化。这个语义与 Path C 的 sensor full-width shader reference 不同；Path A
残差不能用来证明或否定 Path C shader correctness。

`analyze_renders.py` per-frame logic:
1. Read EXR, extract R/G channels (cv2 BGR storage, `[..., 2]` = R, `[..., 1]` = G)
2. Per output pixel (px, py):
   - `r_distorted = norm((px+0.5 - cx, py+0.5 - cy)) / half_width`
   - `r_undistorted = norm((R*W - cx, G*H - cy)) / half_width`
   - `dr = r_distorted - r_undistorted`
3. Filter: `0.005 < R, G < 0.995` (drop edge-clipped / off-FOV pixels)
4. Random subsample to `SAMPLES_PER_FRAME = 30000` (reproducible via `--seed`)

Anchor sanity check on the optional `disguise_K_zero.exr`:
- Verify R ≈ identity U-grid, G ≈ identity V-grid
- If max deviation > 1%, warn — likely LED gamma not linear / color transform applied / wrong frame export type

---

## Path C · Custom Post-Process Material 原理

### 核心思路

不再翻译 K 公式。Disguise CSV 里 K1/K2/K3 直接喂给一个 UE 自定义 post-process material；`centerShiftMM` 同时喂给 UE CineCamera Filmback projection offset 和 material `CenterUV`。material 内部 shader 跑 `official_sensor_inverse` 公式，逐像素采样原图扭曲一次输出。

```
CSV (per frame)
  → CineCameraActor 渲常规图（无 LensFile distortion）
  → CineCamera Filmback.SensorHorizontalOffset/SensorVerticalOffset 应用 principal-point shift
  → post-process material 用 K1/K2/K3/CenterUV 扭曲一次
  → MRQ EXR 输出（Disguise pixel-perfect）
```

### Shader 公式（plan §2.4）

`r` 用 sensor full-width 归一化（2026-05-06 Normalization Gate 结论；详见 `docs/distortion-investigation.md`）。

```hlsl
float2 d  = UV - CenterUV;
float2 r  = float2(d.x, d.y / Aspect);
float r2  = dot(r, r);
float fac = K1 * r2 + K2 * r2 * r2 + K3 * r2 * r2 * r2;
float2 sourceUV = UV + fac * d * DistortionWeight;
// sourceUV 越界 → black，匹配离线 cv2.remap constant border
```

跟 Path A 的本质区别：**这是直接执行公式，不是去拟合 UE 槽位**。Path A 在 LensFile 里只能写 K1..K6 / P1 / P2 八个固定槽，shader 形态由 UE 决定；Path C shader 由我们决定，参数随便加，公式随便改。

### CenterShift 单位映射

```
Filmback.SensorHorizontalOffset = -centerShiftMM.x        # X 反号
Filmback.SensorVerticalOffset   = -centerShiftMM.y        # Y 反号
CenterU = 0.5 + centerShiftMM.x / sensorWidthMM
CenterV = 0.5 + centerShiftMM.y / (sensorWidthMM / aspect)
```

公式由 2026-05-07 K=0 控制帧 phase-correlate (D3 端) + UE pipeline + MRQ 闭环渲染
(UE 端) 双向定型: D3 cs=±0.5mm + K1=K2=K3=0 → 画面平移 ±27.5px (sensor 35mm ×
1920×1080), UE Filmback 内部按 `image_dim/sensor_dim` 转 px 等价于 `0.5/35×1920
= 27.43px`. UE 闭环 max |Δshift| = 0.16 px, cross-render UE vs D3 phase-correlate
≈ (0, 0). 跟 focal length 完全无关。两轴反号是因为 UE Filmback `Sensor*Offset`
跟 D3 `centerShiftMM` 对"光心偏方向"的定义在 X 和 Y 上都相反.
production import **始终启用** Filmback projection tracks（无开关）。

旧路径回顾（仅供 git log 解读）：
- 早期 `centerShiftMM → CenterUV-only` 假设破产（D3 实测产生 27px 级位移，CenterUV-only 只
  产生 0.5–1.3 px）。详见 `docs/distortion-investigation.md` "2026-05-06 — centerShift Projection Re-derivation"。
- 中期 RenderStream NDC 公式（除以 focal）破产（预测 ±9/16 px，实测 ±27.5 px）。详见
  `docs/distortion-investigation.md` "2026-05-06 — RenderStream NDC mapping discovery"。
- 当前公式见 `docs/distortion-investigation.md` "2026-05-07 — K=0 直接测量"。
- `ue_center_shift_projection_sweep.py` / `center_shift_offline_simulation.py` 已废弃, runtime raise.

### Gate 体系（plan §5 节选）

| Gate | 验什么 | 状态 |
|---|---|---|
| Gate 0 | 公式候选可用性（per-bucket p95 < 1.5 px） | NO-GO（Path A LensFile 形态限制） |
| Gate 1 | Pure-Python 公式单元测试（K=0 identity，K1=+0.5 边缘方向，aspect normalization） | 待写（`tests/test_custom_postprocess_distortion_math.py`） |
| Gate 1.5 | 离线 cv2.remap identity round-trip | **PASS**（max_abs_diff = 0） |
| Gate 2 | offline shader-equivalent CPU reference（跟 plan §2.4 公式严格等价的 numpy 版） | 待写 |
| Gate 3 | UE viewport / MRQ K1=+0.5 单帧 | 待跑（依赖 material 资产 + C++ controller） |
| Gate 3.5 | centerShiftMM → Filmback projection offset + CenterUV 单位 / 符号 | 用 `ue_center_shift_projection_sweep.py` 跑 sign sweep |
| Gate 4 | 真实 take_16 CSV vs Disguise reference | 待跑 |
| Gate 5 | zoom-changing K sequence | 待跑 |
| Gate 6 | K2 / K3 公式形态确认 | 等 K2 sweep 5 张 + K3 sweep 5 张 EXR |

### 当前 Disguise 端要渲的 16 张参考帧

详见 `docs/d3-distortion-render-request.md`。摘要：

| Set | 张数 | 用途 |
|---|---|---|
| A · K2 sweep | 5 | K1=K3=0，K2 ∈ {±0.5, ±0.3, 0} |
| A · K3 sweep | 5 | K1=K2=0，K3 ∈ {±0.5, ±0.3, 0} |
| B · centerShiftX sweep | 5 | K1=K2=K3=0，shiftX ∈ {±0.10, ±0.05, 0} |
| C · identity baseline | 1 | 全零，干净基线 |

格式：3840×2160 32-bit float OpenEXR，linear，no LUT，1.5× lens over-scan，命名约定见 d3-distortion-render-request.md。

### 进度（2026-05-05）

| 阶段 | 状态 |
|---|---|
| 计划文档 | ✅ commit `803dfa8` |
| Gate harness 自测 | ✅ self-test PASS |
| Gate 1.5 离线验证 | ✅ PASS |
| Disguise 16 帧 | 🚧 渲染中 |
| `DistortionMode` 开关 + Gate 1 unit test | ⏳ 即将开工 |
| C++ Controller component | ⏳ 即将开工（需 UE Editor 重启 + UBT rebuild） |
| Material 资产（lanPC 手工建） | ⏳ 待开工 |
| Pipeline 分流脚手架（默认仍走 LEGACY） | ⏳ 待开工 |
| Gate 3 / 3.5 / 6 实测验证 | 等帧到货 |
