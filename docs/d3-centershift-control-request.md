# D3 centerShift K=0 Control Render Request

## Purpose

Stage 2 offline simulation (`scripts/distortion_calibration/ue_path_c_validation/center_shift_offline_simulation.py`)
ran the predicted UE Path C displacement field for 8 cases (K1 ∈ {0, 0.5} × centerShiftMM ∈
{(±0.5, 0), (0, ±0.5)}) and phase-correlated against the existing D3 zero-anchor.
Result: both candidate Y normalizers (`sensor_height` → ±8.9 px; `sensor_width` → ±15.8 px)
are K-independent — K1 distortion coupling on Y contributes < 0.2 px. **D3 measured
±21.21 px on Y at K1=0.5**, which cannot be reproduced by any Path C formula combination
we have. There is a real Y-axis gap.

The K=0 control frames isolate the projection-translation component of `centerShiftMM`
from any distortion-coupled effect. With K1=K2=K3=0 the post-process radial term is
identically zero, so the only remaining mechanism is the projection principal-point
shift. This lets us read the raw `centerShiftMM → pixel` mapping directly off the D3
output and disambiguate among three candidates:

- `pixel_shift = (mm/focal) × image_dim/2` with `dim = sensor_height` → ±8.9 px expected
- `pixel_shift = (mm/focal) × image_dim/2` with `dim = sensor_width` → ±15.8 px expected
- some other formula entirely → whatever D3 produces

If D3's K=0 Y comes in at ±9 px the anisotropic `sensor_height` normalizer is right.
If Y comes in at ±16 px the isotropic `sensor_width` normalizer is right. If Y comes
in at ±21 px, D3 has a Y-only scaling factor we have not yet identified, and the next
step is custom UE projection matrix (mirroring `RenderStream-UE/
RenderStreamProjectionPolicy.cpp:122-155` directly). X axis is expected at ±16 px
across all candidates and only confirms NDC normalization with `sensor_width/2` half-
width on the X axis — it does not by itself disambiguate the Y normalizer.

## Global Settings

Use the same `MR Set` / `RenderStream-to-MR-Set` workflow as the existing
`docs/d3-path-c-csv-export-request.md` Group B. All globals identical to that document
unless explicitly overridden below.

| Field | Value |
|---|---:|
| `camera:cam_1.resolution.x` | `1920` |
| `camera:cam_1.resolution.y` | `1080` |
| `camera:cam_1.overscan.x` | `1.3` |
| `camera:cam_1.overscan.y` | `1.3` |
| `camera:cam_1.overscanResolution.x` | `2496` |
| `camera:cam_1.overscanResolution.y` | `1404` |
| `camera:cam_1.paWidthMM` | `35.0` |
| `camera:cam_1.aspectRatio` | `1.77779` |
| `camera:cam_1.aperture` | `18` |
| `camera:cam_1.focusDistance` | `12` |
| `camera:cam_1.focalLengthMM` | `30.302` |

Camera pose (same as Group B):

| Field | Value |
|---|---:|
| `camera:cam_1.offset.x` | `0` |
| `camera:cam_1.offset.y` | `2.25` |
| `camera:cam_1.offset.z` | `-11.6` |
| `camera:cam_1.rotation.x` | `0` |
| `camera:cam_1.rotation.y` | `0` |
| `camera:cam_1.rotation.z` | `-0` |

Color / format requirements (from Group B):
- transmission frame export
- PNG acceptable (matches Group B existing files)
- no crop, no resize, no extra processing
- linear pass-through, no tone mapping / LUT / gamma transform / color management

## Required Cases

For all 5 frames:

| Field | Value |
|---|---:|
| `camera:cam_1.k1k2k3.x` | `0.0` |
| `camera:cam_1.k1k2k3.y` | `0.0` |
| `camera:cam_1.k1k2k3.z` | `0.0` |
| `camera:cam_1.focalLengthMM` | `30.302` (固定，跟 Group B 同) |

**Note: `path_c_center_k_zero_shift_zero` is the K=0 anchor frame.** It must be
rendered fresh with K1=K2=K3=0; the existing `path_c_center_k1_p0p5_shift_zero`
cannot substitute, because the K1=0.5 anchor still has distortion at non-zero radii
that contaminates phase correlation against K=0 case frames.

Vary only `centerShiftMM`:

