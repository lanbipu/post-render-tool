"""Reverse-engineer the actual K2/K3 formula form used by Disguise.

Hypothesis under test (the "official" form used by Gate 6):
    src_norm = out_norm * (1 + K1*r^2 + K2*r^4 + K3*r^6)

Gate 6 reported 200-2400 px residuals, which is unsalvageable. So either:
- the polynomial degree is wrong (n != 4 for K2, n != 6 for K3),
- the formula is multiplicative inverse (1/(1+K*r^n)) instead of (1+K*r^n),
- the K coefficients have a different scale convention,
- or the radius normalization (sensor-half-width vs focal-length) differs.

This script:
  1. Reads anchor (K1=K2=K3=0) + each K2/K3 sweep frame.
  2. For each sweep frame, computes per-pixel:
       delta_x = src_x_actual - src_x_anchor
       delta_y = src_y_actual - src_y_anchor
       radial_delta = (delta_x*x + delta_y*y) / r       (project delta onto radial)
       warp_factor = radial_delta / r_out                (= K_eff * r^(n-1))
  3. Fits log(warp_factor) = log(K_eff) + (n-1)*log(r) in log-log space
     across radial buckets to recover n and K_eff.
  4. Tests linearity in K (K=0.3 vs K=0.5 should give 5/3 ratio for K_eff).

Usage:
    python3 reverse_k_formula.py
"""
from __future__ import annotations

import os
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

from pathlib import Path

import numpy as np

from _exr import load_probe_meta, read_uvprobe_exr
from analyze_renders import (
    VALID_UV_MAX,
    VALID_UV_MIN,
    detect_overscan_from_anchor,
)


VALIDATION_ROOT = Path("/Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration/validation_results")
K2_K3_DIR = VALIDATION_ROOT / "custom_pp_gate_inputs/k2_k3_sweep"
K1_DIR = VALIDATION_ROOT / "k1_sweep"

# Each entry: (label, value, frame_path, anchor_path)
SWEEPS = [
    ("K1",  0.10, K1_DIR / "disguise_K1_p0p10.exr", K1_DIR / "disguise_K1_zero.exr"),
    ("K1",  0.30, K1_DIR / "disguise_K1_p0p30.exr", K1_DIR / "disguise_K1_zero.exr"),
    ("K1", -0.10, K1_DIR / "disguise_K1_n0p10.exr", K1_DIR / "disguise_K1_zero.exr"),
    ("K1", -0.30, K1_DIR / "disguise_K1_n0p30.exr", K1_DIR / "disguise_K1_zero.exr"),
    ("K2",  0.30, K2_K3_DIR / "disguise_K2_p0p3.exr", K2_K3_DIR / "disguise_K2_zero.exr"),
    ("K2",  0.50, K2_K3_DIR / "disguise_K2_p0p5.exr", K2_K3_DIR / "disguise_K2_zero.exr"),
    ("K2", -0.30, K2_K3_DIR / "disguise_K2_n0p3.exr", K2_K3_DIR / "disguise_K2_zero.exr"),
    ("K2", -0.50, K2_K3_DIR / "disguise_K2_n0p5.exr", K2_K3_DIR / "disguise_K2_zero.exr"),
    ("K3",  0.30, K2_K3_DIR / "disguise_K3_p0p3.exr", K2_K3_DIR / "disguise_K2_zero.exr"),
    ("K3",  0.50, K2_K3_DIR / "disguise_K3_p0p5.exr", K2_K3_DIR / "disguise_K2_zero.exr"),
    ("K3", -0.30, K2_K3_DIR / "disguise_K3_n0p3.exr", K2_K3_DIR / "disguise_K2_zero.exr"),
    ("K3", -0.50, K2_K3_DIR / "disguise_K3_n0p5.exr", K2_K3_DIR / "disguise_K2_zero.exr"),
]


