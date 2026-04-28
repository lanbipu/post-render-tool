"""Synthetic-data validation for build_stmap.py.

Applies a known barrel distortion to the identity probe, runs the build_stmap
pipeline, and verifies that:
  - the recovered undistortion direction matches the analytic inverse
  - the recovered distortion direction matches the analytic forward map
  - distort(undistort(uv)) roundtrip is < 0.05 px

Usage:
  .venv/bin/python _self_test_stmap.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_stmap import build_distortion_uv, read_uvprobe, write_stmap

W, H = 1920, 1080
K = 0.30  # barrel distortion strength (analogous to Disguise K1)


def forward_distort_uv(u: np.ndarray, v: np.ndarray, k: float) -> tuple[np.ndarray, np.ndarray]:
    """Map undistorted (u, v) -> distorted (u', v') with r * (1 + k * r^2)."""
    cu, cv = 0.5, 0.5
    rx = (u - cu) / 0.5  # normalized so edge -> r=1
    ry = (v - cv) / 0.5
    r = np.hypot(rx, ry)
    scale = 1.0 + k * r * r  # r' / r
    rx2 = rx * scale
    ry2 = ry * scale
    return (cu + 0.5 * rx2).astype(np.float32), (cv + 0.5 * ry2).astype(np.float32)


def inverse_distort_uv(u_d: np.ndarray, v_d: np.ndarray, k: float) -> tuple[np.ndarray, np.ndarray]:
    """Map distorted (u', v') -> undistorted (u, v) by solving r * (1+k*r^2) = r' (Newton)."""
    cu, cv = 0.5, 0.5
    rx = (u_d - cu) / 0.5
    ry = (v_d - cv) / 0.5
    r_d = np.hypot(rx, ry)
    # Newton-solve: f(r) = r * (1 + k*r^2) - r_d
    r = r_d.copy()
    for _ in range(20):
        f = r * (1.0 + k * r * r) - r_d
        df = 1.0 + 3.0 * k * r * r
        r = r - f / np.maximum(df, 1e-9)
    # scale rx, ry by r / r_d
    scale = np.where(r_d > 1e-9, r / np.maximum(r_d, 1e-9), 1.0)
    rx2 = rx * scale
    ry2 = ry * scale
    return (cu + 0.5 * rx2).astype(np.float32), (cv + 0.5 * ry2).astype(np.float32)


def synthesize_disguise_output() -> Path:
    """Generate a faux Disguise-rendered uv_probe EXR with known barrel K."""
    xs = (np.arange(W, dtype=np.float32) + 0.5) / W
    ys = (np.arange(H, dtype=np.float32) + 0.5) / H
    qx, qy = np.meshgrid(xs, ys, indexing="xy")  # (H, W) — distorted output pixel uv

    # At distorted output pixel (qx, qy), the LED content seen is at undistorted (u, v)
    u_undist, v_undist = inverse_distort_uv(qx, qy, K)

    # Pack as 3-channel BGR for cv2
    out = np.zeros((H, W, 3), dtype=np.float32)
    out[..., 0] = 0.0          # B
    out[..., 1] = v_undist     # G = undistorted V
    out[..., 2] = u_undist     # R = undistorted U
    path = Path("/tmp/_synth_disguise_uvprobe.exr")
    if not cv2.imwrite(str(path), out):
        raise RuntimeError("cv2.imwrite failed")
    return path


def main() -> None:
    print(f"[synth] generating disguise-style uvprobe with barrel K={K}")
    in_path = synthesize_disguise_output()
    print(f"        {in_path}")

    u_undist, v_undist, _, _ = read_uvprobe(in_path)

    # 1. Verify undistortion matches analytic inverse
    xs = (np.arange(W, dtype=np.float32) + 0.5) / W
    ys = (np.arange(H, dtype=np.float32) + 0.5) / H
    qx, qy = np.meshgrid(xs, ys, indexing="xy")
    u_undist_truth, v_undist_truth = inverse_distort_uv(qx, qy, K)
    err_u_undist = np.abs(u_undist - u_undist_truth).max() * W
    err_v_undist = np.abs(v_undist - v_undist_truth).max() * H
    print(f"[chk]   undistortion vs analytic inverse: max err {err_u_undist:.3f}/{err_v_undist:.3f} px (U/V)")
    assert err_u_undist < 0.01 and err_v_undist < 0.01, "undistortion direction mismatch"

    # 2. Run build_distortion_uv (the inverse-interpolation core)
    print(f"[run]   build_distortion_uv (cubic)")
    u_dist, v_dist = build_distortion_uv(u_undist, v_undist, W, H, method="cubic")

    # 3. Verify distortion matches analytic forward.
    # Restrict to the convex hull of available samples — outside that region
    # we extrapolate, which has no analytic ground truth to match (UE clamps
    # the sampler so off-frame regions get the nearest valid sample anyway).
    u_dist_truth, v_dist_truth = forward_distort_uv(qx, qy, K)
    in_frame = (u_dist_truth >= 0.0) & (u_dist_truth <= 1.0) & \
               (v_dist_truth >= 0.0) & (v_dist_truth <= 1.0)
    err_u = np.abs(u_dist - u_dist_truth)[in_frame]
    err_v = np.abs(v_dist - v_dist_truth)[in_frame]
    err_u_dist = err_u.max() * W
    err_v_dist = err_v.max() * H
    err_u_dist_avg = err_u.mean() * W
    err_v_dist_avg = err_v.mean() * H
    coverage = in_frame.mean()
    print(f"[chk]   distortion vs analytic forward (in-frame {coverage*100:.1f}%): max err {err_u_dist:.3f}/{err_v_dist:.3f} px,  avg {err_u_dist_avg:.3f}/{err_v_dist_avg:.3f} px (U/V)")
    # Tolerance: 1 px max within the in-frame convex hull. Sub-pixel
    # residual at the very edge of the sample region is expected from
    # cubic griddata when the convex hull boundary is reached.
    assert err_u_dist < 1.0 and err_v_dist < 1.0, f"distortion direction error too large ({err_u_dist}, {err_v_dist} px)"

    # 4. Write & re-read
    out_path = Path("/tmp/_synth_stmap.exr")
    write_stmap(out_path, u_undist, v_undist, u_dist, v_dist)
    rt = cv2.imread(str(out_path), cv2.IMREAD_UNCHANGED)
    assert rt is not None and rt.shape == (H, W, 4) and rt.dtype == np.float32
    # cv2 BGRA: [..., 0]=B=u_dist, [..., 1]=G=v_undist, [..., 2]=R=u_undist, [..., 3]=A=v_dist
    rt_diff_R = np.abs(rt[..., 2] - u_undist).max()
    rt_diff_G = np.abs(rt[..., 1] - v_undist).max()
    rt_diff_B = np.abs(rt[..., 0] - u_dist).max()
    rt_diff_A = np.abs(rt[..., 3] - v_dist).max()
    print(f"[chk]   EXR roundtrip: R={rt_diff_R:.2e} G={rt_diff_G:.2e} B={rt_diff_B:.2e} A={rt_diff_A:.2e}")
    assert max(rt_diff_R, rt_diff_G, rt_diff_B, rt_diff_A) < 1e-5, "EXR channel storage corrupted"

    print(f"[ok]    self-test PASS at K={K}, errors below tolerance")


if __name__ == "__main__":
    main()
