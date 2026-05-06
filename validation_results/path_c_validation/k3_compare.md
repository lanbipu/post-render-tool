# Path C Render Compare - k3

- Status: `PASS`
- Input probe: `scripts/distortion_calibration/uv_probe_3840x2160.exr`
- Reference base: `validation_results/path_c_validation/renders/path_c_identity.png`
- UE render: `validation_results/path_c_validation/renders/path_c_k3.png`
- Reference mode: `official_sensor_inverse_uv vectorized formula from UE identity render`
- Metric unit: `normalized channel absolute difference [0,1]`

## Metrics

- RMS: `0.00724090`
- Median: `0.00000000`
- P95: `0.00338542`
- Max: `0.50134802`
- Changed values: `83563`
- Changed value ratio: `0.00335821`
- Valid-mask mismatch ratio: `0.00057690`
- Valid RMS: `0.00568067`
- Valid median: `0.00000000`
- Valid P95: `0.00340456`
- Valid max: `0.50134802`
- Valid changed values: `72478`
- Valid changed value ratio: `0.00295198`
