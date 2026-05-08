"""量化 Disguise reference EXR 跟 UE EXR 之间的 Y 方向 shift。

策略: Phase correlation (FFT-based subpixel translation estimation, 来自 OpenCV)
应用在画面中心 ROI (避开边缘 K3 弯曲), 拿到 (dx, dy) 像素位移。

跟 distortion_math 公式预测的 vertical shift 对比, 判断 centerShift Y 公式是否正确。

Usage:
    python measure_vertical_shift.py \\
        --reference ref.exr --ue-render ue.exr \\
        --predict-shift-px 10.5
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np


def _read_linear_gray(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit(f"failed: {path}")
    if img.ndim == 3:
        if img.shape[2] >= 3:
            img = img[:, :, :3]
            gray = (0.0722 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.2126 * img[:, :, 2]).astype(np.float32)
        else:
            gray = img[:, :, 0].astype(np.float32)
    else:
        gray = img.astype(np.float32)
    return gray


def _measure_shift(ref: np.ndarray, ue: np.ndarray, *, roi_box: tuple) -> tuple:
    x0, y0, x1, y1 = roi_box
    ref_roi = ref[y0:y1, x0:x1]
    ue_roi = ue[y0:y1, x0:x1]

    # phaseCorrelate 需要 0 均值 + Hann window
    h, w = ref_roi.shape
    window = cv2.createHanningWindow((w, h), cv2.CV_32F)
    (dx, dy), _ = cv2.phaseCorrelate(ref_roi - ref_roi.mean(), ue_roi - ue_roi.mean(), window)
    return dx, dy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--ue-render", type=Path, required=True)
    parser.add_argument("--predict-shift-px", type=float, default=None,
                        help="公式预测的 Y 方向像素 shift (UE 相对 ref 的方向)")
    args = parser.parse_args()

    ref = _read_linear_gray(args.reference)
    ue = _read_linear_gray(args.ue_render)
    if ref.shape != ue.shape:
        raise SystemExit(f"shape mismatch: ref={ref.shape} ue={ue.shape}")
    h, w = ref.shape

    # 测多个 ROI: 中心 / 上半部 / 下半部, 看 shift 是否一致
    rois = {
        "full":           (0, 0, w, h),
        "center_512":     (w // 2 - 256, h // 2 - 256, w // 2 + 256, h // 2 + 256),
        "upper_half":     (0, h // 8, w, h // 2),
        "lower_half":     (0, h // 2, w, h - h // 8),
        "led_wall_only":  (w // 4, h // 16, w * 3 // 4, h // 2 - 32),
        "ground_only":    (w // 4, h // 2 + 32, w * 3 // 4, h - h // 16),
    }

    print(f"Image shape: {h} x {w}")
    print(f"{'ROI':<20s} {'dx_px':>10s} {'dy_px':>10s}")
    print("-" * 44)
    dy_list = []
    for name, box in rois.items():
        dx, dy = _measure_shift(ref, ue, roi_box=box)
        dy_list.append(dy)
        print(f"{name:<20s} {dx:>10.3f} {dy:>10.3f}")

    if args.predict_shift_px is not None:
        print()
        print(f"Predicted Y shift (UE − ref): {args.predict_shift_px:+.3f} px")
        print(f"Median measured Y shift:      {np.median(dy_list):+.3f} px")
        print(f"Diff (measured − predicted):  {np.median(dy_list) - args.predict_shift_px:+.3f} px")


if __name__ == "__main__":
    main()