def src_pixels(R: np.ndarray, G: np.ndarray, overscan_margin: float, w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    span = 1.0 - 2.0 * overscan_margin
    return (R - overscan_margin) / span * w, (G - overscan_margin) / span * h


def fit_one_sweep(label: str, value: float, frame_path: Path, anchor_path: Path) -> dict | None:
    if not frame_path.exists():
        print(f"  MISSING frame: {frame_path.name}")
        return None
    if not anchor_path.exists():
        print(f"  MISSING anchor: {anchor_path.name}")
        return None
    R0, G0 = read_uvprobe_exr(anchor_path)
    overscan_factor, overscan_margin = detect_overscan_from_anchor(R0, G0)
    h, w = R0.shape
    half_w = w / 2.0
    src_x0, src_y0 = src_pixels(R0, G0, overscan_margin, w, h)

    xs_norm = (np.arange(w) + 0.5 - w / 2.0) / half_w
    ys_norm = (np.arange(h) + 0.5 - h / 2.0) / half_w
    X, Y = np.meshgrid(xs_norm, ys_norm)
    R_norm = np.hypot(X, Y)

    valid0 = (R0 > VALID_UV_MIN) & (R0 < VALID_UV_MAX) & (G0 > VALID_UV_MIN) & (G0 < VALID_UV_MAX)

    R, G = read_uvprobe_exr(frame_path)
    valid = valid0 & (R > VALID_UV_MIN) & (R < VALID_UV_MAX) & (G > VALID_UV_MIN) & (G < VALID_UV_MAX)
    src_x, src_y = src_pixels(R, G, overscan_margin, w, h)
    delta_x = src_x - src_x0
    delta_y = src_y - src_y0

    safe_r = np.where(R_norm > 1e-4, R_norm, 1.0)
    # radial component of delta in pixel space
    radial_delta = (delta_x * X + delta_y * Y) / safe_r
    out_r_px = R_norm * half_w
    warp_minus_one = np.where(out_r_px > 1.0, radial_delta / out_r_px, np.nan)

    sig = (
        np.isfinite(warp_minus_one)
        & (np.abs(warp_minus_one) > 5e-4)
        & valid
        & (R_norm > 0.1) & (R_norm < 1.2)
    )
    n_sig = int(np.count_nonzero(sig))
    if n_sig < 1000:
        print(f"  {frame_path.name:<32} {label:<4} {value:+.2f}  insufficient signal ({n_sig})")
        return None

    rs = R_norm[sig]
    ws = warp_minus_one[sig]
    log_r = np.log(rs)
    log_w = np.log(np.abs(ws))

    bucket_edges = np.linspace(np.log(0.15), np.log(1.15), 11)
    bcs, blws = [], []
    for lo, hi in zip(bucket_edges[:-1], bucket_edges[1:]):
        m = (log_r >= lo) & (log_r < hi)
        if m.sum() > 100:
            bcs.append(0.5 * (lo + hi))
            blws.append(float(np.median(log_w[m])))
    if len(bcs) < 4:
        print(f"  {frame_path.name:<32} {label:<4} {value:+.2f}  too few buckets")
        return None
    bc = np.array(bcs)
    bw = np.array(blws)
    A = np.vstack([bc, np.ones_like(bc)]).T
    slope, intercept = np.linalg.lstsq(A, bw, rcond=None)[0]
    n_rec = float(slope)
    K_eff = float(np.sign(np.median(ws)) * np.exp(intercept))

    m = (rs > 0.95) & (rs < 1.05)
    obs_at_r1 = float(np.median(ws[m])) if m.sum() > 100 else float("nan")
    return {
        "label": label,
        "value": value,
        "frame": frame_path.name,
        "n": n_rec,
        "K_eff": K_eff,
        "obs_at_r1": obs_at_r1,
        "n_signal_px": n_sig,
    }


def main() -> None:
    print(f"{'frame':<32} {'K':<4} {'value':<7} {'n':<7} {'K_eff':<10} {'obs_at_r=1':<12} {'K_eff/value':<12}")
    print("-" * 100)
    rows = []
    for label, value, frame_path, anchor_path in SWEEPS:
        r = fit_one_sweep(label, value, frame_path, anchor_path)
        if r is not None:
            rows.append(r)
            ratio = r["K_eff"] / value
            print(
                f"{r['frame']:<32} {label:<4} {value:+.2f}  {r['n']:<7.3f} "
                f"{r['K_eff']:<10.4f} {r['obs_at_r1']:<12.4f} {ratio:<12.4f}"
            )
    print()
    print("Reading the table:")
    print("  - 'n' is the radial-power exponent recovered from log-log slope.")
    print("    OpenCV expects: K1 -> n=2,  K2 -> n=4,  K3 -> n=6.")
    print("  - 'obs_at_r=1' is the per-pixel warp factor (src/out - 1) sampled at r_norm ~ 1.")
    print("    If formula is src = out*(1 + K*r^n), then obs_at_r=1 = K (when r=1).")
    print("  - 'K_eff/value' is the ratio between fitted K and the displayed K in d3.")
    print("    A consistent ratio across same-K-axis rows means linear scale; varying ratio means saturation/inverse form.")


if __name__ == "__main__":
    main()
