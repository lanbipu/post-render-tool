# Custom Post-Process Distortion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏当前 PostRenderTool production 结果的前提下，新增一条 `Custom Post-Process Material` 畸变路线，让 UE MRQ 渲染结果尽量匹配 Disguise Designer 的 CSV K1/K2/K3 distortion。

**Architecture:** 保留现有 `CSV -> CineCameraActor -> LevelSequence -> MRQ` 主流程，只把 distortion stage 从标准 UE `LensFile + LensComponent` 改成一个可隔离启用的 post-process shader。CSV 每帧的 `K1/K2/K3/centerShift/focalLength` 进入 Sequencer，驱动一个 `PostRenderDistortionController`，控制同一张 `Material` 的参数。

**Tech Stack:** UE 5.7 plugin, Python Editor scripting, C++ `UActorComponent`, UE `Post Process Material`, `UMaterialInstanceDynamic`, `LevelSequence`, MRQ.

---

## 0. 当前结论

最终推荐路线：

```text
Disguise Dense CSV
  -> parse camera transform / focal / aperture / focus / K / centerShift
  -> create or reuse CineCameraActor
  -> create LevelSequence keyframes
  -> attach one Custom Post-Process Material
  -> keyframe material/controller parameters per frame
  -> MRQ render final distorted image
```

不推荐继续把新公式塞进标准 UE `LensFile` 的 `BrownConradyUD` 或 `BrownConradyDU` model 里作为最终方案。

原因不是 `LensFile` 不能渲染 distortion，而是它的标准 pipeline 会引入 UE 自己的模型语义、Focus/Zoom 查表、overscan、displacement RT、handler 方向、MRQ post-process 行为。我们现在需要的是逐像素复现 Disguise 的 `official_sensor_inverse` sampling map；这件事用自定义 post-process shader 更直接。

当前实现必须是测试阶段：

- 默认 production path 保持现状，继续可用 `LensFile + M_RAT6`。
- 新路线用显式 `DistortionMode=CustomPostProcess` 或 UI toggle 启用。
- 新路线全部通过单帧、K sweep、MRQ diff 验证后，才允许成为默认。

---

## 1. 为什么不继续使用 LensFile

### 1.1 标准 LensFile 是 Focus/Zoom 表，不是 K1/K2/K3 三轴公式容器

UE `ULensFile` 的数据入口是 lens calibration 表：

- `DistortionTable`
- `FocalLengthTable`
- `ImageCenterTable`
- `STMapTable`

这些表的 key 是 `Focus` 和 `Zoom`。UE source 里 `AddDistortionPoint` 和 `AddSTMapPoint` 都是：

```cpp
AddDistortionPoint(float NewFocus, float NewZoom, ...)
AddSTMapPoint(float NewFocus, float NewZoom, ...)
```

所以它天然适合表达：

```text
focus + focal length -> lens calibration state
```

但我们现在的输入是：

```text
frame -> K1/K2/K3/centerShift/focalLength
```

如果 K 随 frame 或 zoom 变化，标准 LensFile 只能把它们间接塞进 `Focus/Zoom` 表。这样做可以工作一部分场景，但不是最直接的表达，也不适合三轴 K dictionary。

### 1.2 LensFile 的 Parameters mode 会走 UE 的 lens model，不是我们的公式

UE `EvaluateDistortionData()` 明确按 `DataMode` 分支：

```cpp
if (DataMode == ELensDataMode::Parameters)
{
    return EvaluateDistortionForParameters(...);
}
else
{
    check(DataMode == ELensDataMode::STMap);
    return EvaluateDistortionForSTMaps(...);
}
```

当前 PostRenderTool 的 production path 调 `build_lens_file()`，写的是 `Parameters` table，并把 CSV K 转成 `BrownConradyUDLensModel` 的 8 个参数槽。这个方案的本质是：

```text
Disguise CSV K -> 拟合/翻译成 UE BrownConradyUD parameters -> UE LensComponent 渲染
```

它不是：

```text
Disguise CSV K -> 直接执行 Disguise-like official_sensor_inverse formula
```

这就是之前 K1=+0.5 离线图看起来对，但塞回 LensFile/MRQ 后网格形状仍不一致的根本原因。

### 1.3 LensComponent 会额外参与 overscan 和 rendering mode 决策

`LensComponent` 每帧会：

- 根据 `EvaluationMode` 取 `Focus/Zoom`。
- 调 `LensFile->EvaluateDistortionData(...)`。
- 计算或缩放 `OverscanFactor`。
- 把 `LensDistortionHandler` 的 MID 挂到 camera blendables，或者走 SceneViewExtension。
- 在 `bOverrideCameraOverscan` 时修改 `CineCameraComponent.Overscan` 和 crop 行为。

