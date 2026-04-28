"""Verify M6 distortion-coefficient mapping from CSV K1/K2/K3 to UE.

M6 fit (Path A system identification, commit 5311d4f):
    a = -0.2507  (csv_K1 → ue_K1)
    b = +0.2097  (csv_K1² → ue_K2)
    c = -0.1931  (csv_K1³ → ue_K3)

Plus pass-through sign-flip on csv_K2 / csv_K3 (TODO: validate via K2/K3 sweeps).
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from post_render_tool.distortion_math import (
    M6_A, M6_B, M6_C, compute_normalized_distortion,
)


@dataclass
class _StubFrame:
    k1: float = 0.0
    k2: float = 0.0
    k3: float = 0.0
    center_shift_x_mm: float = 0.0
    center_shift_y_mm: float = 0.0
    sensor_width_mm: float = 35.0
    focal_length_mm: float = 30.0
    aspect_ratio: float = 1.7778


class TestM6Mapping(unittest.TestCase):
    def _check(self, frame, exp_k1, exp_k2, exp_k3, places=6):
        nd = compute_normalized_distortion(frame)
        self.assertAlmostEqual(nd["k1"], exp_k1, places=places)
        self.assertAlmostEqual(nd["k2"], exp_k2, places=places)
        self.assertAlmostEqual(nd["k3"], exp_k3, places=places)

    def test_zero_input_zero_output(self):
        self._check(_StubFrame(), 0.0, 0.0, 0.0)

    def test_csv_k1_positive_sweep_value(self):
        self._check(
            _StubFrame(k1=+0.5),
            exp_k1=M6_A * 0.5,           # -0.12535
            exp_k2=M6_B * 0.5 ** 2,      # +0.052425
            exp_k3=M6_C * 0.5 ** 3,      # -0.024138
        )

    def test_csv_k1_negative_sweep_value(self):
        """K2 always positive (K1²); K3 sign flips with K1 (K1³)."""
        self._check(
            _StubFrame(k1=-0.5),
            exp_k1=-M6_A * 0.5,          # +0.12535
            exp_k2=M6_B * 0.5 ** 2,      # +0.052425  (unchanged: K1²)
            exp_k3=-M6_C * 0.5 ** 3,     # +0.024138  (sign flips: K1³)
        )

    def test_csv_k2_k3_passthrough_sign_flip_when_k1_zero(self):
        """When CSV K1=0 the M6 K1²/K1³ contributions vanish; K2/K3 reduce
        to the legacy sign-flip behaviour."""
        self._check(
            _StubFrame(k1=0.0, k2=-0.004, k3=+0.011),
            exp_k1=0.0,
            exp_k2=+0.004,
            exp_k3=-0.011,
        )

    def test_production_csv_values(self):
        """Production CSV (K1≈3e-4) — M6 K1²/K1³ contributions are sub-1e-7,
        so behaviour is essentially the legacy sign-flip."""
        nd = compute_normalized_distortion(
            _StubFrame(k1=0.000286, k2=-0.003953, k3=+0.011302)
        )
        self.assertAlmostEqual(nd["k1"], M6_A * 0.000286, places=8)
        self.assertAlmostEqual(nd["k2"], +0.003953 + M6_B * 0.000286 ** 2, places=8)
        self.assertAlmostEqual(nd["k3"], -0.011302 + M6_C * 0.000286 ** 3, places=10)

    def test_combined_csv_k1_and_k2_k3(self):
        """M6 K1 contributions + legacy K2/K3 sign-flip stack additively."""
        nd = compute_normalized_distortion(
            _StubFrame(k1=+0.3, k2=+0.05, k3=-0.02)
        )
        self.assertAlmostEqual(nd["k1"], M6_A * 0.3, places=6)
        self.assertAlmostEqual(nd["k2"], M6_B * 0.09 - 0.05, places=6)
        self.assertAlmostEqual(nd["k3"], M6_C * 0.027 - (-0.02), places=6)

    def test_principal_point_unchanged_by_m6_change(self):
        frame = _StubFrame(
            k1=0.5, k2=0.0, k3=0.0,
            center_shift_x_mm=2.0, center_shift_y_mm=1.0,
            sensor_width_mm=35.0, focal_length_mm=30.0, aspect_ratio=1.7778,
        )
        nd = compute_normalized_distortion(frame)
        self.assertAlmostEqual(nd["fx"], 30.0 / 35.0, places=6)
        self.assertAlmostEqual(nd["cx"], 0.5 + 2.0 / 35.0, places=6)
        self.assertAlmostEqual(nd["cy"], 0.5 + 1.0 / (35.0 / 1.7778), places=6)


if __name__ == "__main__":
    unittest.main()
