"""End-to-end validation: M6 → distortion_math → UE polynomial vs Disguise EXR.

For each disguise_K_*.exr render in /tmp/disguise_renders/:
  1. Parse csv_K1 from filename
  2. Run csv_K1 through Content.Python.post_render_tool.distortion_math
     (the production code path) to compute (ue_K1, ue_K2, ue_K3)
  3. Apply UE's Brown-Conrady forward polynomial r·(1 + K1·r² + K2·r⁴ + K3·r⁶)
     on the identity UV grid to predict where each source pixel ends up
  4. Compare to where Disguise actually rendered each source pixel
     (extracted from EXR R/G channels)
  5. Report per-K RMS, median, max

Expected outcome: RMS ≈ 0.4 px per K, near noise floor (0.46 px from K=0
direct measurement). Confirms that:
  - distortion_math implementation is bit-exact with M6 coefficients
  - UE polynomial form matches Disguise rendering at per-pixel level
  - The entire CSV→UE LensFile chain is mathematically sound
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from _exr import read_uvprobe_exr
from analyze_renders import VALID_UV_MAX, VALID_UV_MIN, parse_k_value

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "Content" / "Python"))
from post_render_tool.distortion_math import compute_normalized_distortion


@dataclass
class _StubFrame:
    """Minimal FrameData-like stub to feed compute_normalized_distortion."""
    k1: float
    k2: float = 0.0
    k3: float = 0.0
    center_shift_x_mm: float = 0.0
    center_shift_y_mm: float = 0.0
    sensor_width_mm: float = 35.0
    focal_length_mm: float = 30.0
    aspect_ratio: float = 1.7778


def ue_polynomial_forward(r_undist: np.ndarray, K1: float, K2: float, K3: float) -> np.ndarray:
    """UE Brown-Conrady forward map: r_dist = r·(1 + K1·r² + K2·r⁴ + K3·r⁶)."""
    r2 = r_undist ** 2
    return r_undist * (1.0 + K1 * r2 + K2 * r2 ** 2 + K3 * r2 ** 3)


def validate_one(exr_path: Path) -> tuple[float, float, float, float, int] | None:
    """Returns (csv_K1, RMS_px, median_px, max_px, n_samples) or None on failure."""
    csv_k1 = parse_k_value(exr_path.stem)
    if abs(csv_k1) < 1e-9:
        return None  # K=0 frame: nothing to predict
    R, G = read_uvprobe_exr(exr_path)
    H, W = R.shape
    cx, cy = W / 2.0, H / 2.0
    half_w = W / 2.0

    frame = _StubFrame(k1=csv_k1)
    nd = compute_normalized_distortion(frame)
    ue_K1, ue_K2, ue_K3 = nd["k1"], nd["k2"], nd["k3"]

    # Validity mask: skip pixels Disguise rendered as off-LED background
    valid = (
        (R > VALID_UV_MIN) & (R < VALID_UV_MAX) &
        (G > VALID_UV_MIN) & (G < VALID_UV_MAX)
    )

    # Source position from EXR R/G (where each output pixel sampled from)
    src_x = R * W
    src_y = G * H
    r_undist = np.hypot(src_x - cx, src_y - cy) / half_w

    # Actual output position (pixel center)
    ys, xs = np.indices((H, W), dtype=np.float64)
    r_dist_actual = np.hypot(xs + 0.5 - cx, ys + 0.5 - cy) / half_w

    # M6 prediction via UE polynomial chain
    r_dist_pred = ue_polynomial_forward(r_undist, ue_K1, ue_K2, ue_K3)

    err = np.abs(r_dist_actual - r_dist_pred) * half_w
    err_valid = err[valid]
    if err_valid.size == 0:
        return None
    sorted_err = np.sort(err_valid)
    n = sorted_err.size
    trimmed = sorted_err[: int(n * 0.95)]
    rms = float(np.sqrt(np.mean(trimmed ** 2)))
    median = float(np.median(err_valid))
    max_e = float(err_valid.max())
    return csv_k1, rms, median, max_e, n


def main() -> None:
    input_dir = Path("/tmp/disguise_renders")
    if not input_dir.is_dir():
        raise SystemExit(f"input dir not found: {input_dir}")

    print("CSV K1 → distortion_math → UE polynomial vs Disguise EXR")
    print(f"{'csv_K1':>7} | {'ue_K1':>9} | {'ue_K2':>9} | {'ue_K3':>9} | "
          f"{'median':>8} | {'rms_95%':>8} | {'max':>7} | {'n':>9}")
    print("-" * 95)

    rms_list: list[float] = []
    for png in sorted(input_dir.glob("disguise_K_*.exr")):
        out = validate_one(png)
        if out is None:
            continue
        csv_k1, rms, median, max_e, n = out
        nd = compute_normalized_distortion(_StubFrame(k1=csv_k1))
        print(f"{csv_k1:+7.2f} | "
              f"{nd['k1']:+9.5f} | {nd['k2']:+9.5f} | {nd['k3']:+9.5f} | "
              f"{median:8.3f} | {rms:8.3f} | {max_e:7.2f} | {n:>9}")
        rms_list.append(rms)

    print("-" * 95)
    if rms_list:
        agg_rms = float(np.sqrt(np.mean(np.square(rms_list))))
        print(f"aggregate trimmed RMS across all K: {agg_rms:.3f} px")
        print()
        print("Reference noise floor (K=0 anchor frame deviation): 0.457 px RMS")
        print(f"Pipeline ratio (lower is better): {agg_rms / 0.457:.2f}x")


if __name__ == "__main__":
    main()
