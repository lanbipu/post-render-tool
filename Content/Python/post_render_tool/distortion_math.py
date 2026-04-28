"""Disguise CSV → UE LensFile distortion-coefficient math (Brown-Conrady UD rational).

Pure Python (no ``unreal`` import); UE-side caller is `lens_file_builder.py`.
All unit conversions and the M_RAT6 rational mapping live here so the math
is testable outside UE Editor — same pattern as `distortion_packing.py`.

M_RAT6 mapping (Path A round 1, commit 8164938):

    UV-gradient probe + 11-K-sweep (CSV K1 ∈ {0, ±0.1..±0.5} with K2=K3=0),
    11 candidate fit on 300k pixel samples. M_RAT6 (6-param rational) wins on
    BIC (-4.434M, RMS 0.401 px ≈ noise floor 0.46 px). Disguise's CSV-K1-only
    forward distortion is captured by

        r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶)
            / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶)

    with a=-3.18050, b=+7.24462, c=+5.12035, d=-2.93087, e=+6.30678, f=+7.51125.
    This form is directly isomorphic to UE 5.7 BrownConradyUDLensModel shader
    (BrownConradyUDDistortion.usf:48-50):

        dr = (1 + K1·r² + K2·r⁴ + K3·r⁶) / (1 + K4·r² + K5·r⁴ + K6·r⁶)

    so coefficients can be plugged into UE LensFile without truncation:
        K1 = a·csv_K · (2·fx)²    K4 = d·csv_K · (2·fx)²
        K2 = b·csv_K² · (2·fx)⁴   K5 = e·csv_K² · (2·fx)⁴
        K3 = c·csv_K³ · (2·fx)⁶   K6 = f·csv_K³ · (2·fx)⁶

CSV K2 / K3 mapping NOT yet validated — Path A only swept csv_K1. Pass-through
sign-flip on csv_K2/K3 as additive corrections to UE_K2/UE_K3 (numerator
slots only, matches legacy behaviour for production CSV K1≈0).

Normalization-space conversion (sticky, kept from M6 era, commit 34f5af0):
    Fit was done in HALF-WIDTH-normalized r space (r = pixel_offset / (W/2)).
    UE LensFile applies the polynomial in FOCAL-LENGTH-normalized r space
    (r = pixel_offset / fx_pixels):
        r_HW = (2 · fx_uv) · r_fx
    Each polynomial coefficient scales by (2·fx_uv)^(2k) for k-th radial term.
    Both numerator AND denominator coefficients use the same scaling.

History:
    M6 polynomial (3 params, commit 5311d4f → 34f5af0): RMS 0.412 px in fit
    but in r > 0.806 corner has inflection causing UE rendering edge collapse.
    Replaced by M_RAT6 here.

    Earlier still (commit 3468a67): -K sign-flip as 0th-order Taylor.
"""
from __future__ import annotations

from .csv_parser import FrameData

# ── M6 polynomial coefficients (legacy, commit 34f5af0) ────────────
# 历史记录: 这是 SphericalLensModel 时代的 polynomial truncation 系数,
# 已被 M_RAT6 rational form 取代 (commit 8164938+), 因为 polynomial 在 r > 0.806
# 拐点处发散导致外圈渲染崩盘. 保留作 git blame reference, 实际不再使用.
# M6_A = -0.2507  K¹·r³
# M6_B = +0.2097  K²·r⁵
# M6_C = -0.1931  K³·r⁷

# ── M_RAT6 rational coefficients (Path A round 1, commit 8164938) ────────
# fit_distortion_models.py M_RAT6 BIC-best on 300k pixel samples:
#     r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶)
#         / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶)
# RMS 0.401 px ≈ noise floor, 跟 UE BrownConradyUDLensModel rational shader 同构.
M_RAT6_A: float = -3.18050
M_RAT6_B: float = +7.24462
M_RAT6_C: float = +5.12035
M_RAT6_D: float = -2.93087
M_RAT6_E: float = +6.30678
M_RAT6_F: float = +7.51125


def compute_normalized_distortion(frame_data: FrameData) -> dict:
    """Convert Designer mm-unit camera params to UE BrownConradyUD form.

    Returns a dict with keys ``fx, fy, cx, cy, k1..k6, p1, p2``. Tangential
    P1/P2 are zero — Disguise's CSV schema doesn't carry them.

    M_RAT6 rational fit produces 6 coefficients (a-f); each maps to UE K1-K6
    via fx-scaled csv_K powers (see module docstring). CSV K2/K3 still
    legacy sign-flip pass-through to numerator UE_K2/UE_K3.

    Parameters
    ----------
    frame_data:
        Single-frame camera record from `csv_parser.FrameData`.
    """
    pa_width = frame_data.sensor_width_mm
    focal_mm = frame_data.focal_length_mm
    aspect = frame_data.aspect_ratio

    fx = focal_mm / pa_width
    fy = fx * aspect
    cx = 0.5 + frame_data.center_shift_x_mm / pa_width
    pa_height = pa_width / aspect
    cy = 0.5 + frame_data.center_shift_y_mm / pa_height

    fx_scale = 2.0 * fx
    fx2 = fx_scale * fx_scale
    fx4 = fx2 * fx2
    fx6 = fx4 * fx2

    csv_k1 = frame_data.k1
    k1_sq = csv_k1 * csv_k1
    k1_cu = k1_sq * csv_k1

    # Numerator coefficients (UE K1-K3): rational + legacy CSV K2/K3 sign-flip
    ue_k1 = M_RAT6_A * csv_k1 * fx2
    ue_k2 = M_RAT6_B * k1_sq * fx4 - frame_data.k2
    ue_k3 = M_RAT6_C * k1_cu * fx6 - frame_data.k3

    # Denominator coefficients (UE K4-K6): rational pure
    ue_k4 = M_RAT6_D * csv_k1 * fx2
    ue_k5 = M_RAT6_E * k1_sq * fx4
    ue_k6 = M_RAT6_F * k1_cu * fx6

    return {
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
        "k1": ue_k1,
        "k2": ue_k2,
        "k3": ue_k3,
        "k4": ue_k4,
        "k5": ue_k5,
        "k6": ue_k6,
        "p1": 0.0,
        "p2": 0.0,
    }
