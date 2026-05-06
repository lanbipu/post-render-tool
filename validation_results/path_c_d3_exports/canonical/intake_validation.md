# Path C D3 Export Intake Validation

## Status

- Overall status: `PASS`
- Controlled CSV/image pairs: `13 / 13`
- Production match CSV/image pairs: `1 / 1`
- Canonical order source: `docs/d3-path-c-csv-export-request.md`

## Source Data

- Raw zip: `validation_results/path_c_d3_exports/raw/path_c_d3_exports_0408.zip`
- Raw shots: `validation_results/path_c_d3_exports/raw/output/shots/shot 1`
- Raw screenshots: `validation_results/path_c_d3_exports/raw/screenshots`
- Pairing report: `validation_results/path_c_d3_exports/canonical/pairing_report.md`
- Machine-readable validation: `validation_results/path_c_d3_exports/canonical/local_intake_validation.json`

## Validation Checks

All controlled cases passed the local intake checks:

- `parse_csv_dense()` accepts every controlled CSV.
- Each controlled CSV has `2` stable rows.
- Each controlled image is `1920x1080`.
- `focalLengthMM`, `k1k2k3`, and `centerShiftMM` match the requested case table.
- Fixed global values match the updated request: `paWidthMM=35`, `aspectRatio=1.77779`, `aperture=18`, `focusDistance=12`.
- Fixed pose matches the updated request: `offset=(0, 2.25, -11.6)`, `rotation=(0, 0, 0)`.

## Controlled Case Order

| Order | Case ID | Group |
|---:|---|---|
| 1 | `path_c_focal24_k_zero` | `focal_k_axis` |
| 2 | `path_c_focal24_k1_p0p5` | `focal_k_axis` |
| 3 | `path_c_focal30p302_k_zero` | `focal_k_axis` |
| 4 | `path_c_focal30p302_k1_p0p5` | `focal_k_axis` |
| 5 | `path_c_focal50_k_zero` | `focal_k_axis` |
| 6 | `path_c_focal50_k1_p0p5` | `focal_k_axis` |
| 7 | `path_c_focal30p302_k2_p0p5` | `focal_k_axis` |
| 8 | `path_c_focal30p302_k3_p0p5` | `focal_k_axis` |
| 9 | `path_c_center_k1_p0p5_shift_zero` | `center_shift` |
| 10 | `path_c_center_k1_p0p5_shiftx_n0p5` | `center_shift` |
| 11 | `path_c_center_k1_p0p5_shiftx_p0p5` | `center_shift` |
| 12 | `path_c_center_k1_p0p5_shifty_n0p5` | `center_shift` |
| 13 | `path_c_center_k1_p0p5_shifty_p0p5` | `center_shift` |

## Production Match

- Canonical CSV: `validation_results/path_c_d3_exports/canonical/production_match/path_c_production_match_frame_48932_spatialmap.csv`
- Canonical image: `validation_results/path_c_d3_exports/canonical/production_match/path_c_production_match_frame_48932_spatialmap.png`
- Status: `DEFERRED_SPATIALMAP_CSV_NOT_POSTRENDERTOOL_CAMERA_CSV`
- Reason: this CSV uses a `spatialmap:*` prefix instead of the current `camera:*` prefix expected by `parse_csv_dense()`.

