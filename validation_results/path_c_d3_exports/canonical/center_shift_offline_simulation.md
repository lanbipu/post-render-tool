# Path C centerShift Offline Numpy Simulation

- y_normalizer: `sensor_height`
- anchor: `validation_results/path_c_d3_exports/canonical/center_shift/path_c_center_k1_p0p5_shift_zero.png`
- focal_length_mm: `30.302`
- sensor_width_mm: `35.0`
- image: `1920 x 1080`

## Predicted UE Phase Shift vs D3 Measurement

| case | K1 | shift_mm | predicted_x_px | predicted_y_px | response |
|---|---:|---|---:|---:|---:|
| `k_zero_shiftx_n0p5` | 0.0 | (-0.5, +0.0) | -15.832 | -0.001 | 0.975 |
| `k_zero_shiftx_p0p5` | 0.0 | (+0.5, +0.0) | +15.831 | -0.002 | 0.970 |
| `k_zero_shifty_n0p5` | 0.0 | (+0.0, -0.5) | -0.003 | +8.886 | 0.951 |
| `k_zero_shifty_p0p5` | 0.0 | (+0.0, +0.5) | -0.000 | -8.897 | 0.964 |
| `k1_p0p5_shiftx_n0p5` | 0.5 | (-0.5, +0.0) | -16.090 | -0.048 | 0.435 |
| `k1_p0p5_shiftx_p0p5` | 0.5 | (+0.5, +0.0) | +16.223 | -0.082 | 0.433 |
| `k1_p0p5_shifty_n0p5` | 0.5 | (+0.0, -0.5) | -0.027 | +8.735 | 0.415 |
| `k1_p0p5_shifty_p0p5` | 0.5 | (+0.0, +0.5) | +0.157 | -8.942 | 0.462 |

## Decision Rule

- If `k1_p0p5_shifty_n0p5` predicted_y_px ≈ +21 px (and `..._shifty_p0p5` ≈ -21 px):
  21 px residual is K1 distortion coupling. Proceed to Stage 3 UE sweep.
- If `k1_p0p5_shifty_*` predicted_y_px stays near ±9 px (sensor_height)
  or ±16 px (sensor_width): formula has an unmodeled gap.
  Skip Stage 3, proceed directly to Stage 4 D3 K=0 control frames.