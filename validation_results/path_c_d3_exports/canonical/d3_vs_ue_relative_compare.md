# Path C D3 vs UE Relative Compare

- Status: `MEASURED`
- Metric unit: normalized RGB delta absolute difference `[0,1]`
- Interpretation: subtracts each pipeline anchor before comparing D3 and UE deltas.

| Case | Anchor | Delta P95 | Delta Mean | Changed >1 LSB | D3 Shift px | UE Shift px | Shift Delta px |
|---|---|---:|---:|---:|---:|---:|---:|
| `path_c_focal24_k1_p0p5` | `path_c_focal24_k_zero` | `0.752941` | `0.132426` | `0.721641` | `(0.10, -0.29)` | `(0.15, -0.46)` | `(0.05, -0.17)` |
| `path_c_focal30p302_k1_p0p5` | `path_c_focal30p302_k_zero` | `0.764706` | `0.131267` | `0.625463` | `(0.07, -0.05)` | `(0.07, -0.01)` | `(-0.01, 0.03)` |
| `path_c_focal50_k1_p0p5` | `path_c_focal50_k_zero` | `0.772549` | `0.140170` | `0.672022` | `(-0.03, -0.06)` | `(-0.01, -0.06)` | `(0.02, 0.00)` |
| `path_c_focal30p302_k2_p0p5` | `path_c_focal30p302_k_zero` | `0.239216` | `0.053150` | `0.504876` | `(0.08, -0.15)` | `(0.05, -0.12)` | `(-0.03, 0.03)` |
| `path_c_focal30p302_k3_p0p5` | `path_c_focal30p302_k_zero` | `0.125490` | `0.029599` | `0.436352` | `(0.01, -0.06)` | `(0.01, -0.03)` | `(0.00, 0.03)` |
| `path_c_center_k1_p0p5_shiftx_n0p5` | `path_c_center_k1_p0p5_shift_zero` | `0.125490` | `0.030607` | `0.537310` | `(-16.05, -0.06)` | `(-0.55, -0.05)` | `(15.50, 0.00)` |
| `path_c_center_k1_p0p5_shiftx_p0p5` | `path_c_center_k1_p0p5_shift_zero` | `0.137255` | `0.032641` | `0.546899` | `(16.08, 0.08)` | `(0.57, 0.05)` | `(-15.51, -0.03)` |
| `path_c_center_k1_p0p5_shifty_n0p5` | `path_c_center_k1_p0p5_shift_zero` | `0.184314` | `0.050699` | `0.776817` | `(-0.02, 21.16)` | `(0.05, -1.29)` | `(0.06, -22.45)` |
| `path_c_center_k1_p0p5_shifty_p0p5` | `path_c_center_k1_p0p5_shift_zero` | `0.184314` | `0.052830` | `0.768142` | `(0.04, -21.26)` | `(-0.04, 1.22)` | `(-0.07, 22.48)` |
