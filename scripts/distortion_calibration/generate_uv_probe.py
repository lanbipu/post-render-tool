"""Generate the identity-UV probe image for path B (STMap direct solve).

Outputs:
  - uv_probe_1920x1080.exr   32-bit float, 3-channel
                             R = (x + 0.5) / W   pixel-center U coord, [0,1]
                             G = (y + 0.5) / H   pixel-center V coord, [0,1]
                             B = 0
  - uv_probe_truth.npz       sanity metadata + 4-corner expected values

Pipeline role:
  1. User puts uv_probe.exr onto the LED surface in Disguise (identity mapping)
  2. User renders transmission frame with production K + CenterShift
  3. Output EXR ~= distortion STMap directly (per-pixel displacement)
  4. Mac side reads it back, optionally builds undistortion via inverse
     interpolation, then writes both to UE LensFile.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np

W, H = 1920, 1080
OUT_DIR = Path(__file__).resolve().parent
OUT_EXR = OUT_DIR / "uv_probe_1920x1080.exr"
OUT_NPZ = OUT_DIR / "uv_probe_truth.npz"


def build_probe() -> np.ndarray:
    xs = (np.arange(W, dtype=np.float32) + 0.5) / W
    ys = (np.arange(H, dtype=np.float32) + 0.5) / H
    u = np.broadcast_to(xs[None, :], (H, W)).astype(np.float32)
    v = np.broadcast_to(ys[:, None], (H, W)).astype(np.float32)
    b = np.zeros((H, W), dtype=np.float32)
    return np.stack([b, v, u], axis=-1)


def main() -> None:
    img = build_probe()

    if not cv2.imwrite(str(OUT_EXR), img):
        raise RuntimeError(f"cv2.imwrite failed for {OUT_EXR}")

    rt = cv2.imread(str(OUT_EXR), cv2.IMREAD_UNCHANGED)
    if rt is None or rt.dtype != np.float32 or rt.shape != (H, W, 3):
        raise RuntimeError(f"EXR roundtrip failed: dtype={rt.dtype if rt is not None else None}, shape={rt.shape if rt is not None else None}")

    diff = np.abs(rt - img).max()
    if diff > 1e-6:
        raise RuntimeError(f"EXR roundtrip max-diff {diff} exceeds 1e-6")

    # 4-corner expected (cv2 BGR order)
    expected = {
        "px_0_0":           tuple(img[0, 0].tolist()),
        "px_W-1_0":         tuple(img[0, W - 1].tolist()),
        "px_0_H-1":         tuple(img[H - 1, 0].tolist()),
        "px_W-1_H-1":       tuple(img[H - 1, W - 1].tolist()),
        "px_center":        tuple(img[H // 2, W // 2].tolist()),
    }

    np.savez(
        OUT_NPZ,
        width=W,
        height=H,
        channel_layout="BGR (cv2 native); R=U=(x+0.5)/W, G=V=(y+0.5)/H, B=0",
        u_step=1.0 / W,
        v_step=1.0 / H,
        corners=expected,
    )

    print(f"[ok] wrote {OUT_EXR}")
    print(f"[ok] wrote {OUT_NPZ}")
    print(f"[verify] roundtrip max-diff = {diff:.2e}")
    for name, bgr in expected.items():
        b_, g_, r_ = bgr
        print(f"        {name:14s}  R={r_:.6f} G={g_:.6f} B={b_:.6f}")


if __name__ == "__main__":
    main()