| Case ID | `centerShiftMM.x` | `centerShiftMM.y` |
|---|---:|---:|
| `path_c_center_k_zero_shift_zero` | `0.0` | `0.0` |
| `path_c_center_k_zero_shiftx_n0p5` | `-0.5` | `0.0` |
| `path_c_center_k_zero_shiftx_p0p5` | `0.5` | `0.0` |
| `path_c_center_k_zero_shifty_n0p5` | `0.0` | `-0.5` |
| `path_c_center_k_zero_shifty_p0p5` | `0.0` | `0.5` |

## Naming and Return Layout

Same conventions as `docs/d3-path-c-csv-export-request.md` (lowercase ASCII, `_`
separator, `p` for positive, `n` for negative, `p` for decimal point, `zero` for
exact 0.0). Each case is a separate D3 recording; default Shot Recorder filenames are
fine — Codex post-processing will rename to canonical.

Canonical layout after Codex post-processing:

```text
validation_results/path_c_d3_exports/canonical/center_shift_k_zero/
├── path_c_center_k_zero_shift_zero.csv
├── path_c_center_k_zero_shift_zero.png
├── path_c_center_k_zero_shiftx_n0p5.csv
├── path_c_center_k_zero_shiftx_n0p5.png
├── path_c_center_k_zero_shiftx_p0p5.csv
├── path_c_center_k_zero_shiftx_p0p5.png
├── path_c_center_k_zero_shifty_n0p5.csv
├── path_c_center_k_zero_shifty_n0p5.png
├── path_c_center_k_zero_shifty_p0p5.csv
└── path_c_center_k_zero_shifty_p0p5.png
```

## Sanity Check (After D3 Renders)

Quick phase-correlate sanity test on a single axis to confirm the data is usable
before sending all 5 frames:

```python
import cv2
anchor = cv2.imread("path_c_center_k_zero_shift_zero.png", cv2.IMREAD_GRAYSCALE).astype("float32") / 255.0
shifted = cv2.imread("path_c_center_k_zero_shiftx_p0p5.png", cv2.IMREAD_GRAYSCALE).astype("float32") / 255.0
(sx, sy), resp = cv2.phaseCorrelate(anchor, shifted)
print(f"X={sx:+.2f} Y={sy:+.2f} response={resp:.3f}")
```

Expected outcomes for the `shiftx_p0p5` snippet (X axis only — Y normalizer choice
needs the `shifty_*` frames; both NDC candidates predict the SAME X value):

- `X ≈ +16, Y ≈ 0, response > 0.9` → X axis NDC mapping confirmed. Run the same
  snippet with `path_c_center_k_zero_shifty_p0p5` to disambiguate the Y normalizer:
  - Y ≈ −9 px → `sensor_height` (anisotropic) candidate is right
  - Y ≈ −16 px → `sensor_width` (isotropic) candidate is right
  - Y ≈ −21 px → neither candidate is right, escalate to custom projection matrix
- `X ≈ +9, Y ≈ 0, response > 0.9` → X axis is using `sensor_height/2` (~540 px half-
  height) instead of `sensor_width/2` (~960 px); also valid result, also need
  `shifty` frames to confirm full mapping
- `response < 0.5` → render anomaly (LUT / gamma / tone mapping leaked through),
  debug before continuing

## Completion Checks

- D3 project folder cleaned of prior takes before recording.
- All 5 cases recorded individually.
- Each recording has CSV (Dense) export.
- Each recording has matched Disguise Frame (matched Disguise Frame).
- Camera parameters held constant within each recording.
- No crop, no resize, no tone mapping / LUT / gamma transform / color management.
- Final delivery: complete D3 project folder (Codex post-processing handles canonical
  rename and pairing).

## After Frames Arrive

Mac-side analysis flow:

1. Codex pairs / renames D3 default files to canonical layout above.
2. Run `center_shift_k_zero_analysis.py` (Stage 4 Task 4.3 in the plan, not yet
   created) to phase-correlate each case vs anchor and table the predictions of all
   three candidate formulas alongside the measurements.
3. Append findings to `docs/distortion-investigation.md` and decide:
   - One candidate matches X and Y → update `distortion_math.py` to the chosen
     normalizer, run Stage 3 UE sweep with 4-sign × 1-normalizer (single config), pass
     gate, ship.
   - X matches but Y doesn't match any candidate → upgrade to custom
     `CineCameraComponent::CustomProjectionMatrix` (Stage 4b in the plan) instead of
     the Filmback path.