这套逻辑对 UE 原生 calibration 是合理的，但对我们要复刻的离线 `cv2.remap official_sensor_inverse` 不透明。实测里，即使手动尝试：

- `BrownConradyDULensModel`
- `BrownConradyUDLensModel`
- `K1=+0.5`
- `FxFy=(1.0, aspect)`
- 清理 camera overscan

MRQ 输出仍没有匹配离线 approved image。典型观察：

```text
offline official_sensor_inverse bbox: x=201..3638, y=53..2107
UE MRQ LensFile DU test bbox:       x=479..3360, y=233..2013
```

这个差异不是黑边问题，而是 distortion field 本身不同。

### 1.4 当前 LensFile builder 会按 focal length 合并帧

`lens_file_builder._group_by_focal_length()` 当前只按 `focal_length_mm` 分组，并取第一帧作为代表。这个行为对固定焦距、K 不变的 CSV 可以接受；但如果 zoom 过程中 K 或 centerShift 每帧变化，它会丢掉同一 focal group 里的变化。

对变焦镜头，正确表达应该是：

```text
frame N:
  focalLength = F_N
  K1/K2/K3 = K_N
  centerShift = C_N
```

这些值都应该进入 Sequencer 或 runtime controller，而不是被压成少量 focal groups。

### 1.5 STMap 也不是首选 production 方案

UE `LensFile` 的 `STMap` mode 确实能表达每像素 map，但它仍然是 `Focus/Zoom` keyed table。对于任意 K 组合，若使用 STMap，就意味着：

- 每个 K state 要有一张 map，或者
- 把 K 映射成 fake focus/zoom，或者
- 自己写 custom runtime。

如果公式已经基本明确，`Custom Post-Process Material` 更轻：

- 一张 material 处理所有 K。
- 每帧只改 scalar/vector parameters。
- 不生成大量 4K EXR/Texture asset。
- 不受 LensFile STMap table 的 Focus/Zoom key 限制。

STMap 保留为 fallback：如果 K2/K3 后续证明不是简单 polynomial/radial 公式，或者 Disguise 有非公式化行为，再考虑 STMap。

---

## 2. Custom Post-Process Material 的技术原理

### 2.1 Material 是公式模板，不是一张图

`Custom Post-Process Material` 可以理解成一段 GPU shader：

```text
每个 output pixel 执行一次：
  读取当前 pixel 的 UV
  根据 K1/K2/K3/centerShift 算 source UV
  从 PostProcessInput0 的 source UV 采样颜色
  输出这个颜色
```

所以不需要每个 K 值生成一张 material。只需要：

- 一张 `Material`：固定公式。
- 一个 `MaterialInstanceDynamic`：运行时参数。
- 多个 scalar/vector parameters：`K1/K2/K3/CenterUV/Aspect` 等。

变焦或 K 变化时，只是参数变化，公式模板不变。

### 2.2 当前公式状态

当前被用户认可的是单帧离线视觉 reference，不是可冻结的全数据公式。

```text
Gate 0 result (2026-05-04): NO-GO
simple official_sensor_inverse p95: 484.056 px
failed radius x |K| buckets: 12 / 12
valid-mask mismatch: 12.337%
```

同口径复核:

```text
M_RAT6_deployable_round2_1 p95: 2.867 px, failed buckets 14 / 14
M_RAT8_bic_best_round2_1  p95: 2.511 px, failed buckets 14 / 14
```

结论:

- `Material + MID + C++ controller + Sequencer track` 脚手架仍可继续，因为它和公式形态解耦。
- 不能把下面的简单 polynomial 作为 frozen shader math。
- `Custom STMap Material` / dictionary route 不依赖 Gate 0 通过，仍保留为 fallback。
- 新公式必须等 K2/K3 sweep 和 centerShift sweep 后再冻结。

历史离线测试图来自：

```text
/Volumes/Docs/temp/LS_shot_1_take_15_dense.0000_K1_p0p5_official_sensor_inverse.png
```

其 JSON metadata 记录：

```text
algorithm: official_sensor_inverse
normalization: sensor_width
direction: output_to_source sampling map
k1: 0.5
k2: 0.0
k3: 0.0
pixel_convention: pixel_center, UV=(x+0.5)/W
interpolation: cv2.INTER_LINEAR
border: constant black
```

Material 第一版可以复刻这个 sampling map 作为 engineering harness，但不能作为 production
formula 默认值。

### 2.3 Pixel-space 公式

