# Distortion Calibration Tooling

Two parallel approaches to nail Disguise → UE distortion to pixel-perfect.
Backstory in `docs/distortion-investigation.md`; chosen primary path in `MEMORY.md`.

| Path | Strategy | Status |
|---|---|---|
| **A** — System ID | Reverse-engineer Disguise's K-formula by rendering 11 K-sweep frames + global fit | superseded by Path B as primary, kept as fallback |
| **B** — STMap direct | Render an identity-UV probe through Disguise, output IS the distortion STMap | **active** |

## Layout

### Path B (active)
| File | Role |
|---|---|
| `generate_uv_probe.py` | Produces 32-bit float identity-UV EXR + sanity metadata. |
| `uv_probe_1920x1080.exr` | The probe the user puts on the LED surface in d3. R = U, G = V, B = 0. |
| `uv_probe_truth.npz` | 4-corner expected R/G values for sanity check + roundtrip diff. |
| `USER_INSTRUCTIONS_PATH_B.md` | What the user does in d3 to deliver the rendered EXR + verification frame. |

### Path A (fallback, kept frozen)
| File | Role |
|---|---|
| `generate_charuco_board.py` | Produces the 1920×1080 ChArUco PNG + ID-indexed truth corner array (.npz). |
| `charuco_1920x1080.png` | The image the user puts on the LED surface (or maps to the d3 camera) in d3. Reused by Path B as verification probe. |
| `charuco_truth.npz` | Pixel-precise inner-corner positions, indexed by ChArUco ID (OpenCV pixel-center convention). |
| `analyze_renders.py` | Detects corners on each `disguise_K_*.png` via `CharucoDetector` + custom `cornerSubPix` (winSize=11), emits per-corner displacement records to `displacements.csv`. |
| `fit_distortion_models.py` | Fits 5 candidate formulas globally over all (K, r, dr) tuples, with sigma-clipping outlier filter; ranks by RMS and BIC. |
| `USER_INSTRUCTIONS.md` | What the user does in d3 to deliver the 11 transmission frames. |
| `_self_test_*.py` | Synthetic-data validation; rerun before trusting any pipeline change. |
| `.venv/` | Local Python env (cv2 4.13, scipy, numpy, Pillow); separate from project UE Python. |

## Why ChArUco (vs plain chess board)

| | Plain chess | **ChArUco** |
|---|---|---|
| Subpixel precision | 0.05-0.10 px | 0.02-0.05 px (winSize=11) |
| r coverage | r ≤ 0.69 (must leave margin for K=+0.5 pincushion) | **r ≤ 1.03** (full frame) |
| Partial detection | All-or-nothing — outer ring clip → 0 corners | **Per-ID partial** — outer ring clip → still ~70-80% corners |
| Corner ordering | Topology guess (sort-by-y bin) — fragile under tangential distortion | **Stable ID** — corner k same physical point in every frame |

The high-r data points are critical: **candidate distortion models diverge most at r > 0.7**, so any tooling that can't sample there leaves model identification under-constrained.

## Board specs (locked)

- Dictionary: `DICT_5X5_250` (Hamming distance robust to misidentification)
- Squares: 24 cols × 13 rows × 80 px = 1920 × 1040 board
- Marker length: 48 px (60% of square — leaves 16 px margin around chess corners so cornerSubPix(11,11) patches stay clear of marker pattern)
- Centered in 1920×1080 with 20 px vertical white margins
- Inner corners: 23 × 12 = 276 points, IDs 0..275 in row-major order
- r_max ≈ 1.026 (outermost corner just past image half-width)

## Usage

### One-off setup
```bash
cd scripts/distortion_calibration
python3 -m venv .venv
.venv/bin/pip install --quiet numpy scipy opencv-python-headless pillow
.venv/bin/python generate_charuco_board.py
```

### Validate pipeline (rerun after any edit)
```bash
.venv/bin/python _self_test_truth.py
.venv/bin/python _self_test_analyze.py
.venv/bin/python _self_test_fit.py
```

### Process a delivery
```bash
# 11 PNGs from d3 dropped under /tmp/disguise_renders/
.venv/bin/python analyze_renders.py --input-dir /tmp/disguise_renders
.venv/bin/python fit_distortion_models.py    # default trims top 5% by residual
```

`fit_distortion_models.py` ranks by **BIC** (penalizes free parameters) so
overfitting candidates lose to the simpler-and-still-good ones.

## Candidate models

| Model | Forward map (undist r → dist r') | # free params |
|---|---|---|
| M1 | `r * (1 + α·K·r²)`                          UE-current shape | 1 (α) |
| M2 | `r / (1 + α·K·r²)`                          division model | 1 (α) |
| M3 | `r * (1 + a·K·r² + b·K²·r⁴)`               mixed K-order | 2 |
| M4 | `r + α·K·rᵖ`                                free radial exponent | 2 |
| M5 | `r * (1 + a·K·r² + b·K·r⁴ + c·K·r⁶)`       OpenCV K1-only style | 3 |

## Conventions

- **Pixel coordinates**: OpenCV pixel-center origin (pixel (0,0) = top-left **center**).
- **r normalization**: `r = sqrt(dx² + dy²) / (W/2)`, so `r = 1` at the horizontal image edge.
- **K sign**: matches Disguise CSV (`K1=+0.5` means pincushion in Disguise convention).
  Sign-flip into UE LensFile happens later in `lens_file_builder.py`, not here.

## ChArUco detector tuning

`CharucoParameters` set in `analyze_renders.py`:
- `checkMarkers = False` — bypass marker quadrilateral integrity check that rejects markers warped by heavy barrel distortion. DICT_5X5_250 Hamming distance carries the misidentification protection independently.
- `minMarkers = 1` — interpolate chess corner from a single neighboring marker (default 2). Recovers the outermost corners that have only one neighbor surviving the FOV clip.
- `tryRefineMarkers = True` — let the detector polish marker quad fits before chess corner interpolation.
- Custom `cornerSubPix(winSize=(11,11))` after `detectBoard` for tighter saddle-point fit than the detector's internal default.
