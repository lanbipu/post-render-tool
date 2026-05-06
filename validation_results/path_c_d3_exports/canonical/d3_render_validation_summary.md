# Path C D3 Render Validation Summary

## Status

- D3 export intake: `PASS`
- UE import smoke: `PASS`
- UE MRQ render output: `PASS`
- D3 vs UE direct image compare: `NEEDS_REVIEW`
- CenterShift semantic match: `FAIL`

## Evidence

- Pairing report: `validation_results/path_c_d3_exports/canonical/pairing_report.md`
- Local intake: `validation_results/path_c_d3_exports/canonical/local_intake_validation.json`
- UE import smoke: `validation_results/path_c_d3_exports/canonical/ue_batch_import.json`
- UE MRQ dispatch: `validation_results/path_c_d3_exports/canonical/d3_mrq_render.json`
- UE render outputs: `validation_results/path_c_d3_exports/ue_renders/`
- Direct compare: `validation_results/path_c_d3_exports/canonical/d3_vs_ue_render_compare.json`
- Relative compare: `validation_results/path_c_d3_exports/canonical/d3_vs_ue_relative_compare.json`
- CenterShift Python reference compare: `validation_results/path_c_d3_exports/canonical/center_shift_python_reference_compare.json`

## Render Output

All `13` controlled cases rendered from the duplicated `/Game/Main` test map:

```text
/Game/PathCD3RenderValidation/PathCD3Render_Main
```

The script did not edit production `/Game/Main` directly.

## Direct Compare

Direct RGB compare measured all `13` D3/UE image pairs.

Important context:

- The zero-K anchors already show a render-pipeline/color floor:
  - `path_c_focal24_k_zero`: RGB `p95=0.145098`
  - `path_c_focal30p302_k_zero`: RGB `p95=0.121569`
  - `path_c_focal50_k_zero`: RGB `p95=0.098039`
- Therefore direct RGB difference is not sufficient as shader correctness
  evidence.

## Relative Compare

Relative compare subtracts each pipeline's anchor frame first.

K-axis global phase probes are approximately aligned:

| Case | Shift delta px |
|---|---:|
| `path_c_focal24_k1_p0p5` | `(0.05, -0.17)` |
| `path_c_focal30p302_k1_p0p5` | `(-0.01, 0.03)` |
| `path_c_focal50_k1_p0p5` | `(0.02, 0.00)` |
| `path_c_focal30p302_k2_p0p5` | `(-0.03, 0.03)` |
| `path_c_focal30p302_k3_p0p5` | `(0.00, 0.03)` |

This does not prove radial geometry is pixel-perfect, but it does not show a
large global misregistration in the K-axis cases.

## CenterShift Mismatch

CenterShift is not matching D3 behavior.

Pipeline-internal phase shifts relative to `path_c_center_k1_p0p5_shift_zero`:

| Case | D3 shift px | UE shift px | Delta px |
|---|---:|---:|---:|
| `path_c_center_k1_p0p5_shiftx_n0p5` | `(-16.05, -0.06)` | `(-0.55, -0.05)` | `(15.50, 0.00)` |
| `path_c_center_k1_p0p5_shiftx_p0p5` | `(16.08, 0.08)` | `(0.57, 0.05)` | `(-15.51, -0.03)` |
| `path_c_center_k1_p0p5_shifty_n0p5` | `(-0.02, 21.16)` | `(0.05, -1.29)` | `(0.06, -22.45)` |
| `path_c_center_k1_p0p5_shifty_p0p5` | `(0.04, -21.26)` | `(-0.04, 1.22)` | `(-0.07, 22.48)` |

The current Python/HLSL formula predicts UE's small center-shift response, not
D3's large response. That means the implemented `CenterU/CenterV` semantics are
not the same as D3 Designer's `centerShiftMM` semantics for this workflow.

## Current Conclusion

Path C can ingest the new D3 CSVs and render UE frames, but the D3-controlled
render validation does **not** pass yet because `centerShiftMM` behavior differs
substantially from D3.

Do not treat this as a general material-binding failure:

- `K1/K2/K3` tracks are present and visibly affect renders.
- `CenterU/CenterV` tracks are present.
- UE output follows the current Python/HLSL center formula closely in phase.

The next fix should focus on the semantic mapping from D3 `centerShiftMM` to the
post-process material, not on CSV pairing or UE import plumbing.

