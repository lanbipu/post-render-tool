"""Shared EXR I/O + UV-probe helpers for the Path A pipeline.

Centralizes the OPENCV_IO_ENABLE_OPENEXR env-set, dtype/shape validation,
and identity-grid construction so the three Path A scripts (analyze_renders
+ both self-tests) don't carry redundant boilerplate.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
PROBE_EXR = HERE / "uv_probe_1920x1080.exr"
PROBE_TRUTH_NPZ = HERE / "uv_probe_truth.npz"


def load_probe_meta() -> tuple[int, int]:
    truth = np.load(PROBE_TRUTH_NPZ, allow_pickle=True)
    return int(truth["width"]), int(truth["height"])


def read_uvprobe_exr(
    path: Path, dtype: np.dtype = np.float64,
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (R, G) channels of a UV-probe EXR cast to `dtype`.

    cv2 BGR storage: img[..., 0]=B, [..., 1]=G, [..., 2]=R.
    """
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"cannot read EXR: {path}")
    if img.dtype != np.float32:
        raise RuntimeError(
            f"{path}: dtype {img.dtype}, need float32 EXR. "
            f"PNG / 16-bit half cause >0.5 px quantization error."
        )
    if img.ndim != 3 or img.shape[2] < 3:
        raise RuntimeError(f"{path}: shape {img.shape}, need (H, W, 3+)")
    return img[..., 2].astype(dtype), img[..., 1].astype(dtype)


def build_identity_uv_grid(
    W: int, H: int, dtype: np.dtype = np.float64,
) -> tuple[np.ndarray, np.ndarray]:
    """Identity-probe truth: u = (x+0.5)/W, v = (y+0.5)/H, shape (H, W) each."""
    xs = (np.arange(W, dtype=dtype) + 0.5) / W
    ys = (np.arange(H, dtype=dtype) + 0.5) / H
    u_truth = np.broadcast_to(xs[None, :], (H, W))
    v_truth = np.broadcast_to(ys[:, None], (H, W))
    return u_truth, v_truth
