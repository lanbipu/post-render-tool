"""Tier 2 final - apply UE BrownConradyUD rational distortion to K=0 source PNG,
compare to actual K=+0.5 Disguise output. If M_RAT6 matches Disguise, predicted
should equal actual within noise floor across the whole image (NOT just center).
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np


W, H = 1920, 1080
FX_UV = 30.302 / 35.0
FY_UV = FX_UV * (W / H)
CX, CY = 0.5, 0.5

# UE BrownConradyUD coefficients written into LensFile for csv_K1=+0.5
# Computed from M_RAT6 fit (commit 8164938) with HW-norm -> fx-norm (2*fx)^(2k) scaling.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Content" / "Python"))
from post_render_tool.distortion_math import (
    M_RAT6_A, M_RAT6_B, M_RAT6_C, M_RAT6_D, M_RAT6_E, M_RAT6_F,
)

csv_k1 = +0.5
fx_scale = 2.0 * FX_UV
fx2 = fx_scale ** 2
fx4 = fx2 ** 2
fx6 = fx4 * fx2
UE_K1 = M_RAT6_A * csv_k1 * fx2
UE_K2 = M_RAT6_B * csv_k1**2 * fx4
UE_K3 = M_RAT6_C * csv_k1**3 * fx6
UE_K4 = M_RAT6_D * csv_k1 * fx2
UE_K5 = M_RAT6_E * csv_k1**2 * fx4
UE_K6 = M_RAT6_F * csv_k1**3 * fx6


def newton_inverse_rational(r_dist: np.ndarray, iters: int = 25) -> np.ndarray:
    r = r_dist.copy()
    for _ in range(iters):
        r2 = r * r
        num = 1 + UE_K1 * r2 + UE_K2 * r2 * r2 + UE_K3 * r2 * r2 * r2
        den = 1 + UE_K4 * r2 + UE_K5 * r2 * r2 + UE_K6 * r2 * r2 * r2
        f = r * num / np.where(np.abs(den) > 1e-9, den, 1e-9) - r_dist
        h = 1e-6
        r_h = r + h
        r2_h = r_h * r_h
        num_h = 1 + UE_K1 * r2_h + UE_K2 * r2_h * r2_h + UE_K3 * r2_h * r2_h * r2_h
        den_h = 1 + UE_K4 * r2_h + UE_K5 * r2_h * r2_h + UE_K6 * r2_h * r2_h * r2_h
        f_h = r_h * num_h / np.where(np.abs(den_h) > 1e-9, den_h, 1e-9) - r_dist
        fp = (f_h - f) / h
        r = r - f / np.where(np.abs(fp) > 1e-9, fp, 1e-9)
        r = np.clip(r, 0.0, 5.0)
    return r


def main():
    src = cv2.imread("/tmp/d3_K_zero_source.png", cv2.IMREAD_UNCHANGED)
    actual = cv2.imread("/tmp/d3_K_p0p5_from_png.png", cv2.IMREAD_UNCHANGED)
    if src is None or actual is None:
        raise SystemExit("missing source PNG: ensure /tmp/d3_K_zero_source.png and /tmp/d3_K_p0p5_from_png.png exist")
    print(f"source K=0:    {src.shape}  mean {src.mean():.1f}")
    print(f"actual K=+0.5: {actual.shape}  mean {actual.mean():.1f}")
    print(f"UE coefficients: K1={UE_K1:+.4f} K2={UE_K2:+.4f} K3={UE_K3:+.4f}")
    print(f"                 K4={UE_K4:+.4f} K5={UE_K5:+.4f} K6={UE_K6:+.4f}")

    ys, xs = np.indices((H, W), dtype=np.float64)
    out_u = (xs + 0.5) / W
    out_v = (ys + 0.5) / H
    cam_x_d = (out_u - CX) / FX_UV
    cam_y_d = (out_v - CY) / FY_UV
    r_d = np.hypot(cam_x_d, cam_y_d)

    r_u = newton_inverse_rational(r_d)
    safe = r_d > 1e-9
    scale = np.where(safe, r_u / np.where(safe, r_d, 1.0), 1.0)
    cam_x_u = cam_x_d * scale
    cam_y_u = cam_y_d * scale
    src_x = (cam_x_u * FX_UV + CX) * W - 0.5
    src_y = (cam_y_u * FY_UV + CY) * H - 0.5

    predicted = cv2.remap(src, src_x.astype(np.float32), src_y.astype(np.float32),
                          cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    cv2.imwrite("/tmp/d3_K_p0p5_predicted_via_brownconradyud.png", predicted)

    pred_g = cv2.cvtColor(predicted, cv2.COLOR_BGR2GRAY).astype(np.float64) if predicted.ndim == 3 else predicted.astype(np.float64)
    actual_g = cv2.cvtColor(actual, cv2.COLOR_BGR2GRAY).astype(np.float64) if actual.ndim == 3 else actual.astype(np.float64)
    diff = pred_g - actual_g

    half_w = W / 2.0
    r_norm = np.hypot(xs - W / 2, ys - H / 2) / half_w

    print()
    print(f"=== diff stats by region ===")
    for r_lo, r_hi, name in [(0, 0.5, "center  r<0.5     "),
                               (0.5, 0.8, "mid     0.5<=r<0.8"),
                               (0.8, 99, "outer   r>=0.8    ")]:
        mask = (r_norm >= r_lo) & (r_norm < r_hi)
        sub = diff[mask]
        rms = np.sqrt(np.mean(sub ** 2))
        clean = (np.abs(sub) < 5).mean() * 100
        print(f"  {name}: RMS {rms:5.1f}, |diff|<5/255 {clean:.1f}%")

    edges_pred = cv2.Canny(pred_g.astype(np.uint8), 50, 150)
    edges_actual = cv2.Canny(actual_g.astype(np.uint8), 50, 150)
    dist = cv2.distanceTransform((edges_actual == 0).astype(np.uint8), cv2.DIST_L2, 5)
    px = np.where(edges_pred > 0)
    if len(px[0]) > 0:
        d = dist[px]
        edge_y, edge_x = px
        edge_r = np.hypot(edge_x - W / 2, edge_y - H / 2) / half_w
        print()
        print(f"=== predicted edges -> actual edges distance (px) ===")
        for r_lo, r_hi, name in [(0, 0.5, "center  r<0.5     "),
                                  (0.5, 0.8, "mid     0.5<=r<0.8"),
                                  (0.8, 99, "outer   r>=0.8    ")]:
            m = (edge_r >= r_lo) & (edge_r < r_hi)
            if m.sum() == 0:
                continue
            sub_d = d[m]
            print(f"  {name}: median {np.median(sub_d):.2f}, p95 {np.percentile(sub_d, 95):.2f}, max {sub_d.max():.2f}")

    # Newton convergence check: residual r_forward(r_u) - r_d
    r_u_sample = r_u[::50, ::50].ravel()
    r_d_sample = r_d[::50, ::50].ravel()
    r2 = r_u_sample ** 2
    num = 1 + UE_K1 * r2 + UE_K2 * r2 * r2 + UE_K3 * r2 * r2 * r2
    den = 1 + UE_K4 * r2 + UE_K5 * r2 * r2 + UE_K6 * r2 * r2 * r2
    r_fwd = r_u_sample * num / np.where(np.abs(den) > 1e-9, den, 1e-9)
    newton_residual = np.abs(r_fwd - r_d_sample)
    print()
    print(f"=== Newton convergence check (25 iters) ===")
    print(f"  residual |forward(r_u) - r_d|: median {np.median(newton_residual):.2e}, max {newton_residual.max():.2e}")


if __name__ == "__main__":
    main()
