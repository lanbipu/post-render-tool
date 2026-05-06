# Path C Render Compare - k1

- Status: `PASS`
- Input probe: `scripts/distortion_calibration/uv_probe_3840x2160.exr`
- Reference base: `validation_results/path_c_validation/renders/path_c_identity.png`
- UE render: `validation_results/path_c_validation/renders/path_c_k1.png`
- Reference mode: `official_sensor_inverse_uv vectorized formula from UE identity render`
- Metric unit: `normalized channel absolute difference [0,1]`

## Metrics

- RMS: `0.00619049`
- Median: `0.00000006`
- P95: `0.00392151`
- Max: `0.73437500`
- Changed values: `132806`
- Changed value ratio: `0.00533718`
- Valid-mask mismatch ratio: `0.00049756`
- Valid RMS: `0.00503554`
- Valid median: `0.00036764`
- Valid P95: `0.00392157`
- Valid max: `0.73437500`
- Valid changed values: `123123`
- Valid changed value ratio: `0.00587177`
