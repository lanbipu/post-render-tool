"""Sanity-check generate_charuco_board.py output.

Loads the rendered ChArUco PNG, runs the same detect_corners pipeline
that analyze_renders.py uses (CharucoDetector + custom cornerSubPix),
and verifies each detected corner against the truth array indexed by ID.
RMS error must be near 0 px on the noise-free reference image.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from analyze_renders import detect_corners, load_truth

HERE = Path(__file__).resolve().parent

board, truth_corners, _ = load_truth()
detector = cv2.aruco.CharucoDetector(board)

result = detect_corners(HERE / "charuco_1920x1080.png", detector)
assert result is not None, "ChArUco detection failed on noise-free reference"
det_ids, det_corners = result

n_total = truth_corners.shape[0]
print(f"detected: {len(det_corners)}/{n_total} corners")
assert len(det_corners) == n_total, "expected all corners detected on clean reference"

truth_xy = truth_corners[det_ids]
errs = np.linalg.norm(det_corners - truth_xy, axis=1)
rms = float(np.sqrt(np.mean(errs ** 2)))
max_err = float(np.max(errs))
median = float(np.median(errs))
print(f"rms vs truth:    {rms:.4f} px")
print(f"median err:      {median:.4f} px")
print(f"max err:         {max_err:.4f} px")
assert rms < 0.05, f"self-test rms too high ({rms:.4f} px) — pipeline drift"
print("self-test PASS")
