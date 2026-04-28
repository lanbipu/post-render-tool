# Distortion Calibration Tooling

Two parallel approaches to nail Disguise → UE distortion to pixel-perfect.
Backstory in `docs/distortion-investigation.md`; chosen primary path in `MEMORY.md`.

| Path | Strategy | Status |
|---|---|---|
| **A** — System ID | Reverse-engineer Disguise's K-formula by rendering 11 K-sweep UV-probe EXRs + global fit (M1-M5) | active |
| **B** — STMap direct | Render an identity-UV probe through Disguise, output IS the distortion STMap | active |

Both paths share `generate_uv_probe.py` + `uv_probe_1920x1080.exr` as the d3-side input. They diverge in how the rendered EXRs are analyzed.

## Layout

### Shared (both paths)
| File | Role |
|---|---|
| `generate_uv_probe.py` | Produces 32-bit float identity-UV EXR + sanity metadata. |
| `uv_probe_1920x1080.exr` | The probe the user puts on the LED surface in d3. R = U, G = V, B = 0. |
| `uv_probe_truth.npz` | Image dimensions + 4-corner expected R/G values for sanity check. |

### Path A · System identification (UV gradient + curve fitting)
| File | Role |
|---|---|
| `analyze_renders.py` | Reads each `disguise_K_*.exr`, samples ~30k random valid pixels per frame, emits per-pixel `(K, r_anchor, dr)` records to `displacements.csv`. |
| `fit_distortion_models.py` | Fits 5 candidate formulas globally over all `(K, r, dr)` tuples, with sigma-clipping outlier filter; ranks by RMS and BIC. |
| `USER_INSTRUCTIONS.md` | What the user does in d3 to deliver the 11 K-sweep transmission EXRs. |
| `_self_test_truth.py` | Verifies `uv_probe_1920x1080.exr` matches its identity-grid truth. |
| `_self_test_analyze.py` | Synthesizes K=±0.3 distortion via `cv2.remap`, runs `analyze_renders` end-to-end, checks recovered dr matches `K·r³`. |
| `_self_test_fit.py` | Fits M1-M5 on synthetic α=1.5 polynomial + 0.5 px noise, expects M1 to win on BIC. |

### Path B · STMap direct solve
| File | Role |
|---|---|
| `build_stmap.py` | Reads disguise-rendered EXR, builds bidirectional STMap via scipy griddata cubic. |
| `_self_test_stmap.py` | Synthetic-data validation for `build_stmap`. |
| `USER_INSTRUCTIONS_PATH_B.md` | What the user does in d3 to deliver the rendered EXR + verification frame. |

### Environment
| File | Role |
|---|---|
| `.venv/` | Local Python env (cv2 4.13 + scipy + numpy + Pillow); separate from project UE Python. |

## Why UV gradient (vs ChArUco / chess board)

Earlier iterations of Path A used a ChArUco board with corner detection. Rationale for switching to UV gradient:

| | ChArUco corners | **UV gradient** |
|---|---|---|
| Per-frame samples | 276 corners | **2,073,600 pixels** (random subsample to 30k for fit tractability) |
| 11-frame total data | ~3,000 | **~330,000** (100× denser) |
| Per-point precision | 0.02-0.05 px (cornerSubPix saddle-point fit) | **0.001 px** (direct R/G channel read, EXR float quantization) |
| r coverage | r ≤ 0.95 (partial detection at high pincushion K) | **r ≤ 1.13** (full frame, edge-clipped pixels filtered automatically via `VALID_UV_MIN/MAX`) |
| Topology / ordering | sort-by-y bin (fragile under tangential distortion) | **N/A** — each pixel is self-identifying via its position |
| Detection algorithm | `CharucoDetector` + `cornerSubPix` (multiple failure modes under heavy distortion) | **None** — read R/G channel directly |

The high-r data points are critical: candidate distortion models diverge most at r > 0.7. UV gradient samples the full radial range natively.