> **2026-05-06 归一化 Gate 结论**：full-width（除以 W）比 half-width（除以 W/2）在
> K1+K2+K3 联合 sweep 上低 466–567× 残差。下方公式已更新为 full-width。
> 证据见 `docs/distortion-investigation.md` § "2026-05-06 — Normalization Gate"。

设：

```text
W, H       = render resolution
aspect     = W / H
cx, cy     = distortion center in pixel index space
norm       = W                              # sensor full-width, x/y 同尺度
x, y       = output pixel index center
K1/K2/K3   = CSV distortion coefficients for current frame
```

使用 sensor full-width normalization（横纵同除以 W）：

```text
dx_norm = (x - cx) / norm
dy_norm = (y - cy) / norm
r2 = dx_norm^2 + dy_norm^2
factor = K1*r2 + K2*r2^2 + K3*r2^3

source_x = x + factor * (x - cx)
source_y = y + factor * (y - cy)
```

然后从 `source_x/source_y` 对 `PostProcessInput0` 做 bilinear sampling。

### 2.4 UV-space shader 公式

在 UE material 里更自然的写法是 UV（UV 原点已是归一化空间，d.x ∈ [-0.5, 0.5]，即天然除以 W）：

```hlsl
float2 d = UV - CenterUV;
float2 r = float2(d.x, d.y / Aspect);

float r2 = dot(r, r);
float factor = K1 * r2 + K2 * r2 * r2 + K3 * r2 * r2 * r2;

float2 sourceUV = UV + factor * d;
```

说明：

- `r.x = d.x` 对应 `x / W` (sensor full-width)。
- `r.y = d.y / Aspect` 对应 `y / W`，横竖同尺度归一化。
- `sourceUV = UV + factor*d` 对应 `source_pixel = pixel + factor*(pixel-center)`。
- 如果 `sourceUV` 超出 `[0,1]`，输出 black，匹配离线 `constant black border`。

Material graph 可以用 `SceneTexture:PostProcessInput0` 节点采样，也可以在 `Custom` HLSL node 里调用 `SceneTextureLookup`。优先用 UE graph 原生节点，避免硬编码 scene texture index。

### 2.5 CenterShift 映射

沿用当前 PostRenderTool 的中心点换算：

```text
CenterU = 0.5 + centerShiftMM.x / sensorWidthMM
sensorHeightMM = sensorWidthMM / aspect
CenterV = 0.5 + centerShiftMM.y / sensorHeightMM
```

这部分必须单独做 centerShift 验证，因为它和 K1/K2/K3 是不同问题：

- K 验证证明 radial distortion shape。
- centerShift 验证证明 principal point offset 的单位和符号。

---

## 3. 变焦镜头工作流

### 3.1 一张 Material 处理所有 K

变焦期间不需要生成多张 material。

正确结构：

```text
M_PRT_OfficialSensorInverse
  Parameters:
    K1
    K2
    K3
    CenterUV
    Aspect
    DistortionWeight
```

每个 camera/take 创建一个 `MaterialInstanceDynamic`，Sequencer 每帧更新 controller 的参数。Controller 再把参数推给 MID。

### 3.2 CSV 有 per-frame K 时

如果 CSV 每帧有 K：

```text
frame 1001: focal=24.0, K1=..., K2=..., K3=..., centerShift=...
frame 1002: focal=24.1, K1=..., K2=..., K3=..., centerShift=...
frame 1003: focal=24.2, K1=..., K2=..., K3=..., centerShift=...
```

PostRenderTool 应直接写 Sequencer tracks：

- `CineCameraComponent.CurrentFocalLength`
- `PostRenderDistortionController.K1`
- `PostRenderDistortionController.K2`
- `PostRenderDistortionController.K3`
- `PostRenderDistortionController.CenterU`
- `PostRenderDistortionController.CenterV`

这样 zoom 和 distortion 是同一时间轴上的关键帧，不需要查表。

### 3.3 CSV 只有 sparse K 时

当前 parser 对 lens/optics 字段使用 carry-forward 逻辑。也就是说 Disguise CSV 如果只在变化时写 K，空白帧会继承上一帧。这个行为适合 Sequencer keyframes。

导入策略：

- 保留 frame cadence。
- 对连续相同值可以优化 keyframe 数量。
- 初期为了验证，先每帧写 key，避免优化引入误判。

### 3.4 CSV 没有 per-frame K 时

如果未来某些 CSV 只有 focal length，没有每帧 K，就需要 calibration table：

```text
focalLength/focus -> K1/K2/K3/centerShift
```

但这个 table 应由 PostRenderTool 自己评估后写到 controller parameters，不建议塞回 UE LensFile 作为最终 distortion path。

