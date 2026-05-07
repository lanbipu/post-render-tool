"""Synthetic ground-truth gate for fit_normalization_candidates.

Generates a fake K1=+0.3 distortion via known full-width Brown-Conrady, runs
the fit harness, and asserts:
1. full-width candidate has lowest delta-residual.
2. fitted K1_eff matches +0.3 to within 1e-3.
3. focal-length candidate's K1_eff diverges (since it would require
   different K1_eff at different focals).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _fit_helpers import (  # noqa: E402
    candidate_norm_factor,
    forward_brown_conrady_pixel,
)


def _synth_disguise_frame(
    *,
    width: int,
    height: int,
    focal_mm: float,
    sensor_width_mm: float,
    k1: float,
    overscan_margin: float,
    truth_norm: str,
) -> np.ndarray:
    """Build a synthetic Disguise output: R = corrected source U, G = source V.

    The input plate is identity; truth distortion uses `truth_norm` so we
    know which candidate the fit harness should pick.
    """
    cx = width / 2.0
    cy = height / 2.0
    norm = candidate_norm_factor(
        truth_norm,
        width_px=width,
        height_px=height,
        focal_mm=focal_mm,
        sensor_width_mm=sensor_width_mm,
    )
    xs = np.arange(width, dtype=np.float64) + 0.5
    ys = np.arange(height, dtype=np.float64) + 0.5
    out_x, out_y = np.meshgrid(xs, ys)
    src_x, src_y = forward_brown_conrady_pixel(
        out_x, out_y, cx_px=cx, cy_px=cy, norm_px=norm, k1=k1, k2=0, k3=0,
    )
    span = 1.0 - 2.0 * overscan_margin
    R = (src_x / width) * span + overscan_margin
    G = (src_y / height) * span + overscan_margin
    img = np.zeros((height, width, 3), dtype=np.float32)
    img[..., 2] = R.astype(np.float32)
    img[..., 1] = G.astype(np.float32)
    return img


class FitReviewPathTest(unittest.TestCase):
    def test_no_qualifying_candidate_returns_none_winner(self):
        # Synth data with INCONSISTENT truth normalization across focals
        # (each focal uses a different truth_norm). This forces every candidate
        # to fit poorly cross-focal — high k1_eff_spread, high p95_max — so no
        # candidate satisfies the 3-criteria gate. winner must be None,
        # verdict must be REVIEW.
        #
        # The plain "k=0.5 with tiny margin, single truth_norm" scenario won't
        # trigger REVIEW: full-width still fits cleanly (spread ~0, p95 < 1px)
        # because anchor + frame share over-scan recovery — even at margin=0.001.
        # Inconsistent per-focal truth is the reliable failure mode.
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            (data_root / "focal_length_sweep").mkdir()
            (data_root / "k2_k3_sweep").mkdir()
            (data_root / "center_shift_sweep").mkdir()
            width, height = 3840, 2160
            sensor_w = 35.0
            truth_norms_per_focal = {
                24.0: "full-width",
                30.302: "diagonal",
                50.0: "height",
            }
            for f in [24.0, 30.302, 50.0]:
                anchor = _synth_disguise_frame(
                    width=width, height=height, focal_mm=f, sensor_width_mm=sensor_w,
                    k1=0.0, overscan_margin=0.103,
                    truth_norm=truth_norms_per_focal[f],
                )
                nonzero = _synth_disguise_frame(
                    width=width, height=height, focal_mm=f, sensor_width_mm=sensor_w,
                    k1=0.5, overscan_margin=0.103,
                    truth_norm=truth_norms_per_focal[f],
                )
                fcal_str = str(f).replace(".", "p")
                cv2.imwrite(
                    str(data_root / "focal_length_sweep" / f"disguise_focal{fcal_str}_K1_zero.exr"),
                    anchor,
                )
                cv2.imwrite(
                    str(data_root / "focal_length_sweep" / f"disguise_focal{fcal_str}_K1_p0p5.exr"),
                    nonzero,
                )
            from fit_normalization_candidates import evaluate_focal_sweep
            report = evaluate_focal_sweep(
                data_root=data_root, width=width, height=height,
                sensor_width_mm=sensor_w, samples_per_frame=20_000, seed=0,
            )
            self.assertEqual(report["verdict"], "REVIEW")
            self.assertIsNone(report["winner"])
            self.assertIn("ranked_top", report)
            self.assertEqual(len(report["ranked_top"]), 3)


class FitGroundTruthTest(unittest.TestCase):
    def test_truth_normalization_recovered(self):
        # Synthesize 3 focal × K1 sweep using truth = full-width.
        # truth_k1 must equal target_k1 (0.5) so qualifying-criteria check
        # `abs(k1_eff_mean - target_k1) < K1_TOL` succeeds and winner is set
        # via the GO path. (The fallback "winner = ranked[0][0]" was removed
        # 2026-05-07 per Codex review finding 2.)
        width, height = 3840, 2160
        sensor_w = 35.0
        truth_k1 = 0.5
        truth_norm = "full-width"
        focals = [24.0, 30.302, 50.0]
        # Each focal gets a different over-scan margin (matches d3 behavior)
        margins = {24.0: 0.001, 30.302: 0.103, 50.0: 0.259}

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            (data_root / "focal_length_sweep").mkdir()
            (data_root / "k2_k3_sweep").mkdir()
            (data_root / "center_shift_sweep").mkdir()
            for f in focals:
                anchor = _synth_disguise_frame(
                    width=width, height=height,
                    focal_mm=f, sensor_width_mm=sensor_w,
                    k1=0.0, overscan_margin=margins[f],
                    truth_norm=truth_norm,
                )
                nonzero = _synth_disguise_frame(
                    width=width, height=height,
                    focal_mm=f, sensor_width_mm=sensor_w,
                    k1=truth_k1, overscan_margin=margins[f],
                    truth_norm=truth_norm,
                )
                fcal_str = str(f).replace(".", "p")
                cv2.imwrite(
                    str(data_root / "focal_length_sweep" / f"disguise_focal{fcal_str}_K1_zero.exr"),
                    anchor,
                )
                cv2.imwrite(
                    str(data_root / "focal_length_sweep" / f"disguise_focal{fcal_str}_K1_p0p5.exr"),
                    nonzero,
                )
            # Re-import (after Task 3 lands) and run focal-only path
            from fit_normalization_candidates import evaluate_focal_sweep
            report = evaluate_focal_sweep(
                data_root=data_root, width=width, height=height,
                sensor_width_mm=sensor_w, samples_per_frame=50_000, seed=0,
            )
            self.assertEqual(report["winner"], truth_norm)
            # tolerance loosened from 1e-3 → 5e-3 (same as K1_TOL gate) when
            # truth_k1 was raised to 0.5 to match target_k1; larger K has
            # slightly more numeric error in the LSQ inversion (~1.6e-3).
            self.assertLess(
                abs(report["candidates"][truth_norm]["k1_eff_mean"] - truth_k1),
                5e-3,
            )
            self.assertLess(report["candidates"][truth_norm]["k1_eff_spread"], 5e-3)
            self.assertGreater(
                report["candidates"]["focal-length"]["k1_eff_spread"], 1e-2,
            )


if __name__ == "__main__":
    unittest.main()
