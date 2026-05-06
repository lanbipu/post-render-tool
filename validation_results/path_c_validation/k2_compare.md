# Path C Render Compare - k2

- Status: `PASS`
- Input probe: `scripts/distortion_calibration/uv_probe_3840x2160.exr`
- Reference base: `validation_results/path_c_validation/renders/path_c_identity.png`
- UE render: `validation_results/path_c_validation/renders/path_c_k2.png`
- Reference mode: `official_sensor_inverse_uv vectorized formula from UE identity render`
- Metric unit: `normalized channel absolute difference [0,1]`

## Metrics

- RMS: `0.00693057`
- Median: `0.00002301`
- P95: `0.00381809`
- Max: `0.50000000`
- Changed values: `121377`
- Changed value ratio: `0.00487787`
- Valid-mask mismatch ratio: `0.00060233`
- Valid RMS: `0.00530247`
- Valid median: `0.00011486`
- Valid P95: `0.00383735`
- Valid max: `0.50000000`
- Valid changed values: `109676`
- Valid changed value ratio: `0.00461967`
