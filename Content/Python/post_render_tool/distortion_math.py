"""Disguise CSV → UE 畸变映射数学 (Path C: Custom Post-Process Material).

Pure Python (no ``unreal`` import); 测试通过 unittest 在 UE Editor 外运行.

提供 Path C 的 ``official_sensor_inverse_uv`` 函数, 照搬
docs/custom-postprocess-distortion-final-plan.md §2.4 的 HLSL 公式. UE
Material graph 与 ``PostRenderDistortionControllerComponent`` 必须照抄此
实现; Gate 1 单元测试守住公式形态契约.

Path A (LensFile + BrownConradyUD M_RAT6) 已下架 (2026-05-08), 历史代码
归档在 ``archive/path_a_runtime/distortion_math_path_a.py``.
"""
from __future__ import annotations


# ── Path C · Custom Post-Process Material 公式 reference ───────────────────
# 跟 docs/custom-postprocess-distortion-final-plan.md §2.4 的 HLSL shader 公式
# 一字一致. UE Material graph 与 PostRenderDistortionControllerComponent
# 必须照抄此实现. 任何形态调整 (Gate 6 反推 K2/K3 阶数后) 都先在这里改, 测试
# 跑过, 再把 shader graph 同步过去.
#
# 公式 (output → source 取样映射, 即 cv2.remap forward map):
#     d = UV - CenterUV
#     r = (d.x, d.y / aspect)                  # sensor full-width 归一化 (2026-05-06 Gate 结论)
#     r² = r·r
#     factor = K1·r² + K2·r⁴ + K3·r⁶          # OpenCV 标准形态打底, Gate 6 后可能改
#     csxUV = CenterUV - (0.5, 0.5)            # principal-point 平移项 (2026-05-07 12 帧 fit 结论)
#     sourceUV = UV + (factor · d - csxUV) · DistortionWeight
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
        本参数在公式里有两个作用:
        1. 作为径向项的零点 (``d = UV - center_uv``);
        2. 推出 ``csx_uv = center_uv - 0.5``, 在 source UV 上额外减去
           principal-point 平移. K=0 时 d3 仍然平移 source, 跟早期假设相反,
           参见 validation_results/normalization_gate/20260507_150346_center_shift_report.md.
    aspect
        画面长宽比 W/H. r.y 用 ``d.y/aspect`` 把 y 归一化到 sensor full-width
        空间, 跟 r.x 同尺度.
    distortion_weight
        位移幅度乘子. 1.0 = 完整 distortion, 0.0 = identity, 中间值用于淡入.
        注意 weight 同时作用在径向项 *和* 平移项上 (weight=0 → 完全 identity).

    Returns
    -------
    tuple[float, float]
        ``(source_u, source_v)`` —— 应该从输入图采样的 UV.

    Notes
    -----
    本函数是 scalar-only 实现. Gate 2 (offline shader-equivalent CPU reference)
    需要 numpy 向量化版本时, 在调用方写 vectorized wrapper 即可, 公式形态
    在这里钉死.

    centerShift 平移项 (2026-05-07 加): 12-frame fit at K=0 with varying csx_mm
    显示 d3 在 source UV 上额外减去 ``csx_uv = center_uv - 0.5``, 跟 radial
    解耦. 详见 validation_results/normalization_gate/20260507_150346_summary.md.
    """
    cu, cv = center_uv
    dx = u - cu
    dy = v - cv

    rx = dx
    ry = dy / aspect
    r2 = rx * rx + ry * ry

    factor = k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2

    # centerShift = (CenterU - 0.5, CenterV - 0.5) — d3 translates source UV by -csx_uv
    # in addition to the radial term, even when K=0. Verified by
    # validation_results/normalization_gate/20260507_150346_center_shift_report.md.
    csx_u = cu - 0.5
    csx_v = cv - 0.5

    source_u = u + (factor * dx - csx_u) * distortion_weight
    source_v = v + (factor * dy - csx_v) * distortion_weight
    return source_u, source_v