---

## 4. 实现设计

### 4.1 新增 DistortionMode

新增配置：

```python
class DistortionMode:
    LEGACY_LENS_FILE = "legacy_lens_file"
    CUSTOM_POST_PROCESS = "custom_post_process"
    NONE = "none"
```

默认值：

```python
DISTORTION_MODE = DistortionMode.LEGACY_LENS_FILE
```

测试期间必须默认 legacy，避免影响已有项目成果。

### 4.2 C++ Controller Component

新增 C++ component：

```text
Source/PostRenderTool/Public/PostRenderDistortionControllerComponent.h
Source/PostRenderTool/Private/PostRenderDistortionControllerComponent.cpp
```

职责：

- 持有可被 Sequencer keyframe 的 `UPROPERTY`：
  - `K1`
  - `K2`
  - `K3`
  - `CenterU`
  - `CenterV`
  - `Aspect`
  - `DistortionWeight`
- 持有 `UMaterialInterface* BaseMaterial`。
- 创建并缓存 `UMaterialInstanceDynamic* MID`。
- 将 MID 添加到 owner camera 的 `PostProcessSettings.WeightedBlendables`。
- 在 `TickComponent` 或 property update 时调用：
  - `MID->SetScalarParameterValue("K1", K1)`
  - `MID->SetScalarParameterValue("K2", K2)`
  - `MID->SetScalarParameterValue("K3", K3)`
  - `MID->SetVectorParameterValue("CenterUV", FVector(CenterU, CenterV, 0))`
  - `MID->SetScalarParameterValue("Aspect", Aspect)`
  - `MID->SetScalarParameterValue("DistortionWeight", DistortionWeight)`

为什么需要 C++ component：

- Sequencer 对普通 UPROPERTY float track 支持稳定。
- Python 每帧直接更新 material parameter 不适合 MRQ 离线渲染。
- MID 生命周期和 camera blendable 管理放 C++ 更可靠。

### 4.3 Material Asset

新增或部署一个 UE material：

```text
Content/Materials/M_PRT_OfficialSensorInverse.uasset
```

Material 设置：

```text
Material Domain: Post Process
Blendable Location: After Tonemapping
Output: Emissive Color
```

默认用 `After Tonemapping`。如果后续要对 linear HDR stage 做专门验证，可以单独加一轮
`Before Tonemapping` A/B，但不能改默认验证路径。

Material 参数：

```text
K1: Scalar
K2: Scalar
K3: Scalar
CenterUV: Vector2 via Vector parameter
Aspect: Scalar
DistortionWeight: Scalar
```

核心 Material graph 逻辑：

```text
ScreenPosition(ViewportUV)
  -> subtract CenterUV
  -> build sensor-width normalized radius using Aspect
  -> evaluate current formula candidate
  -> sourceUV = UV + formulaOffset * DistortionWeight
  -> compare sourceUV against [0,1]
  -> SceneTexture:PostProcessInput0 sampled at sourceUV
  -> If sourceUV out of bounds, output black
  -> Emissive Color
```

不要在计划里写死 `SamplePostProcessInput0(...)` 伪函数。实际资产用
`SceneTexture:PostProcessInput0` graph node 采样。

### 4.4 Python pipeline branch

现有 `run_import()` 流程：

```text
parse CSV
build LensFile
build CineCameraActor + LensComponent
build LevelSequence
generate report
```

新流程：

```text
parse CSV
if LEGACY_LENS_FILE:
    build LensFile
    build camera with LensComponent
if CUSTOM_POST_PROCESS:
    skip LensFile for distortion
    build camera without active LensComponent distortion
    attach PostRenderDistortionController
build LevelSequence
if CUSTOM_POST_PROCESS:
    keyframe controller K/center/aspect tracks
generate report
```

LensFile 可以仍然创建为 debug/fallback asset，但不能参与最终 custom post-process distortion。

### 4.5 Camera builder change

`camera_builder.py` 需要分成两种配置：

```python
build_camera(..., distortion_mode="legacy_lens_file")
```

行为：

- `legacy_lens_file`：
  - 保持现有 LensComponent 配置。
- `custom_post_process`：
  - 不启用 `LensComponent.apply_distortion`。
  - 清理已有 camera 上的 LensComponent distortion state。
  - 清理 `CineCameraComponent.Overscan`，避免上一次 LensComponent 测试残留。
  - 添加/复用 `PostRenderDistortionControllerComponent`。

### 4.6 Sequence builder change

`sequence_builder.py` 需要在 custom mode 绑定 controller component，并添加 float tracks：

```text
K1
K2
K3
CenterU
CenterV
Aspect
DistortionWeight
```

