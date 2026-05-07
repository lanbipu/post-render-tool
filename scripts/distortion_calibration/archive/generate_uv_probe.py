"""Generate identity-UV probe image(s) for system identification.

Outputs:
  - uv_probe_<W>x<H>.exr      32-bit float, 3-channel
                              R = (x + 0.5) / W   pixel-center U coord, [0,1]
                              G = (y + 0.5) / H   pixel-center V coord, [0,1]
                              B = 0
  - uv_probe_truth_<W>x<H>.npz   sanity metadata + 4-corner expected values

Pipeline role:
  1. User puts uv_probe.exr onto the LED surface in Disguise (identity mapping)
  2. User renders transmission frame with production K + CenterShift
  3. Output EXR ~= distortion STMap directly (per-pixel displacement)
  4. Mac side reads it back, optionally builds undistortion via inverse
     interpolation, then writes both to UE LensFile.

Usage:
  python generate_uv_probe.py                # default 1920x1080 + 3840x2160
  python generate_uv_probe.py --resolution 1920x1080
  python generate_uv_probe.py --resolution 3840x2160
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np


OUT_DIR = Path(__file__).resolve().parent
DEFAULT_RESOLUTIONS = [(1920, 1080), (3840, 2160)]


def build_probe(W: int, H: int) -> np.ndarray:
    xs = (np.arange(W, dtype=np.float32) + 0.5) / W
    ys = (np.arange(H, dtype=np.float32) + 0.5) / H
    u = np.broadcast_to(xs[None, :], (H, W)).astype(np.float32)
    v = np.broadcast_to(ys[:, None], (H, W)).astype(np.float32)
    b = np.zeros((H, W), dtype=np.float32)
    return np.stack([b, v, u], axis=-1)


def write_one(W: int, H: int, camera_w: int | None = None, camera_h: int | None = None) -> None:
    img = build_probe(W, H)

    cam_w = camera_w if camera_w is not None else W
    cam_h = camera_h if camera_h is not None else H
    over_x = W / cam_w
    over_y = H / cam_h

    out_exr = OUT_DIR / f"uv_probe_{W}x{H}.exr"
    out_npz = OUT_DIR / f"uv_probe_truth_{W}x{H}.npz"

    if not cv2.imwrite(str(out_exr), img):
        raise RuntimeError(f"cv2.imwrite failed for {out_exr}")

    rt = cv2.imread(str(out_exr), cv2.IMREAD_UNCHANGED)
    if rt is None or rt.dtype != np.float32 or rt.shape != (H, W, 3):
        raise RuntimeError(
            f"EXR roundtrip failed: dtype={rt.dtype if rt is not None else None}, "
            f"shape={rt.shape if rt is not None else None}"
        )

    diff = float(np.abs(rt - img).max())
    if diff > 1e-6:
        raise RuntimeError(f"EXR roundtrip max-diff {diff} exceeds 1e-6")

    # 4-corner + center expected (cv2 BGR order)
    expected = {
        "px_0_0":     tuple(img[0, 0].tolist()),
        "px_W-1_0":   tuple(img[0, W - 1].tolist()),
        "px_0_H-1":   tuple(img[H - 1, 0].tolist()),
        "px_W-1_H-1": tuple(img[H - 1, W - 1].tolist()),
        "px_center":  tuple(img[H // 2, W // 2].tolist()),
    }

    np.savez(
        out_npz,
        width=W,
        height=H,
        camera_width=cam_w,
        camera_height=cam_h,
        channel_layout="BGR (cv2 native); R=U=(x+0.5)/W, G=V=(y+0.5)/H, B=0",
        u_step=1.0 / W,
        v_step=1.0 / H,
        corners=expected,
    )

    print(f"[ok] wrote {out_exr}  ({out_exr.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"[ok] wrote {out_npz}")
    print(f"[verify] roundtrip max-diff = {diff:.2e}")
    print(f"[meta] probe={W}x{H}  camera={cam_w}x{cam_h}  over-scan={over_x:.4f}x / {over_y:.4f}y")
    for name, bgr in expected.items():
        b_, g_, r_ = bgr
        print(f"        {name:14s}  R={r_:.6f} G={g_:.6f} B={b_:.6f}")
    print()


def parse_resolution(spec: str) -> tuple[int, int]:
    parts = spec.lower().replace("×", "x").split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"resolution must be WxH, got {spec!r}")
    return int(parts[0]), int(parts[1])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--resolution", "-r",
        type=parse_resolution,
        action="append",
        help="probe resolution WxH (e.g., 3840x2160). May be specified multiple times. "
             "Default generates both 1920x1080 and 3840x2160 if omitted.",
    )
    ap.add_argument(
        "--camera-resolution",
        type=parse_resolution,
        default=None,
        help="Camera frame resolution as WxH (e.g., '3840x2160'). 默认等于 --resolution "
             "(no over-scan). Over-scan factor 隐式由 probe_W / camera_W 推出. "
             "若提供, 同一个 camera 尺寸应用到所有 --resolution 条目.",
    )
    args = ap.parse_args()

    resolutions = args.resolution or DEFAULT_RESOLUTIONS
    cam_dims = args.camera_resolution  # tuple or None
    for W, H in resolutions:
        if cam_dims is None:
            write_one(W, H)
        else:
            write_one(W, H, cam_dims[0], cam_dims[1])


if __name__ == "__main__":
    main()
