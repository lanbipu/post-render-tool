"""Tier 2 final - UE polynomial with corrected fx-norm K values vs Disguise EXR.

Reads K1/K2/K3 stored in the UE LensFile (after fx-norm correction in
distortion_math.py), applies them in fx-norm Newton inverse polynomial
on Mac, predicts per-pixel source UV. Compares to Disguise EXR R/G
channels (truth). If math is right, residual ≈ noise floor.

This bypasses the displacement RT decoding (which has UE-specific overscan
encoding) and tests the pure polynomial math at the K values UE actually has.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np


W, H = 1920, 1080

# K values written into LensFile after fx-norm correction (read from UE LensFile,
# Tier 1 v2 readback at /Game/PostRender/synth_K1_p0p5/LF_synth_K1_p0p5)
UE_K1 = -0.375829
UE_K2 = +0.471272
UE_K3 = -0.650567

# Camera params
FX_UV = 30.302 / 35.0          # fx in screen UV space
FY_UV = FX_UV * (1920 / 1080)  # fy = fx * aspect
CX_UV = 0.5
CY_UV = 0.5


def newton_inverse_polynomial(r_dist: np.ndarray, K1: float, K2: float, K3: float, iters: int = 12) -> np.ndarray:
    """Solve r * (1 + K1·r² + K2·r⁴ + K3·r⁶) = r_dist for r.

    Vectorized Newton iteration. Initial guess r ≈ r_dist works for |Kr²| < 1.
    """
    r = r_dist.copy()
    for _ in range(iters):
        r2 = r * r
        factor = 1.0 + K1 * r2 + K2 * r2 * r2 + K3 * r2 * r2 * r2
        f = r * factor - r_dist
        fp = 1.0 + 3 * K1 * r2 + 5 * K2 * r2 * r2 + 7 * K3 * r2 * r2 * r2
        r = r - f / np.where(np.abs(fp) > 1e-9, fp, 1e-9)
        r = np.clip(r, 0.0, 5.0)
    return r


def main() -> None:
    print("Tier 2 - UE polynomial (fx-norm) with corrected K vs Disguise EXR")
    print(f"  UE K1 = {UE_K1:+.6f}")
    print(f"  UE K2 = {UE_K2:+.6f}")
    print(f"  UE K3 = {UE_K3:+.6f}")
    print(f"  fx_uv = {FX_UV:.5f}, fy_uv = {FY_UV:.5f}")

    disguise = cv2.imread(str(Path("/tmp/disguise_renders/disguise_K_p0p5.exr")), cv2.IMREAD_UNCHANGED)
    R_d = disguise[..., 2].astype(np.float64)
    G_d = disguise[..., 1].astype(np.float64)

    # Per output pixel, normalized cam coords (fx-norm)
    ys, xs = np.indices((H, W), dtype=np.float64)
    out_u = (xs + 0.5) / W
    out_v = (ys + 0.5) / H
    cam_out_x = (out_u - CX_UV) / FX_UV
    cam_out_y = (out_v - CY_UV) / FY_UV
    r_dist_n = np.hypot(cam_out_x, cam_out_y)

    # Newton inverse: source r in fx-norm space
    r_undist_n = newton_inverse_polynomial(r_dist_n, UE_K1, UE_K2, UE_K3)

    # Source position in cam coords (preserve angle)
    safe = r_dist_n > 1e-9
    scale = np.where(safe, r_undist_n / np.where(safe, r_dist_n, 1.0), 1.0)
    cam_src_x = cam_out_x * scale
    cam_src_y = cam_out_y * scale
    src_u = cam_src_x * FX_UV + CX_UV
    src_v = cam_src_y * FY_UV + CY_UV

    # Compare to Disguise R/G
    valid = (R_d > 0.005) & (R_d < 0.995) & (G_d > 0.005) & (G_d < 0.995)
    err_u_px = (src_u - R_d)[valid] * W
    err_v_px = (src_v - G_d)[valid] * H
    err_radial = np.hypot(err_u_px, err_v_px)
    n = err_radial.size

    sorted_err = np.sort(err_radial)
    trimmed = sorted_err[: int(n * 0.95)]
    rms_trimmed = float(np.sqrt(np.mean(trimmed ** 2)))
    median = float(np.median(err_radial))
    p95 = float(np.percentile(err_radial, 95))
    max_e = float(err_radial.max())

    print()
    print(f"valid pixels: {n}/{H*W}")
    print(f"median:           {median:8.3f} px")
    print(f"trimmed_rms_95:   {rms_trimmed:8.3f} px")
    print(f"p95:              {p95:8.3f} px")
    print(f"max:              {max_e:8.3f} px")
    print()
    print(f"Reference noise floor: 0.457 px")
    print(f"Pipeline ratio: {rms_trimmed / 0.457:.2f}x noise floor")
    if rms_trimmed < 0.6:
        print("VERDICT: at noise floor, M6+fx-norm correction VALIDATED")
    elif rms_trimmed < 1.5:
        print("VERDICT: marginal, near noise floor")
    else:
        print("VERDICT: residual > noise floor, investigate")


if __name__ == "__main__":
    main()