初期实现每帧都写 key：

```text
frame_number = frame.frame_number - first_frame_number
K1 = frame.k1
K2 = frame.k2
K3 = frame.k3
CenterU = 0.5 + frame.center_shift_x_mm / frame.sensor_width_mm
CenterV = 0.5 + frame.center_shift_y_mm / (frame.sensor_width_mm / frame.aspect_ratio)
Aspect = frame.aspect_ratio
DistortionWeight = 1.0
```

后续可以优化相同值 key，但验证阶段不要优化。

---

## 5. 验证计划

### Gate 0: all-data bucket readiness

目标：先判断候选公式是否值得冻结到 shader math。

输入：

```text
/Volumes/Docs/temp/k_sweep/displacements.csv
/Volumes/Docs/temp/k_sweep/disguise_K1_*.exr
```

输出：

```text
/Volumes/Docs/temp/k_sweep/gate0_official_sensor_inverse_readiness.md
/Volumes/Docs/temp/k_sweep/gate0_formula_candidate_buckets.md
```

当前结果：

```text
simple official_sensor_inverse: NO-GO, p95 484.056 px
M_RAT6_deployable_round2_1:     NO-GO, p95 2.867 px
M_RAT8_bic_best_round2_1:       NO-GO, p95 2.511 px
```

通过标准：

```text
every radius x |K| bucket p95 < 1.5 px
valid-mask mismatch classified and explainable
```

Gate 0 当前不通过。继续工程脚手架可以，但公式部分必须保持可替换。

### Gate 1: pure math unit tests

目标：公式和参数映射先在 Python 层闭环。

新增测试：

```text
Content/Python/post_render_tool/tests/test_custom_postprocess_distortion_math.py
```

覆盖：

- `K=0` 时 `sourceUV == UV`。
- `K1=+0.5` 时 center 不动、边缘按 expected direction 移动。
- `Aspect=16/9` 时 Y normalization 使用 sensor width。
- centerShift 改变时 distortion center 改变。
- out-of-bounds sourceUV 返回 black mask。

### Gate 1.5: identity round-trip

目标：验证离线 `cv2.remap` harness 在 `K=0, DistortionWeight=0` 时不引入差异。

命令：

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
scripts/distortion_calibration/.venv/bin/python scripts/distortion_calibration/check_identity_roundtrip.py
```

输出：

```text
/Volumes/Docs/temp/k_sweep/gate1_5_identity_roundtrip.json
```

当前结果：

```text
PASS
max_abs_diff = 0
changed_values = 0
input = /Volumes/Docs/temp/LS_shot_1_take_15_dense.0000.jpeg
```

通过标准：

```text
max_abs_diff = 0
changed_values = 0
```

UE 端 identity 在 Task 5 完成后再跑 MRQ 实测，不能用这个离线 Gate 代替。

### Gate 2: offline shader-equivalent reference

目标：生成一张和 Material 公式完全等价的 CPU reference。

输入：

```text
/Volumes/Docs/temp/LS_shot_1_take_15_dense.0000.jpeg
```

输出：

```text
/Volumes/Docs/temp/LS_shot_1_take_15_dense.0000_K1_p0p5_custom_pp_reference.png
```

要求：

- 与已认可的 `official_sensor_inverse` 图做 image diff。
- displacement bbox 和网格形状一致。
- 黑边差异单独统计，不混入 distortion shape 判断。

### Gate 3: UE viewport/MRQ single-frame K1=+0.5

目标：确认 UE material/MRQ 和 offline reference 一致。

步骤：

1. 创建一个只渲染测试网格的 sequence。
2. 设置 `K1=+0.5, K2=0, K3=0, CenterUV=(0.5,0.5)`。
3. MRQ 输出 3840x2160 EXR。
4. 与 offline reference 做：
   - bbox comparison
   - absolute difference heatmap
   - grid line overlay comparison

MRQ 设置：

```text
Output format: EXR
Anti-aliasing: off
TAA/TSR: off
Plate: UV gradient plate
```

通过标准：

```text
distortion field shape visibly identical
p95 displacement residual < 1 px
max residual excluding black border and AA edges < 2 px
```

最终阈值以后续实测收紧。

### Gate 3.5: centerShift-only sweep

目标：验证 `centerShiftMM -> CenterUV` 的单位和符号，不混入 K distortion。

输入：`docs/d3-distortion-render-request.md` 的 Set B。

最低帧集：

```text
K1=K2=K3=0
centerShiftMM.x in {-0.10, -0.05, 0.00, +0.05, +0.10}
centerShiftMM.y = 0
```

命令：

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
scripts/distortion_calibration/.venv/bin/python scripts/distortion_calibration/evaluate_center_shift_sweep.py \
  --input-dir validation_results/custom_pp_gate_inputs/center_shift_sweep
```

