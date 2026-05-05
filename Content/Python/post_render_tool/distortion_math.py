"""Disguise CSV → UE 畸变映射数学 (双路线共用).

Pure Python (no ``unreal`` import); 测试通过 unittest 在 UE Editor 外运行.

模块同时提供两条路线的公式实现:

1. ``compute_normalized_distortion`` (Path A · 老路, LensFile + BrownConradyUD):
   把 CSV K1/K2/K3 翻译成 UE LensFile 的 8 系数 + fxfy + cxcy. 用 M_RAT6
   rational form 拟合, 详见模块下方常量注释.

2. ``official_sensor_inverse_uv`` (Path C · 新路, Custom Post-Process Material):
   照搬 docs/custom-postprocess-distortion-final-plan.md §2.4 的 HLSL 公式,
   shader / C++ controller 必须照抄. Gate 1 单元测试守住公式形态契约.

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

# ── M_RAT6 rational coefficients ────────────────────────────────────────────
# Path A round 1 (commit 8164938): 11-frame K1 sweep @ 1080p, RMS 0.401 px
# Path A round 2.1 (commit xxx): 51-frame K1 sweep @ 4K + 1.5× over-scan, RMS 1.135 px @ 4K
#
# Round 2.1 BIC-best M_RAT6 on 5M samples (after 5% robust trim):
#     r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶)
#         / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶)
# Trimmed RMS 1.135 px @ 4K (≈0.57 px @ 1080p), trimmed max 5.786 px @ 4K
# Full-set RMS 1.9 px, full-set max 39.5 px (K=-0.5 extreme).
# M_RAT8 (BIC -70.99M vs M_RAT6 -70.62M) adds r⁸ terms but UE shader only
# has K1-K6 slots → M_RAT6 is the deployable ceiling for BrownConradyUD.
#
# 注意: Round 2.1 系数绝对值很大 (10²~10⁶), 是 r 扩展到 1.33 (over-scan) 后
# 的数值现象, numerator/denominator 近似抵消后净效果跟 Round 1 类似.
# production K1 ≈ 3e-4 时 M_RAT6 项贡献 sub-1e-7, 主导项仍是 legacy K2/K3 sign-flip.
M_RAT6_A: float = +602.25734
M_RAT6_B: float = +812547.17935
M_RAT6_C: float = +395029.04330
M_RAT6_D: float = +602.66929
M_RAT6_E: float = +814809.12141
M_RAT6_F: float = +601028.79343


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


# ── Path C · Custom Post-Process Material 公式 reference ───────────────────
# 跟 docs/custom-postprocess-distortion-final-plan.md §2.4 的 HLSL shader 公式
# 一字一致. UE Material graph 与 PostRenderDistortionControllerComponent
# 必须照抄此实现. 任何形态调整 (Gate 6 反推 K2/K3 阶数后) 都先在这里改, 测试
# 跑过, 再把 shader graph 同步过去.
#
# 公式 (output → source 取样映射, 即 cv2.remap forward map):
#     d = UV - CenterUV
#     r = (2·d.x, 2·d.y / aspect)            # sensor-width 归一化
#     r² = r·r
#     factor = K1·r² + K2·r⁴ + K3·r⁶          # OpenCV 标准形态打底, Gate 6 后可能改
#     sourceUV = UV + factor · d · DistortionWeight
#
# 越界 (sourceUV ∉ [0,1]²) 时 shader 输出 black, 这里返回原始坐标即可,
# 黑边判断由调用者负责.

def official_sensor_inverse_uv(
    u: float,
    v: float,
    *,
    k1: float,
    k2: float,
    k3: float,
    center_uv: tuple = (0.5, 0.5),
    aspect: float,
    distortion_weight: float = 1.0,
) -> tuple:
    """Disguise official_sensor_inverse 的 UV-space pure-Python reference.

    给定输出像素 UV, 返回应该从输入图哪里取样的 sourceUV. 与
    ``M_PRT_OfficialSensorInverse`` material shader 公式一字一致.

    Parameters
    ----------
    u, v
        输出像素的 UV 坐标 (left-top origin, [0, 1] 范围).
    k1, k2, k3
        Disguise CSV 提供的畸变系数, 直接透传, 不做符号翻转.
    center_uv
        畸变中心 UV (光学中心), Path C pipeline 通过
        ``CenterU = 0.5 + centerShiftMM.x / sensorWidthMM`` 计算 (plan §2.5).
    aspect
        画面长宽比 W/H. r.y 用 ``2·d.y/aspect`` 把 y 归一化到 sensor-width
        空间, 跟 r.x 同尺度.
    distortion_weight
        位移幅度乘子. 1.0 = 完整 distortion, 0.0 = identity, 中间值用于淡入.

    Returns
    -------
    tuple[float, float]
        ``(source_u, source_v)`` —— 应该从输入图采样的 UV.

    Notes
    -----
    本函数是 scalar-only 实现. Gate 2 (offline shader-equivalent CPU reference)
    需要 numpy 向量化版本时, 在调用方写 vectorized wrapper 即可, 公式形态
    在这里钉死.
    """
    cu, cv = center_uv
    dx = u - cu
    dy = v - cv

    rx = 2.0 * dx
    ry = 2.0 * dy / aspect
    r2 = rx * rx + ry * ry

    factor = k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2

    source_u = u + factor * dx * distortion_weight
    source_v = v + factor * dy * distortion_weight
    return source_u, source_v
