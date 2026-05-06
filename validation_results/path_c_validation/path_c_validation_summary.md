# Path C Validation Summary

## Scope

This report tracks Path C UE validation only. It does not use Path A LensFile
fit residuals as shader correctness evidence.

## Matrix

| Gate | Status | Evidence |
|---|---|---|
| Material HLSL readback | PASS | `validation_results/path_c_material_readback/material_custom_nodes.csv`, `validation_results/path_c_material_readback/material_readback.md` |
| Controller binding smoke | PASS | `validation_results/path_c_validation/path_c_smoke.json`, `validation_results/path_c_validation/path_c_smoke_remote_editor.json`, `validation_results/path_c_validation/path_c_smoke_spawn_actor.json` |
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