输出：

```text
/Volumes/Docs/temp/k_sweep/gate3_5_center_shift_sweep.json
/Volumes/Docs/temp/k_sweep/gate3_5_center_shift_sweep.md
```

通过标准：

```text
measured sourceUV shift direction matches CenterU = 0.5 + centerShiftMM.x / sensorWidthMM
residual after best-fit sign/unit mapping is at the existing EXR quantization floor
```

### Gate 4: take_16 CSV vs Disguise reference

目标：验证真实 CSV 工作流。

输入：

```text
E:\d3 Projects\0408\output\shots\shot 1\take_16\shot 1_take_16_dense.csv
```

Disguise reference：

```text
E:\d3 Projects\0408\screenshots\screen_live cam 2 transmission_00000.png
```

检查：

- camera transform/FOV composition 是否匹配。
- distortion shape 是否匹配。
- MRQ 是否和 viewport preview 一致。
- 是否仍出现 crop / forward-shift / overscan 残留。

### Gate 5: zoom-changing K sequence

目标：验证变焦期间 per-frame K 生效。

构造一个测试 CSV 或使用真实 zoom take：

```text
frame 0:   focal=24, K1=0.0
frame 50:  focal=35, K1=0.2
frame 100: focal=50, K1=0.5
```

检查：

- Sequencer 曲线里 K 和 focal 同步。
- MRQ 每帧 distortion 连续变化。
- 没有因为 focal grouping 丢掉 K 变化。

### Gate 6: K2/K3 validation

K1 当前有 approved visual result，但 K2/K3 还需要独立验证。

最低验证集：

```text
K2 sweep: K1=0, K3=0, K2 in {-0.5, -0.3, 0, +0.3, +0.5}
K3 sweep: K1=0, K2=0, K3 in {-0.5, -0.3, 0, +0.3, +0.5}
joint:    selected production-like K1/K2/K3 combinations
```

当前请求清单：

```text
docs/d3-distortion-render-request.md
```

命令：

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
scripts/distortion_calibration/.venv/bin/python scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py \
  --validation-root validation_results
