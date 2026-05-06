# Path C Validation Summary

## Scope

This report tracks Path C UE validation only. It does not use Path A LensFile
fit residuals as shader correctness evidence.

## Matrix

| Gate | Status | Evidence |
|---|---|---|
| Material HLSL readback | PASS | `validation_results/path_c_material_readback/material_custom_nodes.csv`, `validation_results/path_c_material_readback/material_readback.md` |
| Controller binding smoke | PASS | `validation_results/path_c_validation/path_c_smoke.json`, `validation_results/path_c_validation/path_c_smoke_remote_editor.json`, `validation_results/path_c_validation/path_c_smoke_spawn_actor.json` |
| D3 export intake / pairing | PASS | `validation_results/path_c_d3_exports/canonical/pairing_report.md`, `validation_results/path_c_d3_exports/canonical/local_intake_validation.json` |
| D3 controlled CSV import smoke | PASS | `validation_results/path_c_d3_exports/canonical/ue_batch_import.json`, `validation_results/path_c_d3_exports/canonical/ue_import_smoke_attempt.md` |
| D3 controlled MRQ render output | PASS | `validation_results/path_c_d3_exports/canonical/d3_mrq_render.json`, `validation_results/path_c_d3_exports/ue_renders/`, `validation_results/path_c_d3_exports/canonical/d3_mrq_render_attempt.md` |
| D3 controlled render compare | FAIL_MODEL_SEMANTICS | `validation_results/path_c_d3_exports/canonical/d3_render_validation_summary.md`, `validation_results/path_c_d3_exports/canonical/d3_vs_ue_relative_compare.json`, `validation_results/path_c_d3_exports/canonical/center_shift_python_reference_compare.json` |
| centerShift projection sign sweep (raw-mm v1) | HISTORICAL_ARCHIVE | `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_dispatch.json`, `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.json`, `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.md` (X 27px 当时被误判为 over-shift, K=0 直接测量后确认就是真值, 详见 `docs/distortion-investigation.md`) |
| centerShift projection sign sweep (NDC v2) | SUPERSEDED | NDC `cx_ndc = mm/focal` 公式被 K=0 直接测量打脸（预测 ±9/16 px, 实测 ±27.5 px）, sweep 未跑直接跳到 Stage 4 |
| centerShift K=0 direct measurement | PASS | `validation_results/path_c_d3_exports/canonical/center_shift_k_zero/` (5 帧 K1=K2=K3=0 PNG+CSV); 公式 `pixel = cs × image_dim / sensor_dim_mm` 残差 < 0.6%; 详见 `docs/distortion-investigation.md` "2026-05-07 — K=0 直接测量" |
| centerShift K=0 UE closed-loop | PASS | `validation_results/path_c_d3_exports/ue_renders_k_zero/` (5 帧 UE MRQ); UE pipeline + MRQ 渲染 vs D3 原始 PNG, 4 个 shifted case D3-relative vs UE-relative max |Δshift| = 0.160 px (X +0.16, Y +0.10); cross-render UE vs D3 同 case ≈ (0, 0). 公式两轴双反号 (`Sensor*Offset = -cs`); 详见 `docs/distortion-investigation.md` "2026-05-07 UE 闭环验证" |
| D3 production-match spatialmap CSV | DEFERRED | `validation_results/path_c_d3_exports/canonical/discovery_report.json`, `validation_results/path_c_d3_exports/canonical/intake_validation.md` |
| `DistortionWeight=0` identity render | PASS | `validation_results/path_c_validation/path_c_mrq_render.json`, `validation_results/path_c_validation/renders/path_c_identity.png`, `validation_results/path_c_validation/identity_compare.json`, `validation_results/path_c_validation/identity_source_compare.json` |
| `K1=+0.5` UE vs Python | PASS | `validation_results/path_c_validation/renders/path_c_k1.png`, `validation_results/path_c_validation/k1_compare.json`, `validation_results/path_c_validation/k1_compare.md` |
| `K2=+0.5` UE vs Python | PASS | `validation_results/path_c_validation/renders/path_c_k2.png`, `validation_results/path_c_validation/k2_compare.json`, `validation_results/path_c_validation/k2_compare.md` |
| `K3=+0.5` UE vs Python | PASS | `validation_results/path_c_validation/renders/path_c_k3.png`, `validation_results/path_c_validation/k3_compare.json`, `validation_results/path_c_validation/k3_compare.md` |
| d3 next-data request status | PASS | `docs/d3-distortion-render-request.md` |
| Path A half-width status | DEFERRED | `validation_results/path_a_half_width/path_a_half_width_diagnostic.md` |

