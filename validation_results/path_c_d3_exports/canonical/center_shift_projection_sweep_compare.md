# Path C centerShift Projection Sign Sweep

- Status: `RAW_MM_FILMBACK_SWEEP_INVALID`
- Note: This sweep wrote `Filmback.SensorOffset = ±centerShiftMM` (raw mm). RenderStream-UE source (`RenderStreamProjectionPolicy.cpp:122-155`) shows the correct mapping is `cx_ndc = centerShiftMM / focalLengthMM`; this sweep's residuals do not represent formula failure, only wrong input units. Superseded by `center_shift_projection_sweep_v2_compare.md`.
- D3 centerShift root: `validation_results/path_c_d3_exports/canonical/center_shift`
- UE sweep root: `validation_results/path_c_d3_exports/center_shift_projection_sweep/ue_renders`
- Acceptance threshold: `3.000px`

## Selected Sign

- Sign id: `xp_yn`
- X sign: `1.0`
- Y sign: `-1.0`
- Primary RMS: `25.442984px`
- Primary P95 abs: `42.568863px`
- Primary max abs: `48.102616px`
- Direction status: `FAIL`

## Reason

best sign sweep did not meet direction/max-abs threshold; request K=0 centerShift-only D3 frames before production rollout

## Sign Matrix

| `xp_yp` | x `1.0` | y `1.0` | rms `35.243227` | p95 `48.591385` | max `48.596686` | `FAIL` |
| `xp_yn` | x `1.0` | y `-1.0` | rms `25.442984` | p95 `42.568863` | max `48.102616` | `FAIL` |
| `xn_yp` | x `-1.0` | y `1.0` | rms `35.275543` | p95 `48.591348` | max `48.596708` | `FAIL` |
| `xn_yn` | x `-1.0` | y `-1.0` | rms `25.482978` | p95 `42.583683` | max `48.092525` | `FAIL` |

## Case Details

### `xp_yp`
- `path_c_center_k1_p0p5_shiftx_n0p5` axis `x`: D3=(-16.052, -0.055) UE=(-27.130, 0.133) delta=(-11.078, 0.189) primary_delta=`-11.078px`
- `path_c_center_k1_p0p5_shiftx_p0p5` axis `x`: D3=(16.084, 0.078) UE=(27.299, 0.032) delta=(11.215, -0.047) primary_delta=`11.215px`
- `path_c_center_k1_p0p5_shifty_n0p5` axis `y`: D3=(-0.016, 21.160) UE=(0.010, -27.401) delta=(0.026, -48.561) primary_delta=`-48.561px`
- `path_c_center_k1_p0p5_shifty_p0p5` axis `y`: D3=(0.036, -21.261) UE=(-0.005, 27.336) delta=(-0.041, 48.597) primary_delta=`48.597px`

### `xp_yn`
- `path_c_center_k1_p0p5_shiftx_n0p5` axis `x`: D3=(-16.052, -0.055) UE=(-27.136, 0.132) delta=(-11.084, 0.188) primary_delta=`-11.084px`
- `path_c_center_k1_p0p5_shiftx_p0p5` axis `x`: D3=(16.084, 0.078) UE=(27.295, 0.033) delta=(11.211, -0.045) primary_delta=`11.211px`
- `path_c_center_k1_p0p5_shifty_n0p5` axis `y`: D3=(-0.016, 21.160) UE=(-0.026, -26.942) delta=(-0.010, -48.103) primary_delta=`-48.103px`
- `path_c_center_k1_p0p5_shifty_p0p5` axis `y`: D3=(0.036, -21.261) UE=(-0.088, -26.456) delta=(-0.124, -5.195) primary_delta=`-5.195px`

### `xn_yp`
- `path_c_center_k1_p0p5_shiftx_n0p5` axis `x`: D3=(-16.052, -0.055) UE=(-27.419, 0.009) delta=(-11.366, 0.065) primary_delta=`-11.366px`
- `path_c_center_k1_p0p5_shiftx_p0p5` axis `x`: D3=(16.084, 0.078) UE=(27.418, -0.010) delta=(11.334, -0.088) primary_delta=`11.334px`
- `path_c_center_k1_p0p5_shifty_n0p5` axis `y`: D3=(-0.016, 21.160) UE=(0.010, -27.401) delta=(0.026, -48.561) primary_delta=`-48.561px`
- `path_c_center_k1_p0p5_shifty_p0p5` axis `y`: D3=(0.036, -21.261) UE=(-0.005, 27.336) delta=(-0.041, 48.597) primary_delta=`48.597px`

### `xn_yn`
- `path_c_center_k1_p0p5_shiftx_n0p5` axis `x`: D3=(-16.052, -0.055) UE=(-27.419, 0.010) delta=(-11.367, 0.065) primary_delta=`-11.367px`
- `path_c_center_k1_p0p5_shiftx_p0p5` axis `x`: D3=(16.084, 0.078) UE=(27.418, -0.010) delta=(11.333, -0.089) primary_delta=`11.333px`
- `path_c_center_k1_p0p5_shifty_n0p5` axis `y`: D3=(-0.016, 21.160) UE=(-0.029, -26.932) delta=(-0.012, -48.093) primary_delta=`-48.093px`
- `path_c_center_k1_p0p5_shifty_p0p5` axis `y`: D3=(0.036, -21.261) UE=(-0.088, -26.456) delta=(-0.124, -5.195) primary_delta=`-5.195px`
