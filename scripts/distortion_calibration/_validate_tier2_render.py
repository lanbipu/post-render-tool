"""Tier 2 final - apply UE-computed displacement RT to UV probe, compare to Disguise EXR.

UE produced a 256x256 RG16F displacement render target by evaluating our M6
LensFile via SphericalLensDistortionModelHandler. This is what the actual
distortion shader samples per output pixel. Bilinearly upsample to full
1920x1080, apply to identity UV grid, compare result to disguise_K_p0p5.exr
R/G channels (which encode where each output pixel sourced from per Disguise).

If UE shader implementation matches our M6 expectation, residual ~= noise floor.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np


W, H = 1920, 1080
HALF_W = W / 2.0


def read_exr(path):
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"cannot read {path}")
    return img


def upsample_displacement(disp_rt: np.ndarray, target_w: int, target_h: int) -> tuple[np.ndarray, np.ndarray]:
    """Bilinearly upsample 256x256 displacement RT to target resolution.

    cv2 BGR storage: index 2 = R, index 1 = G.
    Returns (du_field, dv_field) at target resolution.
    """
    R = disp_rt[..., 2].astype(np.float64)
    G = disp_rt[..., 1].astype(np.float64)
    du = cv2.resize(R, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    dv = cv2.resize(G, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    return du, dv


def main() -> None:
    ue_disp = read_exr("/tmp/ue_disp_K_p0p5.exr")
    print(f"UE distortion RT: shape={ue_disp.shape} dtype={ue_disp.dtype}")
    print(f"  R range [{ue_disp[...,2].min():+.5f}, {ue_disp[...,2].max():+.5f}]")
    print(f"  G range [{ue_disp[...,1].min():+.5f}, {ue_disp[...,1].max():+.5f}]")
    print()

    disguise = read_exr(Path("/tmp/disguise_renders/disguise_K_p0p5.exr"))
    print(f"Disguise EXR: shape={disguise.shape}")

    du_field, dv_field = upsample_displacement(ue_disp, W, H)
    print(f"upsampled displacement: {du_field.shape}, R range [{du_field.min():+.5f}, {du_field.max():+.5f}]")

    # Per output pixel (px, py): UV grid coords are (px+0.5)/W, (py+0.5)/H
    ys, xs = np.indices((H, W), dtype=np.float64)
    u_out = (xs + 0.5) / W
    v_out = (ys + 0.5) / H

    R_disguise = disguise[..., 2].astype(np.float64)
    G_disguise = disguise[..., 1].astype(np.float64)

    # Try multiple sign / scale conventions to find the right one
    print()
    print("=== try different displacement conventions ===")
    print(f"{'convention':>40} | {'mean U err':>14} | {'mean V err':>14} | {'RMS px':>10}")
    print("-" * 90)

    for name, src_u, src_v in [
        ("raw + (source = out + disp)", u_out + du_field, v_out + dv_field),
        ("raw - (source = out - disp)", u_out - du_field, v_out - dv_field),
        ("scale 2 + (source = out + 2*disp)", u_out + 2 * du_field, v_out + 2 * dv_field),
        ("scale 2 - (source = out - 2*disp)", u_out - 2 * du_field, v_out - 2 * dv_field),
        ("biased decode + (s=out+(disp*2-1))", u_out + (du_field * 2 - 1), v_out + (dv_field * 2 - 1)),
    ]:
        valid = (R_disguise > 0.01) & (R_disguise < 0.99) & (G_disguise > 0.01) & (G_disguise < 0.99)
        u_err = (src_u - R_disguise)[valid]
        v_err = (src_v - G_disguise)[valid]
        u_err_px = u_err * W
        v_err_px = v_err * H
        rms_px = float(np.sqrt(np.mean(u_err_px ** 2 + v_err_px ** 2)))
        print(f"{name:>40} | {float(u_err_px.mean()):+14.4f} | {float(v_err_px.mean()):+14.4f} | {rms_px:>10.3f}")

    print()
    print("=== best convention details ===")
    # whichever gave lowest RMS (likely raw + or scale 2 +)
    best_name = "raw + (source = out + disp)"
    src_u = u_out + du_field
    src_v = v_out + dv_field
    valid = (R_disguise > 0.01) & (R_disguise < 0.99) & (G_disguise > 0.01) & (G_disguise < 0.99)
    u_err_px = (src_u - R_disguise)[valid] * W
    v_err_px = (src_v - G_disguise)[valid] * H
    err_combined = np.hypot(u_err_px, v_err_px)
    print(f"convention: {best_name}")
    print(f"  median: {np.median(err_combined):.3f} px")
    print(f"  RMS:    {float(np.sqrt(np.mean(err_combined**2))):.3f} px")
    print(f"  p95:    {float(np.percentile(err_combined, 95)):.3f} px")
    print(f"  max:    {float(err_combined.max()):.3f} px")


if __name__ == "__main__":
    main()