## Notes

- `Material HLSL readback` is direct UE asset readback via `DumpMaterialExpressionInfo`.
- `Controller binding smoke` passed both in `-nullrhi` transient mode and in the
  already-open UE Editor remote execution path. The actor-spawn smoke confirms
  the component can be added to a `CineCameraActor` and parameter values round-trip.
- `D3 export intake / pairing` confirms the 13 controlled CSV/image pairs were
  sorted into the requested order, parse successfully, and match the requested
  `focalLengthMM`, `K1/K2/K3`, `centerShiftMM`, pose, and resolution values.
- `D3 controlled CSV import smoke` confirms all 13 canonical CSVs import into
  isolated `/Game/PathCD3Validation` assets, and each generated `LevelSequence`
  contains `K1`, `K2`, `K3`, `CenterU`, `CenterV`, `Aspect`, and
  `DistortionWeight` tracks.
- `D3 controlled MRQ render output` now renders all 13 controlled frames from a
  duplicated `/Game/Main` test map.
- `D3 controlled render compare` fails on old `centerShiftMM` semantics. D3 shows
  approximately `16px` X shifts and `21px` Y shifts for `±0.5mm`, while current
  UE/Python/HLSL center semantics produce only about `0.5px` X and `1.2px` Y.
  This is not a CSV pairing or material-binding failure; it points to the
  `centerShiftMM -> CenterUV only` model, now classified as `FAIL_MODEL_SEMANTICS`.
- `centerShift projection sign sweep` 已归档：sweep 当年报 `xp_yn` 26px residual
  并判 BLOCKED_FORMULA, 现在回头看 27px 那个数字本身就是 D3 真值 (K=0 直接测量
  确认 ±27.5px @ cs=±0.5mm), sweep 当年错的是 phase-correlate 用了 K1=0.5
  污染帧做 reference. 现在生产已切到 `Sensor*Offset = -cs.x / -cs.y` (双轴反号,
  UE Filmback 跟 D3 在两个轴上方向定义都相反), projection tracks 总是开启,
  公式无开关. 2026-05-07 UE pipeline 闭环渲染 5 case max |Δshift| = 0.16 px.
- `D3 production-match spatialmap CSV` is deferred because the current parser
  accepts `camera:*` columns, while the exported production-match CSV uses a
  `spatialmap:*` prefix.
- Headless non-null `UnrealEditor-Cmd.exe` remains blocked by swapchain creation,
  but this is superseded for render validation by the open UE Editor MRQ path.
- `identity_source_compare` intentionally records the render pipeline color floor:
  UE texture import / PNG output / tonemapping do not match the source EXR byte-for-byte.
  Shader geometry comparisons therefore use the UE identity render as `reference_base`.
- `identity_compare` uses UE identity as its own Python reference base and is exactly zero:
  `valid_p95=0`, `rms=0`, `valid_mask_mismatch_ratio=0`.
- K-axis comparisons use `official_sensor_inverse_uv` against the UE identity
  render as the base image. Metrics are normalized channel absolute differences
  in `[0,1]`, not pixel displacement in px. Valid-region `p95` is at approximately
  the 8-bit PNG quantization floor:
  `K1=0.003921568`, `K2=0.003837347`, `K3=0.003404558`.
- Sparse edge pixels still produce higher `valid_max` values, so any future
  border-rule tightening should inspect edge sampling separately from interior
  shader geometry.
