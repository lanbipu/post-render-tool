# centerShift K=0 Analysis

- Status: `PASS`
- Input root: `validation_results/path_c_d3_exports/canonical/center_shift_k_zero`
- Method: `cv2.phaseCorrelate(anchor, shifted) on grayscale PNG; primary axis compared against CSV-derived formula`
- Resolution: `1920x1080`
- Sensor: `35.000000mm x 19.687365mm`
- Focal length: `30.302000mm`
- Formula under test: `pixel_shift_x = centerShiftMM.x * image_width / paWidthMM; pixel_shift_y = centerShiftMM.y * image_height / paHeightMM * -1`

## Summary

- Max abs primary residual: `0.170536px`
- RMS primary residual: `0.136488px`
- Max residual percent: `0.621744%`
- Old NDC/focal formula residual range: `74.21%` to `209.17%`

## Cases

| case | cs_mm | measured_primary_px | predicted_primary_px | residual_px | residual_% | response | old_ndc_pred_px | old_ndc_residual_% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `path_c_center_k_zero_shiftx_n0p5` | (-0.500, +0.000) | `-27.595516` | `-27.428571` | `-0.166944` | `0.608651` | `0.927458` | `-15.840539` | `74.21` |
| `path_c_center_k_zero_shiftx_p0p5` | (+0.500, +0.000) | `+27.599107` | `+27.428571` | `+0.170536` | `0.621744` | `0.919901` | `+15.840539` | `74.23` |
| `path_c_center_k_zero_shifty_n0p5` | (+0.000, -0.500) | `+27.486652` | `+27.428760` | `+0.057892` | `0.211064` | `0.834681` | `+8.910303` | `208.48` |
| `path_c_center_k_zero_shifty_p0p5` | (+0.000, +0.500) | `-27.547975` | `-27.428760` | `-0.119215` | `0.434634` | `0.847382` | `-8.910303` | `209.17` |

## Conclusion

- The sensor-dimension formula matches all four non-zero K=0 centerShift frames within `<0.7%` primary-axis residual.
- The focal-length/NDC formula is rejected for this D3 export set; its primary-axis residual is `74%` to `209%` depending on axis/sign.
