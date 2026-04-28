"""Per-pixel distortion measurement from Disguise UV-probe transmission renders.

Path A (system identification) pipeline using UV gradient probe instead of
ChArUco corner detection. Each rendered EXR contains a forward distortion
sample at every pixel — ~2M data points per frame, 80x denser than the
276-corner ChArUco version, no detection / topology / interpolation overhead.

Per output pixel (px, py) of a Disguise-rendered uv_probe transmission frame:
  EXR R channel = u_undist (source U the output pixel sampled from)
  EXR G channel = v_undist (source V)
  Source position in pixels: (R*W, G*H)
  Output position in pixels: (px + 0.5, py + 0.5)
  r_undistorted = norm((R*W - cx, G*H - cy)) / half_width
  r_distorted   = norm((px + 0.5 - cx, py + 0.5 - cy)) / half_width
  dr            = r_distorted - r_undistorted

The (K, r_undistorted, dr) tuples drive curve_fit in fit_distortion_models.py.

File naming (place renders under --input-dir):
  disguise_K_zero.exr      K = 0.0 (sanity check, optional)
  disguise_K_p0p1.exr      K = +0.1     ('p'=positive, second 'p'=decimal point)
  disguise_K_n0p3.exr      K = -0.3     ('n'=negative)

EXR MUST be 32-bit float (cv2 BGR layout). PNG / 16-bit half are NOT supported
— 8-bit quantization injects ~7 px noise; 16-bit half is borderline at 0.03 px.

Usage (after delivery):
  ./.venv/bin/python analyze_renders.py \\
      --input-dir /tmp/disguise_renders \\
      --output displacements.csv
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np

from _exr import (
    HERE, build_identity_uv_grid, load_probe_meta, read_uvprobe_exr,
)

# Per-frame random subsample. 30k × 11 frames = 330k rows total — far more
# than ChArUco's ~3000, well under curve_fit's comfort zone, keeps CSV size
# under ~30 MB. Reproducible via --seed.
SAMPLES_PER_FRAME = 30000

# Skip pixels at exact 0/1 in either channel — those are border/edge-clipped
# samples (Disguise sourced from outside the LED surface or hit FOV mask).
# 0.005 = ~10 px inset, generous against numerical near-zero precision noise.
VALID_UV_MIN = 0.005
VALID_UV_MAX = 0.995

# Anchor (K=0) sanity gate: above this normalized deviation the LED gamma /
# color transform / transmission-vs-overlay pipeline is suspect.
ANCHOR_DEVIATION_WARN = 0.01

CSV_FIELDS = (
    "K", "pixel_id",
    "src_x_norm", "src_y_norm", "out_x_norm", "out_y_norm",
    "r_anchor", "r_dist", "dr",
)


_K_PATTERN = re.compile(
    r"^disguise_K_(?:(zero)|([pn])(\d+(?:p\d+)?))$", re.IGNORECASE,
)


def parse_k_value(stem: str) -> float:
    m = _K_PATTERN.match(stem)
    if not m:
        raise ValueError(f"cannot parse K from filename stem: {stem}")
    if m.group(1):
        return 0.0
    sign = +1.0 if m.group(2).lower() == "p" else -1.0
    return sign * float(m.group(3).replace("p", "."))


def compute_displacements(
    R: np.ndarray, G: np.ndarray, K: float, rng: np.random.Generator,
) -> dict[str, np.ndarray] | None:
    """Sample-first per-pixel (K, r, dr) extraction.

    Builds the validity mask on R/G only, draws SAMPLES_PER_FRAME indices,
    then computes the 8 normalized scalars on the sample. Avoids the
    full-resolution np.indices + r_dist + r_undist arrays that would peak
    at ~120 MB for a 1920x1080 float64 frame.
    """
    H, W = R.shape
    cx = W / 2.0
    cy = H / 2.0
    half_w = W / 2.0

    valid = (
        (R > VALID_UV_MIN) & (R < VALID_UV_MAX) &
        (G > VALID_UV_MIN) & (G < VALID_UV_MAX)
    )
    valid_idx = np.flatnonzero(valid.ravel())
    if len(valid_idx) == 0:
        return None

    n_sample = min(SAMPLES_PER_FRAME, len(valid_idx))
    sample = rng.choice(valid_idx, size=n_sample, replace=False)
    ys, xs = np.unravel_index(sample, (H, W))
    R_s = R.ravel()[sample]
    G_s = G.ravel()[sample]

    out_x_norm = (xs.astype(np.float64) + 0.5 - cx) / half_w
    out_y_norm = (ys.astype(np.float64) + 0.5 - cy) / half_w
    src_x_norm = (R_s * W - cx) / half_w
    src_y_norm = (G_s * H - cy) / half_w
    r_dist = np.hypot(out_x_norm, out_y_norm)
    r_undist = np.hypot(src_x_norm, src_y_norm)

    return {
        "K": np.full(n_sample, K),
        "pixel_id": sample.astype(np.int32),
        "src_x_norm": src_x_norm,
        "src_y_norm": src_y_norm,
        "out_x_norm": out_x_norm,
        "out_y_norm": out_y_norm,
        "r_anchor": r_undist,
        "r_dist": r_dist,
        "dr": r_dist - r_undist,
    }


def anchor_sanity_check(anchor_path: Path, W: int, H: int) -> None:
    """K=0 frame should reproduce the source UV grid almost exactly.

    Large deviations flag pipeline issues (LED gamma not linear, color
    transform applied, EXR resolution mismatch) that would corrupt
    downstream fits.
    """
    R0, G0 = read_uvprobe_exr(anchor_path)
    u_truth, v_truth = build_identity_uv_grid(W, H)
    u_dev = float(np.abs(R0 - u_truth).max())
    v_dev = float(np.abs(G0 - v_truth).max())
    print(f"K=0 anchor sanity ({anchor_path.name}):")
    print(f"  R channel max deviation: {u_dev:.5f}  ({u_dev * W:.2f} px)")
    print(f"  G channel max deviation: {v_dev:.5f}  ({v_dev * H:.2f} px)")
    if u_dev > ANCHOR_DEVIATION_WARN or v_dev > ANCHOR_DEVIATION_WARN:
        print("  [WARN] >1% deviation — investigate LED gamma / color transform / "
              "transmission-vs-overlay before trusting fits")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input-dir", type=Path, default=Path("/tmp/disguise_renders"),
        help="directory of disguise_K_*.exr renders",
    )
    ap.add_argument(
        "--output", type=Path, default=HERE / "displacements.csv",
        help="output CSV path",
    )
    ap.add_argument(
        "--seed", type=int, default=42,
        help="reproducible per-frame subsample",
    )
    args = ap.parse_args()

    if not args.input_dir.is_dir():
        raise SystemExit(f"input dir not found: {args.input_dir}")

    W, H = load_probe_meta()
    rng = np.random.default_rng(args.seed)

    anchor_path = args.input_dir / "disguise_K_zero.exr"
    if anchor_path.exists():
        anchor_sanity_check(anchor_path, W, H)

    batches: list[dict[str, np.ndarray]] = []
    seen_K: list[float] = []
    for png in sorted(args.input_dir.glob("disguise_K_*.exr")):
        K = parse_k_value(png.stem)
        seen_K.append(K)
        if abs(K) < 1e-9:
            continue
        R, G = read_uvprobe_exr(png)
        result = compute_displacements(R, G, K, rng)
        if result is None:
            print(f"  [warn] {png.name}: no valid pixels (whole frame masked?)")
            continue
        batches.append(result)
        n = len(result["K"])
        r_lo, r_hi = float(result["r_anchor"].min()), float(result["r_anchor"].max())
        dr_lo, dr_hi = float(result["dr"].min()), float(result["dr"].max())
        print(f"  {png.name}: K={K:+.3f}, sampled {n}/{W * H} pixels "
              f"(r ∈ [{r_lo:.3f}, {r_hi:.3f}], dr ∈ [{dr_lo:+.4f}, {dr_hi:+.4f}])")

    if not batches:
        raise SystemExit("no rows emitted — check input directory and EXR validity")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    all_rows = np.concatenate(
        [np.column_stack([b[name] for name in CSV_FIELDS]) for b in batches]
    )
    np.savetxt(
        args.output, all_rows,
        delimiter=",", fmt="%.8g",
        header=",".join(CSV_FIELDS), comments="",
    )
    print(f"wrote {all_rows.shape[0]} rows to {args.output}")
    print(f"K values: {sorted(set(seen_K))}")


if __name__ == "__main__":
    main()
