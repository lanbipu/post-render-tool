"""Verify M6 distortion-coefficient mapping from CSV K1/K2/K3 to UE LensFile,
including the HW-norm → fx-norm conversion required for UE shader.

M6 fit (Path A system identification, commit 5311d4f) in half-width norm:
    r' = r_HW · (1 + a·csv_K1·r_HW² + b·csv_K1²·r_HW⁴ + c·csv_K1³·r_HW⁶)
    a = -0.2507, b = +0.2097, c = -0.1931

UE LensFile applies polynomial in focal-length norm (r_fx = pixel/fx_pixels).
Conversion factor for K_k coefficient: (2·fx_uv)^(2k). For 30mm-on-35mm-sensor
the factors are roughly 3x, 9x, 27x.
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


def _expected_ue(csv_k1: float, csv_k2: float, csv_k3: float, fx: float):
    """M6 + sign-flip mapping with HW→fx normalization scaling."""
    fx_scale = 2.0 * fx
    fx2 = fx_scale * fx_scale
    fx4 = fx2 * fx2
    fx6 = fx4 * fx2
    return (
        M6_A * csv_k1 * fx2,
        M6_B * csv_k1 ** 2 * fx4 - csv_k2,
        M6_C * csv_k1 ** 3 * fx6 - csv_k3,
    )


class TestM6Mapping(unittest.TestCase):
    def _check(self, frame, exp_k1, exp_k2, exp_k3, places=8):
        nd = compute_normalized_distortion(frame)
        self.assertAlmostEqual(nd["k1"], exp_k1, places=places)
        self.assertAlmostEqual(nd["k2"], exp_k2, places=places)
        self.assertAlmostEqual(nd["k3"], exp_k3, places=places)

    def test_zero_input_zero_output(self):
        self._check(_StubFrame(), 0.0, 0.0, 0.0)

    def test_csv_k1_positive_sweep_value(self):
        frame = _StubFrame(k1=+0.5)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        e1, e2, e3 = _expected_ue(+0.5, 0.0, 0.0, fx)
        # For default stub fx ≈ 0.857: scaling roughly 2.94, 8.64, 25.38
        # ue_K1 ≈ -0.368, ue_K2 ≈ +0.453, ue_K3 ≈ -0.613
        self._check(frame, e1, e2, e3)

    def test_csv_k1_negative_sweep_value(self):
        """K2 always positive (K1²); K3 sign flips with K1 (K1³)."""
        frame = _StubFrame(k1=-0.5)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        e1, e2, e3 = _expected_ue(-0.5, 0.0, 0.0, fx)
        nd = compute_normalized_distortion(frame)
        self.assertAlmostEqual(nd["k1"], e1, places=8)
        self.assertGreater(nd["k1"], 0.0, "ue_K1 must flip sign with csv_K1")
        self.assertAlmostEqual(nd["k2"], e2, places=8)
        self.assertGreater(nd["k2"], 0.0, "ue_K2 must stay positive (K1²)")
        self.assertAlmostEqual(nd["k3"], e3, places=8)
        self.assertGreater(nd["k3"], 0.0, "ue_K3 must flip with K1 (K1³)")

    def test_csv_k2_k3_passthrough_sign_flip_when_k1_zero(self):
        self._check(
            _StubFrame(k1=0.0, k2=-0.004, k3=+0.011),
            exp_k1=0.0,
            exp_k2=+0.004,
            exp_k3=-0.011,
        )

    def test_production_csv_values(self):
        """Production CSV (K1≈3e-4) — M6 K1²/K1³ contributions are sub-1e-7
        even after fx scaling. Behaviour ≈ legacy sign-flip."""
        frame = _StubFrame(k1=0.000286, k2=-0.003953, k3=+0.011302)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        e1, e2, e3 = _expected_ue(0.000286, -0.003953, +0.011302, fx)
        self._check(frame, e1, e2, e3)

    def test_combined_csv_k1_and_k2_k3(self):
        frame = _StubFrame(k1=+0.3, k2=+0.05, k3=-0.02)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        e1, e2, e3 = _expected_ue(+0.3, +0.05, -0.02, fx)
        self._check(frame, e1, e2, e3)

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

    def test_fx_scaling_factor_at_typical_focal(self):
        """Check that for fx≈0.866 (30.302mm on 35mm sensor) the scaling
        factor on K1 is about 3x — sanity-check the unit conversion."""
        frame = _StubFrame(k1=+1.0, focal_length_mm=30.302, sensor_width_mm=35.0)
        nd = compute_normalized_distortion(frame)
        # M6_A * 1.0 * (2*0.86577)² = -0.2507 * 2.998 ≈ -0.7517
        fx = 30.302 / 35.0
        expected_k1 = M6_A * 1.0 * (2.0 * fx) ** 2
        self.assertAlmostEqual(nd["k1"], expected_k1, places=8)
        self.assertAlmostEqual(expected_k1, -0.751654, places=4)


if __name__ == "__main__":
    unittest.main()
