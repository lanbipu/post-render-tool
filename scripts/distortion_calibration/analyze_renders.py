"""Per-pixel distortion measurement from Disguise UV-probe transmission renders.

Path A (system identification) pipeline using UV gradient probe instead of
ChArUco corner detection. Each rendered EXR contains a forward distortion
sample at every pixel — ~2M data points per frame at 1080p, ~8M at 4K,
80x denser than the 276-corner ChArUco version, no detection / topology /
interpolation overhead.

Per output pixel (px, py) of a Disguise-rendered uv_probe transmission frame:
  EXR R channel = u_undist (source U the output pixel sampled from)
  EXR G channel = v_undist (source V)
  Source position in pixels: (R*W, G*H)
  Output position in pixels: (px + 0.5, py + 0.5)
  r_undistorted = norm((R*W - cx, G*H - cy)) / half_width
  r_distorted   = norm((px + 0.5 - cx, py + 0.5 - cy)) / half_width
  dr            = r_distorted - r_undistorted

The (K1, K2, K3, r_undistorted, dr) tuples drive curve_fit in
fit_distortion_models.py. Only one axis is non-zero per frame (single-axis
sweep); the fitter sees the union of all three sweeps.

File naming (place renders under --input-dir):
  Round 1 (legacy, single-axis K1, flat directory):
    disguise_K_zero.exr      K1 = 0.0   (sanity check, optional)
    disguise_K_p0p1.exr      K1 = +0.1  ('p'=positive, second 'p'=decimal point)
    disguise_K_n0p3.exr      K1 = -0.3  ('n'=negative)
  Round 2 (tri-axis K1/K2/K3, flat or k{1,2,3}_sweep/ subdirs — rglob picks both):
    disguise_K1_zero.exr     K1 = 0.0
    disguise_K1_p0p02.exr    K1 = +0.02
    disguise_K2_n0p20.exr    K2 = -0.20
    disguise_K3_p0p36.exr    K3 = +0.36

EXR MUST be 32-bit float (cv2 BGR layout). PNG / 16-bit half are NOT supported
— 8-bit quantization injects ~7 px noise; 16-bit half is borderline at 0.03 px.

Per-frame subsample size scales with resolution: 30k / frame at 1080p (default,
~330k rows for 11-frame Round 1) is plenty; bump --samples-per-frame to 100k+
for 4K Round 2 (153 frames × 100k ≈ 15M rows, ~1.5 GB CSV — still under
curve_fit's comfort zone, fits in RAM on a workstation).

Usage:
  Round 1 regression (1080p, 11 frames):
    ./.venv/bin/python analyze_renders.py \\
        --input-dir /tmp/disguise_renders \\
        --probe-truth uv_probe_truth_1920x1080.npz \\
        --output displacements.csv
  Round 2 default (4K, 153 frames, auto-detect probe truth):
    ./.venv/bin/python analyze_renders.py \\
        --input-dir /tmp/disguise_renders_round2 \\
        --samples-per-frame 100000 \\
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
    "K1", "K2", "K3", "pixel_id",
    "src_x_norm", "src_y_norm", "out_x_norm", "out_y_norm",
    "r_anchor", "r_dist", "dr",
)


# 支持 Round 1 (单轴: disguise_K_zero / disguise_K_p0p1) 和
# Round 2 (三轴: disguise_K1_zero / disguise_K2_p0p02 / disguise_K3_n0p50).
# 命名约定: 'p' = positive, 'n' = negative, 'p' (after digit) = decimal point.
_K_PATTERN = re.compile(
    r"^disguise_K(?P<axis>[123]?)_(?:(?P<zero>zero)|(?P<sign>[pn])(?P<value>\d+(?:p\d+)?))$",
    re.IGNORECASE,
)


def parse_k_value(stem: str) -> tuple[int, float]:
    """Returns (axis, value). axis ∈ {1, 2, 3}; Round 1 命名无 axis 数字, 默认 axis=1."""
    m = _K_PATTERN.match(stem)
    if not m:
        raise ValueError(f"cannot parse K from filename stem: {stem}")
    axis_str = m.group("axis") or "1"  # Round 1 命名缺 axis 数字, 默认 K1
    axis = int(axis_str)
    if m.group("zero"):
        return axis, 0.0
    sign = +1.0 if m.group("sign").lower() == "p" else -1.0
    return axis, sign * float(m.group("value").lower().replace("p", "."))


def compute_displacements(
    R: np.ndarray, G: np.ndarray, axis: int, K_value: float, rng: np.random.Generator,
    n_samples: int = SAMPLES_PER_FRAME,
) -> dict[str, np.ndarray] | None:
    """Sample-first per-pixel (K1, K2, K3, r, dr) extraction.

    Builds the validity mask on R/G only, draws n_samples indices,
    then computes the 8 normalized scalars on the sample. Avoids the
    full-resolution np.indices + r_dist + r_undist arrays that would peak
    at ~120 MB for a 1920x1080 float64 frame (4K = 4× larger, MUST sample).

    Parameters
    ----------
    axis: 1, 2, or 3 — which K axis is non-zero in this frame.
    K_value: the non-zero K coefficient for that axis (other two = 0).
    n_samples: per-frame random subsample size (default SAMPLES_PER_FRAME = 30000).
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

    n_sample = min(n_samples, len(valid_idx))
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

    K1 = np.full(n_sample, K_value if axis == 1 else 0.0)
    K2 = np.full(n_sample, K_value if axis == 2 else 0.0)
    K3 = np.full(n_sample, K_value if axis == 3 else 0.0)

    return {
        "K1": K1, "K2": K2, "K3": K3,
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
        "--input-dir", type=Path, default=Path("/tmp/disguise_renders_round2"),
        help="directory of disguise_K[1-3]_*.exr renders. "
             "Round 1 layout (flat dir of disguise_K_*.exr) also supported.",
    )
    ap.add_argument(
        "--output", type=Path, default=HERE / "displacements.csv",
        help="output CSV path",
    )
    ap.add_argument(
        "--samples-per-frame", type=int, default=SAMPLES_PER_FRAME,
        help=f"per-frame random subsample size (default {SAMPLES_PER_FRAME})",
    )
    ap.add_argument(
        "--probe-truth", type=Path, default=None,
        help="probe truth npz (auto-detect 4K → 1080p → legacy if omitted)",
    )
    ap.add_argument(
        "--seed", type=int, default=42,
        help="reproducible per-frame subsample",
    )
    args = ap.parse_args()

    if not args.input_dir.is_dir():
        raise SystemExit(f"input dir not found: {args.input_dir}")

    W, H = load_probe_meta(args.probe_truth)
    rng = np.random.default_rng(args.seed)

    # 收集所有 disguise_*.exr (递归 + flat 都支持). pathlib.Path.rglob 在 POSIX 是
    # case-sensitive, 用 'disguise_K*' 会漏掉 'disguise_k1_*' 之类小写命名;
    # 这里 broaden 到 'disguise_*.exr', 由 parse_k_value 的 IGNORECASE regex
    # 兜底过滤无关文件 (走 [skip] 分支).
    exr_files = list(args.input_dir.rglob("disguise_*.exr"))
    if not exr_files:
        raise SystemExit(f"no disguise_*.exr in {args.input_dir}")

    # Anchor sanity check: 每个 axis 取首个 K=0 帧, 用 parse_k_value 解析
    # (它已 IGNORECASE), 不再走 case-sensitive 的 axis_name rglob.
    zero_seen: set[int] = set()
    for cand in sorted(exr_files):
        try:
            axis, K_value = parse_k_value(cand.stem)
        except ValueError:
            continue
        if abs(K_value) < 1e-9 and axis not in zero_seen:
            anchor_sanity_check(cand, W, H)
            zero_seen.add(axis)

    batches: list[dict[str, np.ndarray]] = []
    seen_axes: dict[int, list[float]] = {1: [], 2: [], 3: []}
    for exr_path in sorted(exr_files):
        try:
            axis, K_value = parse_k_value(exr_path.stem)
        except ValueError as exc:
            print(f"  [skip] {exr_path.name}: {exc}")
            continue
        seen_axes[axis].append(K_value)
        if abs(K_value) < 1e-9:
            continue
        R, G = read_uvprobe_exr(exr_path)
        if R.shape != (H, W):
            print(f"  [skip] {exr_path.name}: shape {R.shape} ≠ probe {(H, W)}")
            continue
        result = compute_displacements(R, G, axis, K_value, rng, args.samples_per_frame)
        if result is None:
            print(f"  [warn] {exr_path.name}: no valid pixels (whole frame masked?)")
            continue
        batches.append(result)
        n = len(result["K1"])
        r_lo, r_hi = float(result["r_anchor"].min()), float(result["r_anchor"].max())
        dr_lo, dr_hi = float(result["dr"].min()), float(result["dr"].max())
        print(f"  {exr_path.name}: axis K{axis}={K_value:+.3f}, sampled {n}/{W * H} pixels "
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
    for axis in (1, 2, 3):
        if seen_axes[axis]:
            ks = sorted(set(seen_axes[axis]))
            print(f"  K{axis} values ({len(ks)}): {ks[:5]}...{ks[-2:]}" if len(ks) > 7 else f"  K{axis} values: {ks}")


if __name__ == "__main__":
    main()
