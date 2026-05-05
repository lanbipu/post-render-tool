"""Self-test for custom post-process gate evaluation helpers."""
from __future__ import annotations

import math

import numpy as np

from evaluate_center_shift_sweep import (
    center_uv_from_shift,
    expected_shift_pixels,
    parse_center_shift_value,
)
from pathlib import Path

from evaluate_k_sweep_custom_formula import (
    format_stats,
    normalization_factor,
    parse_axis_value,
    resolve_anchor_for_axis,
    source_norm_from_official_formula,
)


def test_parse_axis_value() -> None:
    assert parse_axis_value("disguise_K2_p0p3") == (2, 0.3)
    assert parse_axis_value("disguise_K3_n0p5") == (3, -0.5)
    assert parse_axis_value("disguise_K2_zero") == (2, 0.0)


def test_parse_axis_value_includes_k1() -> None:
    assert parse_axis_value("disguise_K1_p0p10") == (1, 0.10)
    assert parse_axis_value("disguise_K1_n0p30") == (1, -0.30)
    assert parse_axis_value("disguise_K1_zero") == (1, 0.0)


def test_official_formula_uses_k2_and_k3_orders() -> None:
    out_x = np.array([0.5])
    out_y = np.array([0.0])

    sx, sy = source_norm_from_official_formula(out_x, out_y, k1=0.0, k2=0.5, k3=0.0)
    assert np.allclose(sx, [0.515625])
    assert np.allclose(sy, [0.0])

    sx, sy = source_norm_from_official_formula(out_x, out_y, k1=0.0, k2=0.0, k3=0.5)
    assert np.allclose(sx, [0.50390625])
    assert np.allclose(sy, [0.0])


def test_format_stats_reports_p95() -> None:
    stats = format_stats(np.array([0.0, 1.0, 2.0, 3.0]))
    assert stats["n"] == 4
    assert math.isclose(stats["p95_px"], 2.85)
    assert math.isclose(stats["max_px"], 3.0)


def test_parse_center_shift_value() -> None:
    assert parse_center_shift_value("disguise_K1p3_centerShiftX_n0p10") == ("x", -0.10)
    assert parse_center_shift_value("disguise_K1p3_centerShiftY_p0p05") == ("y", 0.05)
    assert parse_center_shift_value("disguise_K1p3_centerShift_zero") == ("zero", 0.0)
    assert parse_center_shift_value("disguise_K1p3_centerShiftY_zero") == ("zero", 0.0)


def test_center_uv_and_expected_pixels() -> None:
    center_u, center_v = center_uv_from_shift(
        shift_x_mm=0.35,
        shift_y_mm=-0.175,
        sensor_width_mm=35.0,
        aspect_ratio=16.0 / 9.0,
    )
    assert math.isclose(center_u, 0.51)
    assert math.isclose(center_v, 0.5 - (0.175 / (35.0 / (16.0 / 9.0))))

    dx, dy = expected_shift_pixels(
        axis="x",
        shift_mm=0.35,
        sensor_width_mm=35.0,
        aspect_ratio=16.0 / 9.0,
        width_px=3840,
        height_px=2160,
    )
    assert math.isclose(dx, 38.4)
    assert math.isclose(dy, 0.0)


def test_resolve_anchor_for_axis_picks_correct_zero() -> None:
    base = Path("/some/validation_root")
    assert resolve_anchor_for_axis(1, base) == base / "k1_sweep" / "disguise_K1_zero.exr"
    assert resolve_anchor_for_axis(2, base) == base / "custom_pp_gate_inputs" / "k2_k3_sweep" / "disguise_K2_zero.exr"
    assert resolve_anchor_for_axis(3, base) == base / "custom_pp_gate_inputs" / "k2_k3_sweep" / "disguise_K2_zero.exr"


def test_normalization_factor_full_width_vs_half_width() -> None:
    from evaluate_k_sweep_custom_formula import normalization_factor
    width = 3840
    assert normalization_factor("full-width", width) == 3840.0
    assert normalization_factor("half-width", width) == 1920.0


def main() -> None:
    test_parse_axis_value()
    test_parse_axis_value_includes_k1()
    test_official_formula_uses_k2_and_k3_orders()
    test_format_stats_reports_p95()
    test_parse_center_shift_value()
    test_center_uv_and_expected_pixels()
    test_resolve_anchor_for_axis_picks_correct_zero()
    test_normalization_factor_full_width_vs_half_width()
    print("self-test PASS")


if __name__ == "__main__":
    main()
