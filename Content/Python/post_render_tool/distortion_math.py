"""Disguise CSV → UE LensFile distortion-coefficient math.

Pure Python (no ``unreal`` import); UE-side caller is `lens_file_builder.py`.
All unit conversions and the M6 polynomial mapping live here so the math
is testable outside UE Editor — same pattern as `distortion_packing.py`.

M6 mapping (Path A system identification, commit 5311d4f):

    UV-gradient probe + 11-K-sweep (CSV K1 ∈ {0, ±0.1..±0.5} with K2=K3=0),
    M1-M10 candidate fit on 300k pixel samples. M6 wins on BIC (-4.42M, RMS
    0.412 px ≈ noise floor 0.46 px). Disguise's CSV-K1-only forward
    distortion is captured by

        r' = r · (1 + a·csv_K1·r² + b·csv_K1²·r⁴ + c·csv_K1³·r⁶)

    with a=-0.2507, b=+0.2097, c=-0.1931. Expanding into UE Brown-Conrady
    form r·(1 + ue_K1·r² + ue_K2·r⁴ + ue_K3·r⁶) gives the M6 coefficients
    used here.

CSV K2 / K3 mapping NOT yet validated — Path A has only swept K1. The fall-
back here treats CSV K2/K3 as Brown-Conrady-on-OpenCV (independent r⁴ / r⁶
scalars) and applies the same forward↔inverse sign flip as the pre-M6
pipeline, then sums with the M6 K1²/K1³ contributions. For production CSV
(K1≈3e-4) the M6 K1²/K1³ terms are vanishingly small, so behaviour is
essentially the legacy sign-flip; for CSV K1 in the test sweep range
(|K1|≥0.1) the M6 cubic dominates and matches Disguise within ~0.4 px.

TODO (full pixel-perfect): K2 sweep + K3 sweep + joint validation to
confirm CSV K2/K3 mapping.

History: commit 3468a67 used -K (sign flip) as a 0th-order Taylor approxi-
mation; the 1.5x visual-match factor cited then was a single-K1 best-fit
artifact. M6 reveals the true K1 mapping is α=-0.2507 with K1² and K1³
higher-order corrections that the earlier single-axis comparison missed.
"""
from __future__ import annotations

from .csv_parser import FrameData

M6_A: float = -0.2507
M6_B: float = +0.2097
M6_C: float = -0.1931


def compute_normalized_distortion(frame_data: FrameData) -> dict:
    """Convert Designer mm-unit camera params to UE-normalized form.

    Returns a dict with keys ``fx``, ``fy``, ``cx``, ``cy``, ``k1``, ``k2``,
    ``k3``, ``p1``, ``p2``. Tangential P1/P2 are zero — Disguise's CSV
    schema doesn't carry them.

    Normalization-space conversion (Tier 2 fix, commit TBD):
        M6 was fit in HALF-WIDTH-normalized r space (r = pixel_offset / (W/2)).
        UE LensFile applies the polynomial in FOCAL-LENGTH-normalized r space
        (r = pixel_offset / fx_pixels). Same physical r maps to different
        numeric values in the two spaces:
            r_HW = (2 · fx_uv) · r_fx
        For the polynomial r·(1 + K·r² + ...) to describe the same physical
        distortion in both normalizations, the coefficients must scale:
            K1_fx = K1_HW · (2 · fx_uv)²
            K2_fx = K2_HW · (2 · fx_uv)⁴
            K3_fx = K3_HW · (2 · fx_uv)⁶
        For typical 30mm-on-35mm-sensor (fx_uv ≈ 0.866), these factors are
        roughly 3x, 9x, 27x — sizable. Without the conversion UE under-applies
        distortion by 3-30x at the K3 corner term and Tier 2 fails by ~30 px.

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

    # HW-norm → fx-norm scaling (see docstring)
    fx_scale = 2.0 * fx
    fx2 = fx_scale * fx_scale
    fx4 = fx2 * fx2
    fx6 = fx4 * fx2

    csv_k1 = frame_data.k1
    ue_k1 = M6_A * csv_k1 * fx2
    ue_k2 = M6_B * csv_k1 * csv_k1 * fx4 - frame_data.k2
    ue_k3 = M6_C * csv_k1 * csv_k1 * csv_k1 * fx6 - frame_data.k3

    return {
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
        "k1": ue_k1,
        "k2": ue_k2,
        "k3": ue_k3,
        "p1": 0.0,
        "p2": 0.0,
    }