## Probe specs (locked)

- 1920×1080 grayscale-float EXR, 3 channels
- R channel = (x + 0.5) / W (pixel-center U coord, identity in [0, 1])
- G channel = (y + 0.5) / H (pixel-center V coord)
- B channel = 0
- 32-bit float; PNG and 16-bit half are NOT supported (quantization error >0.5 px)
- File: `uv_probe_1920x1080.exr` (~220 KB), `uv_probe_truth.npz` (sanity metadata)

## Usage

### One-off setup
```bash
cd scripts/distortion_calibration
python3 -m venv .venv
.venv/bin/pip install --quiet numpy scipy opencv-python-headless pillow
.venv/bin/python generate_uv_probe.py
```

### Validate pipeline (rerun after any edit)
```bash
.venv/bin/python _self_test_truth.py
.venv/bin/python _self_test_analyze.py
.venv/bin/python _self_test_fit.py
```

### Process a Path A delivery (11 EXRs from d3)
```bash
# 11 EXRs from d3 dropped under /tmp/disguise_renders/
.venv/bin/python analyze_renders.py --input-dir /tmp/disguise_renders
.venv/bin/python fit_distortion_models.py    # default trims top 5% by residual
```

`fit_distortion_models.py` ranks by **BIC** (penalizes free parameters) so overfitting candidates lose to simpler-and-still-good ones.

### Process a Path B delivery (1 EXR from d3)
```bash
.venv/bin/python build_stmap.py --input /tmp/disguise_stmap/disguise_uvprobe.exr
# Then UE remote-execute stmap_writer.py to inject into LensFile
```

## Candidate models (Path A)

| Model | Forward map (undist r → dist r') | # free params |
|---|---|---|
| M1 | `r * (1 + α·K·r²)`                          UE-current shape | 1 (α) |
| M2 | `r / (1 + α·K·r²)`                          division model | 1 (α) |
| M3 | `r * (1 + a·K·r² + b·K²·r⁴)`               mixed K-order | 2 |
| M4 | `r + α·K·rᵖ`                                free radial exponent | 2 |
| M5 | `r * (1 + a·K·r² + b·K·r⁴ + c·K·r⁶)`       OpenCV K1-only style | 3 |

If M5 wins with `a≈1, b≈0, c≈0`, Disguise is standard OpenCV polynomial — Path A's reverse calc reduces to copying coefficients into UE LensFile K1/K2/K3.
If M2/M3/M4 wins, Disguise's formula doesn't match UE's polynomial form — UE LensFile can only best-fit-approximate, not pixel-perfect (this is the known polynomial ceiling).

## Conventions

- **Pixel coordinates**: OpenCV pixel-center origin (pixel (0,0) = top-left **center**).
- **r normalization**: `r = sqrt(dx² + dy²) / (W/2)`, so `r = 1` at the horizontal image edge.
- **K sign**: matches Disguise CSV (`K1=+0.5` means pincushion in Disguise convention).
  Sign-flip into UE LensFile happens later in `lens_file_builder.py`, not here.

## Path A — analyze_renders details

`analyze_renders.py` per-frame logic:
1. Read EXR, extract R/G channels (cv2 BGR storage, `[..., 2]` = R, `[..., 1]` = G)
2. Per output pixel (px, py):
   - `r_distorted = norm((px+0.5 - cx, py+0.5 - cy)) / half_width`
   - `r_undistorted = norm((R*W - cx, G*H - cy)) / half_width`
   - `dr = r_distorted - r_undistorted`
3. Filter: `0.005 < R, G < 0.995` (drop edge-clipped / off-FOV pixels)
4. Random subsample to `SAMPLES_PER_FRAME = 30000` (reproducible via `--seed`)

Anchor sanity check on the optional `disguise_K_zero.exr`:
- Verify R ≈ identity U-grid, G ≈ identity V-grid
- If max deviation > 1%, warn — likely LED gamma not linear / color transform applied / wrong frame export type
