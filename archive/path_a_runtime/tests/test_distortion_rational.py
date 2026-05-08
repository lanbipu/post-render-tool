"""Verify M_RAT6 rational distortion-coefficient mapping from CSV K1/K2/K3 to UE.

M_RAT6 fit (commit 8164938, Path A K1 sweep):
    r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶)
        / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶)

Maps to UE BrownConradyUDLensModel (with HW-norm → fx-norm scaling):
    K1 = a·csv_K · (2·fx)²    K4 = d·csv_K · (2·fx)²
    K2 = b·csv_K² · (2·fx)⁴   K5 = e·csv_K² · (2·fx)⁴
    K3 = c·csv_K³ · (2·fx)⁶   K6 = f·csv_K³ · (2·fx)⁶
plus CSV K2/K3 sign-flip pass-through on UE K2/K3 (legacy, TODO: K2/K3 sweep).
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from post_render_tool.distortion_math import (
    M_RAT6_A, M_RAT6_B, M_RAT6_C, M_RAT6_D, M_RAT6_E, M_RAT6_F,
    compute_normalized_distortion,
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
    fx_scale = 2.0 * fx
    fx2 = fx_scale ** 2
    fx4 = fx2 ** 2
    fx6 = fx4 * fx2
    return {
        "k1": M_RAT6_A * csv_k1 * fx2,
        "k2": M_RAT6_B * csv_k1**2 * fx4 - csv_k2,
        "k3": M_RAT6_C * csv_k1**3 * fx6 - csv_k3,
        "k4": M_RAT6_D * csv_k1 * fx2,
        "k5": M_RAT6_E * csv_k1**2 * fx4,
        "k6": M_RAT6_F * csv_k1**3 * fx6,
    }


class TestRationalMapping(unittest.TestCase):
    PLACES = 8

    def _check(self, frame, expected):
        nd = compute_normalized_distortion(frame)
        for key, exp in expected.items():
            self.assertAlmostEqual(nd[key], exp, places=self.PLACES,
                                   msg=f"{key}: got {nd[key]} expected {exp}")

    def test_zero_input_zero_output(self):
        nd = compute_normalized_distortion(_StubFrame())
        for key in ("k1", "k2", "k3", "k4", "k5", "k6", "p1", "p2"):
            self.assertEqual(nd[key], 0.0)

    def test_csv_k1_positive_sweep(self):
        frame = _StubFrame(k1=+0.5)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        self._check(frame, _expected_ue(+0.5, 0.0, 0.0, fx))

    def test_csv_k1_negative_sweep(self):
        frame = _StubFrame(k1=-0.5)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        nd = compute_normalized_distortion(frame)
        # M_RAT6_A < 0 且 M_RAT6_D < 0, 所以 ue_K1/K4 必反向于 csv_K1.
        # K2, K5 是 csv_K1² 项 (永远跟 sign-of-coef 同号, 不随 csv_K1 翻).
        self.assertLess(nd["k1"] * (-0.5), 0, "ue_K1 must oppose csv_K1 sign (M_RAT6_A < 0)")
        self.assertLess(nd["k4"] * (-0.5), 0, "ue_K4 must oppose csv_K1 sign (M_RAT6_D < 0)")
        self._check(frame, _expected_ue(-0.5, 0.0, 0.0, fx))

    def test_csv_k2_k3_passthrough_when_k1_zero(self):
        """csv_K1=0 时所有 M_RAT6 项贡献为 0, K2/K3 退回 legacy sign-flip."""
        nd = compute_normalized_distortion(
            _StubFrame(k1=0.0, k2=-0.004, k3=+0.011)
        )
        self.assertEqual(nd["k1"], 0.0)
        self.assertAlmostEqual(nd["k2"], +0.004, places=8)
        self.assertAlmostEqual(nd["k3"], -0.011, places=8)
        self.assertEqual(nd["k4"], 0.0)
        self.assertEqual(nd["k5"], 0.0)
        self.assertEqual(nd["k6"], 0.0)

    def test_production_csv_values(self):
        """Production CSV (K1≈3e-4): M_RAT6 项贡献 sub-1e-7, 行为 ≈ legacy sign-flip."""
        frame = _StubFrame(k1=0.000286, k2=-0.003953, k3=+0.011302)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        self._check(frame, _expected_ue(0.000286, -0.003953, +0.011302, fx))

    def test_combined_csv_k1_and_k2_k3(self):
        frame = _StubFrame(k1=+0.3, k2=+0.05, k3=-0.02)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        self._check(frame, _expected_ue(+0.3, +0.05, -0.02, fx))

    def test_principal_point_unchanged(self):
        frame = _StubFrame(
            k1=0.5, k2=0.0, k3=0.0,
            center_shift_x_mm=2.0, center_shift_y_mm=1.0,
            sensor_width_mm=35.0, focal_length_mm=30.0, aspect_ratio=1.7778,
        )
        nd = compute_normalized_distortion(frame)
        self.assertAlmostEqual(nd["fx"], 30.0 / 35.0, places=6)
        self.assertAlmostEqual(nd["cx"], 0.5 + 2.0 / 35.0, places=6)

    def test_returns_eight_distortion_coefficients(self):
        nd = compute_normalized_distortion(_StubFrame(k1=+0.5))
        for key in ("k1", "k2", "k3", "k4", "k5", "k6", "p1", "p2"):
            self.assertIn(key, nd, f"missing UE BrownConradyUD coefficient: {key}")


if __name__ == "__main__":
    unittest.main()
