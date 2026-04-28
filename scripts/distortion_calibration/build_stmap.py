"""Build UE-compatible 4-channel STMap EXR from a Disguise-rendered UV probe.

Pipeline:
  1. Read disguise_uvprobe.exr (3-channel float, RGB; cv2 BGR storage).
     Each pixel (px, py) at distorted output position carries
       R = undistorted U   (where in the LED source this distorted pixel sees from)
       G = undistorted V
       B = 0
  2. The R/G channels ARE the UE undistortion direction (UE reads RG by default).
  3. The distortion direction is built by inverse-interpolating the
     (undistorted_uv -> distorted_uv) sample set onto a uniform undistorted grid.
  4. Pack into 4-channel BGRA EXR:
       cv2 storage [B, G, R, A] = [distortion_U, undistortion_V, undistortion_U, distortion_V]
     UE shader reads R/G/B/A by name -> undistortion (RG) + distortion (BA).
  5. Default FCalibratedMapFormat (PixelOrigin=TopLeft, UndistortionChannels=RG,
     DistortionChannels=BA) consumes this layout natively.

Usage:
  .venv/bin/python build_stmap.py --input disguise_uvprobe.exr [--output stmap.exr]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np
from scipy.interpolate import griddata


def read_uvprobe(path: Path) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Return (undistortion_u, undistortion_v, W, H), all float32."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.dtype != np.float32:
        raise ValueError(f"{path}: dtype {img.dtype}, need float32 EXR")
    if img.ndim != 3 or img.shape[2] < 3:
        raise ValueError(f"{path}: shape {img.shape}, need (H, W, 3+)")
    H, W = img.shape[:2]
    # cv2 BGR storage: [..., 0]=B, [..., 1]=G, [..., 2]=R
    u_undist = img[..., 2].astype(np.float32)  # R = undistorted U
    v_undist = img[..., 1].astype(np.float32)  # G = undistorted V
    return u_undist, v_undist, W, H


def build_distortion_uv(
    u_undist: np.ndarray,
    v_undist: np.ndarray,
    W: int,
    H: int,
    method: str = "cubic",
) -> tuple[np.ndarray, np.ndarray]:
    """Invert (distorted -> undistorted) sample set onto uniform undistorted grid."""
    # Forward sample set
    xs = (np.arange(W, dtype=np.float32) + 0.5) / W
    ys = (np.arange(H, dtype=np.float32) + 0.5) / H
    Xd = np.broadcast_to(xs[None, :], (H, W)).reshape(-1)  # distorted U at each pixel
    Yd = np.broadcast_to(ys[:, None], (H, W)).reshape(-1)  # distorted V
    Ud = u_undist.reshape(-1)                              # undistorted U at each pixel
    Vd = v_undist.reshape(-1)                              # undistorted V

    # Filter NaN/out-of-range samples (edge clipping in heavy distortion)
    valid = (
        np.isfinite(Ud) & np.isfinite(Vd) &
        (Ud >= 0.0) & (Ud <= 1.0) & (Vd >= 0.0) & (Vd <= 1.0)
    )
    if valid.sum() < 100:
        raise RuntimeError(f"only {valid.sum()} valid samples — input EXR likely not a UV probe")

    src_pts = np.stack([Ud[valid], Vd[valid]], axis=-1)
    tgt_xs = Xd[valid]
    tgt_ys = Yd[valid]

    # Query grid: uniform undistorted UV
    qx, qy = np.meshgrid(xs, ys, indexing="xy")  # (H, W)
    q_pts = np.stack([qx.reshape(-1), qy.reshape(-1)], axis=-1)

    # Interpolate distorted U/V at each query point
    u_dist = griddata(src_pts, tgt_xs, q_pts, method=method)
    v_dist = griddata(src_pts, tgt_ys, q_pts, method=method)

    # Fallback for NaN (outside convex hull): use nearest
    nan_u = ~np.isfinite(u_dist)
    nan_v = ~np.isfinite(v_dist)
    if nan_u.any() or nan_v.any():
        u_near = griddata(src_pts, tgt_xs, q_pts, method="nearest")
        v_near = griddata(src_pts, tgt_ys, q_pts, method="nearest")
        u_dist[nan_u] = u_near[nan_u]
        v_dist[nan_v] = v_near[nan_v]

    return u_dist.reshape(H, W).astype(np.float32), v_dist.reshape(H, W).astype(np.float32)


def write_stmap(
    out_path: Path,
    u_undist: np.ndarray,
    v_undist: np.ndarray,
    u_dist: np.ndarray,
    v_dist: np.ndarray,
) -> None:
    H, W = u_undist.shape
    bgra = np.zeros((H, W, 4), dtype=np.float32)
    bgra[..., 0] = u_dist     # B = distortion U
    bgra[..., 1] = v_undist   # G = undistortion V
    bgra[..., 2] = u_undist   # R = undistortion U
    bgra[..., 3] = v_dist     # A = distortion V
    if not cv2.imwrite(str(out_path), bgra):
        raise RuntimeError(f"cv2.imwrite failed for {out_path}")


def sanity_report(
    u_undist: np.ndarray,
    v_undist: np.ndarray,
    u_dist: np.ndarray,
    v_dist: np.ndarray,
    W: int,
    H: int,
) -> str:
    xs = (np.arange(W, dtype=np.float32) + 0.5) / W
    ys = (np.arange(H, dtype=np.float32) + 0.5) / H
    qx, qy = np.meshgrid(xs, ys, indexing="xy")

    # Identity error: how far each map is from being a pass-through
    undist_err = np.hypot(u_undist - qx, v_undist - qy)
    dist_err = np.hypot(u_dist - qx, v_dist - qy)
    # Convert UV error to pixel error (using max(W,H) as ruler)
    px_undist_max = float(undist_err.max() * max(W, H))
    px_dist_max = float(dist_err.max() * max(W, H))
    px_undist_avg = float(undist_err.mean() * max(W, H))
    px_dist_avg = float(dist_err.mean() * max(W, H))

    # Roundtrip: undistort then distort should ≈ identity
    # u_dist sampled at undistorted grid -> should equal what u_undist would produce
    # if we run undistort(distort(uniform_uv)) ≈ uniform_uv. Hard to check directly
    # without re-sampling; report static identity errors instead.

    return (
        f"  undistortion vs identity: avg {px_undist_avg:7.3f} px,  max {px_undist_max:7.3f} px\n"
        f"  distortion   vs identity: avg {px_dist_avg:7.3f} px,  max {px_dist_max:7.3f} px"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="disguise rendered uv-probe EXR")
    ap.add_argument("--output", default=None, help="output 4-channel STMap EXR (default: stmap_<input_basename>.exr)")
    ap.add_argument("--method", default="cubic", choices=["cubic", "linear"], help="inverse interpolation method")
    args = ap.parse_args()

    in_path = Path(args.input).resolve()
    out_path = Path(args.output).resolve() if args.output else in_path.parent / f"stmap_{in_path.stem}.exr"

    print(f"[in]  {in_path}")
    u_undist, v_undist, W, H = read_uvprobe(in_path)
    print(f"      {W}x{H} float32, R range [{u_undist.min():.4f}, {u_undist.max():.4f}], G range [{v_undist.min():.4f}, {v_undist.max():.4f}]")

    print(f"[inv] inverse-interpolating distortion direction (method={args.method})...")
    u_dist, v_dist = build_distortion_uv(u_undist, v_undist, W, H, method=args.method)

    write_stmap(out_path, u_undist, v_undist, u_dist, v_dist)
    print(f"[out] {out_path}")

    print("[sanity]")
    print(sanity_report(u_undist, v_undist, u_dist, v_dist, W, H))


if __name__ == "__main__":
    main()
