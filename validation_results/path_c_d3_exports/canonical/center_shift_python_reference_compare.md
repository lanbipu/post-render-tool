# Center Shift Python Reference Compare

- Formula: current `official_sensor_inverse_uv` / HLSL center semantics.
- Base frames: `path_c_center_k1_p0p5_shift_zero` from each pipeline.

| Case | CenterUV | UE vs Python P95 | D3 vs Python P95 | UE Actual Shift | UE Python Shift | D3 Actual Shift | D3 Python Shift |
|---|---:|---:|---:|---:|---:|---:|---:|
| `path_c_center_k1_p0p5_shiftx_n0p5` | `[0.485714, 0.5]` | `0.760784` | `0.784314` | `(-0.55, -0.05)` | `(-0.42, -0.14)` | `(-16.05, -0.06)` | `(-0.27, -0.09)` |
| `path_c_center_k1_p0p5_shiftx_p0p5` | `[0.514286, 0.5]` | `0.760784` | `0.784314` | `(0.57, 0.05)` | `(0.56, 0.01)` | `(16.08, 0.08)` | `(0.39, -0.06)` |
| `path_c_center_k1_p0p5_shifty_n0p5` | `[0.5, 0.474603]` | `0.760784` | `0.784314` | `(0.05, -1.29)` | `(-0.06, -0.34)` | `(-0.02, 21.16)` | `(-0.03, -0.22)` |
| `path_c_center_k1_p0p5_shifty_p0p5` | `[0.5, 0.525397]` | `0.760784` | `0.784314` | `(-0.04, 1.22)` | `(0.21, 0.04)` | `(0.04, -21.26)` | `(0.17, 0.01)` |
