# Path C centerShift Projection Validation

## Status

`RAW_MM_FILMBACK_SWEEP_INVALID` — superseded by RenderStream NDC mapping discovery 2026-05-06; canonical reports under `canonical/center_shift_projection_sweep_compare.{md,json}` carry the same renamed status. NDC v2 sweep tracked separately as `center_shift_projection_sweep_v2_compare.md` (Stage 3, pending).

## Evidence

- Dispatch report: `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_dispatch.json`
- Compare JSON: `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.json`
- Compare Markdown: `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.md`
- UE renders: `validation_results/path_c_d3_exports/center_shift_projection_sweep/ue_renders/`

## Result

The UE sign sweep generated and rendered all 20 frames:

- 4 sign pairs: `xp_yp`, `xp_yn`, `xn_yp`, `xn_yn`
- 5 centerShift cases per sign pair
- All imported sequences contained:
  - material tracks: `K1/K2/K3/CenterU/CenterV/Aspect/DistortionWeight`
  - projection tracks: `SensorHorizontalOffset`, `SensorVerticalOffset`

Best sign candidate:

| sign | x_sign | y_sign | primary RMS px | primary p95 abs px | primary max abs px | direction |
|---|---:|---:|---:|---:|---:|---|
| `xp_yn` | `+1.0` | `-1.0` | `25.442984` | `42.568863` | `48.102616` | `FAIL` |

This fails the `<=3px` acceptance gate.

## Interpretation

`Filmback.SensorHorizontalOffset` / `Filmback.SensorVerticalOffset` tracks are a valid UE control path, but the simple model `Sensor*Offset = +/- centerShiftMM` is not the D3 model.

Observed issues:

- X axis over-shifts to about `27px` where D3 is about `16px`.
- Y axis does not have a stable sign/scale match across `+0.5mm` and `-0.5mm`.

Do not enable centerShift projection tracks in production import. The current code keeps them behind `CENTER_SHIFT_ENABLE_PROJECTION_TRACKS=False`.

## Next Data Request

Request D3 centerShift-only frames with `K1=K2=K3=0`. The current centerShift group uses `K1=+0.5`, so projection shift and radial-center coupling remain mixed.