```

输出：

```text
/Volumes/Docs/temp/k_sweep/gate6_k2_k3_custom_formula.json
/Volumes/Docs/temp/k_sweep/gate6_k2_k3_custom_formula.md
```

如果 K2/K3 和 K1 使用同一 radial polynomial 语义，material 公式直接成立。否则只调整 formula 部分，不需要改 workflow。

---

## 6. Implementation Tasks

### Task 1: Add isolated distortion mode config

**Files:**

- Modify: `Content/Python/post_render_tool/config.py`
- Modify: `Content/Python/post_render_tool/pipeline.py`
- Test: `Content/Python/post_render_tool/tests/test_custom_distortion_mode.py`

- [ ] Add `DistortionMode` constants.
- [ ] Default to `LEGACY_LENS_FILE`.
- [ ] Make `run_import()` accept optional `distortion_mode`.
- [ ] Assert legacy mode produces the same code path as today.
- [ ] Commit with message `feat: add isolated distortion mode`.

### Task 2: Add custom formula helper

**Files:**

- Create: `Content/Python/post_render_tool/custom_postprocess_math.py`
- Test: `Content/Python/post_render_tool/tests/test_custom_postprocess_math.py`

- [ ] Implement center conversion.
- [ ] Implement UV source coordinate function.
- [ ] Implement out-of-bounds mask helper.
- [ ] Match approved `official_sensor_inverse` convention.
- [ ] Commit with message `feat: add custom postprocess distortion math`.

### Task 3: Add C++ distortion controller component

**Files:**

- Create: `Source/PostRenderTool/Public/PostRenderDistortionControllerComponent.h`
- Create: `Source/PostRenderTool/Private/PostRenderDistortionControllerComponent.cpp`
- Modify: `Source/PostRenderTool/PostRenderTool.Build.cs`

- [ ] Add `UPROPERTY(EditAnywhere, BlueprintReadWrite)` parameters for `K1/K2/K3/CenterU/CenterV/Aspect/DistortionWeight`.
- [ ] Define all 7 Sequencer-facing `UPROPERTY` fields in one C++ pass.
- [ ] Add `BaseMaterial` and transient `MID`.
- [ ] Add function `EnsureBlendableOnCamera()`.
- [ ] Add function `PushParametersToMID()`.
- [ ] Tick only when component is active.
- [ ] Full plugin rebuild in UE 5.7; do not rely on Live Coding after UPROPERTY changes.
- [ ] Restart UE Editor after this task before Python/Blueprint reflection checks.
- [ ] Commit with message `feat: add postprocess distortion controller`.

### Task 4: Create material asset

**Files:**

- Create: `Content/Materials/M_PRT_OfficialSensorInverse.uasset`
- Document: `docs/custom-postprocess-distortion-final-plan.md`

- [ ] Create Post Process material in UE.
- [ ] Add `SceneTexture:PostProcessInput0` sample.
- [ ] Add parameters `K1/K2/K3/CenterUV/Aspect/DistortionWeight`.
- [ ] Implement source UV formula.
- [ ] Save asset under plugin content.
- [ ] Verify material loads from `/PostRenderTool/Materials/M_PRT_OfficialSensorInverse`.
- [ ] Commit with message `feat: add official sensor inverse material`.

### Task 5: Attach controller in custom mode

**Files:**

- Modify: `Content/Python/post_render_tool/camera_builder.py`
- Test: UE remote smoke script under `/tmp/ue_remote_custom_pp_smoke.py`

- [ ] In legacy mode, keep current LensComponent behavior.
- [ ] Add `cleanup_legacy_distortion(camera_actor)` helper.
- [ ] In custom mode, set CineCamera overscan to `0.0`.
- [ ] In custom mode, use the correct UE enum for disabling lens distortion state.
- [ ] In custom mode, deactivate `LensComponent` distortion without nuking `lens_file_picker`.
- [ ] In custom mode, add/reuse `PostRenderDistortionControllerComponent`.
- [ ] Assign material asset to controller.
- [ ] Confirm camera contains one active custom controller and one material blendable.
- [ ] Commit with message `feat: attach custom distortion controller`.

### Task 6: Keyframe controller params

**Files:**

- Modify: `Content/Python/post_render_tool/sequence_builder.py`
- Test: UE remote sequence inspection script

- [ ] Verify component binding API on lanPC before writing final implementation.
- [ ] Bind controller component as possessable only after the lanPC API shape is confirmed.
- [ ] Add float tracks for `K1/K2/K3/CenterU/CenterV/Aspect/DistortionWeight`.
- [ ] Write per-frame keys from `FrameData`.
- [ ] Preserve original frame cadence.
- [ ] Inspect LevelSequence tracks in UE remote script.
- [ ] Commit with message `feat: keyframe custom distortion parameters`.

### Task 7: Add UI toggle as test mode

**Files:**

- Modify: `docs/widget-tree-spec.json`
- Modify: `Source/PostRenderTool/Public/PostRenderToolWidget.h`
- Modify: `Content/Python/post_render_tool/widget.py`
- Modify: `Content/Python/post_render_tool/ui_interface.py`
- Test: `Content/Python/post_render_tool/tests/test_spec_drift.py`

- [ ] Add `Distortion Mode` control with `Legacy LensFile` default and `Custom PostProcess` option.
- [ ] Keep legacy as default.
- [ ] Pass selected mode into `run_import()`.
- [ ] Run spec drift test.
- [ ] Rebuild widget in UE only after full plugin rebuild if UPROPERTY changes.
- [ ] Commit with message `feat: expose custom distortion test mode`.

### Task 8: MRQ validation harness

**Files:**

- Create: `scripts/distortion_calibration/compare_custom_pp_mrq.py`
- Create: `scripts/distortion_calibration/render_custom_pp_test.py`

- [ ] Render K1=+0.5 test frame in MRQ as EXR.
- [ ] Disable TAA/TSR and all AA in the MRQ test job.
- [ ] Use UV gradient plate for the primary pixel-diff run.
- [ ] Copy output back to Mac.
- [ ] Compute bbox, image diff, and heatmap.
- [ ] Compare against approved offline reference.
- [ ] Save JSON report.
- [ ] Commit with message `test: add custom postprocess mrq validation`.

### Task 9: K2/K3 validation data pass

**Files:**

- Modify: `scripts/distortion_calibration/USER_INSTRUCTIONS.md`
- Create: `docs/d3-distortion-render-request.md`
- Create: `scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py`
- Create: `scripts/distortion_calibration/evaluate_center_shift_sweep.py`

- [ ] Add clear Disguise render instructions for K2/K3 sweeps, centerShift sweep, and identity frame.
- [ ] Evaluate K2-only and K3-only frames.
- [ ] Evaluate centerShift-only frames.
- [ ] Decide whether same formula holds.
- [ ] If not, update only `custom_postprocess_math.py` and material formula.
- [ ] Commit with message `test: validate custom formula k2 k3`.

---

## 7. Fallback Strategy

Fallback priority:

1. `Legacy LensFile + M_RAT6` remains available for current project continuity.
2. `Custom Post-Process Material` becomes preferred once gates pass.
3. `Custom STMap Material` is fallback if formula cannot express K2/K3.
4. Standard UE `LensFile STMap` is only fallback if Focus/Zoom keyed STMap is enough for the take.

Do not delete old LensFile code during this phase. It is the known working fallback and a useful comparison baseline.

---

## 8. Expected Precision

Current confidence:

- Offline `official_sensor_inverse` K1=+0.5 result is visually accepted as a single-frame reference.
- Gate 0 all-data check rejects the simple `official_sensor_inverse` polynomial as frozen shader math.
- Standard UE LensFile path did not reproduce that result in MRQ.
- Custom material should match whichever offline formula is finally selected because it executes the same output-to-source UV remap per pixel.

Expected after implementation:

```text
Formula-to-formula residual: near sub-pixel, limited by GPU sampling vs cv2.INTER_LINEAR
MRQ-to-offline residual: target p95 < 1 px after excluding black border and AA edge amplification
Disguise-to-MRQ residual: pending K2/K3/centerShift/MRQ pipeline verification
```

Do not claim final pixel-perfect until Gate 4 and Gate 6 pass.

---

## 9. Material Deployment

Phase 1:

- Create and commit `Content/Materials/M_PRT_OfficialSensorInverse.uasset` manually from UE Editor.
- Document the asset deployment steps in `docs/deployment-guide.md`.
- Verify the asset loads from `/PostRenderTool/Materials/M_PRT_OfficialSensorInverse`.
- Keep the formula graph readable and parameterized; formula swaps must not require controller or Sequencer changes.

Phase 2:

- Consider programmatic generation only after the material graph and MRQ behavior are stable.
- Do not block Phase 1 on programmatic material generation.

---

## 10. Source References

Project docs/code:

- `docs/distortion-investigation.md`
- `docs/d3-distortion-render-request.md`
- `docs/K1-implementation.md`
- `docs/distortion-precision-analysis.md`
- `Content/Python/post_render_tool/pipeline.py`
- `Content/Python/post_render_tool/lens_file_builder.py`
- `Content/Python/post_render_tool/camera_builder.py`
- `Content/Python/post_render_tool/sequence_builder.py`
- `Content/Python/post_render_tool/stmap_writer.py`
- `Content/Python/post_render_tool/csv_parser.py`
- `scripts/distortion_calibration/check_identity_roundtrip.py`
- `scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py`
- `scripts/distortion_calibration/evaluate_center_shift_sweep.py`

UE 5.7 source evidence:

- `Engine/Plugins/VirtualProduction/CameraCalibrationCore/Source/CameraCalibrationCore/Public/LensFile.h`
  - `ELensDataMode` has `Parameters` and `STMap`.
  - `ULensFile.DataMode` defaults to `Parameters`.
  - `STMapTable` is a Focus/Zoom keyed table.
- `Engine/Plugins/VirtualProduction/CameraCalibrationCore/Source/CameraCalibrationCore/Private/LensFile.cpp`
  - `EvaluateDistortionData()` branches into `EvaluateDistortionForParameters()` or `EvaluateDistortionForSTMaps()`.
  - STMap path still blends displacement maps through LensFile machinery.
- `Engine/Plugins/VirtualProduction/LensComponent/Source/LensComponent/Private/LensComponent.cpp`
  - `LensComponent` evaluates LensFile from camera settings and applies MID / SVE.
  - It also manages overscan and camera crop behavior.
- `Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineRenderPasses/Private/MoviePipelineDeferredPasses.cpp`
  - MRQ supports active post-process material stack.

External/session inputs:

- Approved offline image:
  `/Volumes/Docs/temp/LS_shot_1_take_15_dense.0000_K1_p0p5_official_sensor_inverse.png`
- Approved offline JSON:
  `/Volumes/Docs/temp/LS_shot_1_take_15_dense.0000_K1_p0p5_official_sensor_inverse.json`
- Latest CSV on lanPC:
  `E:\d3 Projects\0408\output\shots\shot 1\take_16\shot 1_take_16_dense.csv`
- Disguise reference on lanPC:
  `E:\d3 Projects\0408\screenshots\screen_live cam 2 transmission_00000.png`
- Session MRQ tests showing LensFile DU/UD variants do not match the approved offline distortion shape.

KnowledgeBase status:

- No relevant KnowledgeBase docs found. The repository currently has no `.Codex/knowledge/_INDEX.md` path available in this workspace.
