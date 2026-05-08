"""Distortion parameter packing — VP Post-Render Tool.

把归一化畸变字典打包成 UE Spherical 畸变模型期望的扁平 list，顺序必须严格匹配
``FSphericalDistortionParameters`` 的 UPROPERTY 声明顺序：

    K1, K2, K3, P1, P2

UE 在 ``ULensModel::FromArray_Internal``（CameraCalibrationCore/Private/Models/
LensModel.cpp:108-134）用 ``TFieldIterator<FProperty>`` 按字段声明顺序把
``FDistortionInfo.Parameters`` 数组逐个回填到 struct 字段，错一位就会让 K3↔P1↔P2
互窜——表现为 Designer K3 被解读成 UE P2 之类的隐性 Bug。

历史教训（2026-04-27）：lens_file_builder 曾写成 ``[k1, k2, p1, p2, k3]``，导致
CSV K3=0.335 落到 UE P2 槽、UE K3 槽变成 0。

本模块是 pure Python，不引入 ``unreal`` 依赖，可在 UE 外用 unittest 跑回归。
"""

from __future__ import annotations


# 顺序源于 SphericalLensModel.h FSphericalDistortionParameters UPROPERTY 声明。
SPHERICAL_PARAMETER_ORDER: tuple[str, ...] = ("k1", "k2", "k3", "p1", "p2")


def to_spherical_parameters(normalized: dict) -> list[float]:
    """按 UE Spherical 模型的 K1, K2, K3, P1, P2 顺序打包归一化畸变参数。

    Parameters
    ----------
    normalized:
        ``distortion_math.compute_normalized_distortion`` 的返回字典，必须包含
        ``k1, k2, k3, p1, p2`` 五个键。

    Returns
    -------
    list[float]
        长度为 5 的 list，对应 ``FSphericalDistortionParameters`` 的字段顺序。

    Raises
    ------
    KeyError
        缺失任一必需键时抛出，避免静默把 0.0 塞到错误槽位。
    """
    return [float(normalized[key]) for key in SPHERICAL_PARAMETER_ORDER]


_BROWN_CONRADY_UD_KEYS: tuple[str, ...] = ("k1", "k2", "k3", "k4", "k5", "k6", "p1", "p2")


def to_brown_conrady_ud_parameters(normalized: dict) -> list[float]:
    """按 UE BrownConradyUD 模型的 K1-K6 + P1, P2 顺序打包归一化畸变参数。

    UE shader (BrownConradyUDDistortion.usf:48-50) 用 polynomial division 形态:
        dr = (1 + K1·r² + K2·r⁴ + K3·r⁶) / (1 + K4·r² + K5·r⁴ + K6·r⁶)

    UE 在 ``ULensModel::FromArray_Internal`` 用 ``TFieldIterator<FProperty>`` 按
    UPROPERTY 声明顺序 (BrownConradyUDLensModel.h:23-52) 把数组回填到 struct 字段;
    错位会让 K2-K6 / P1/P2 互窜.

    Parameters
    ----------
    normalized:
        ``distortion_math.compute_normalized_distortion`` 的返回字典, 必须包含
        ``k1, k2, k3, k4, k5, k6, p1, p2`` 八个键.

    Returns
    -------
    list[float]
        长度 8, 顺序匹配 FBrownConradyUDDistortionParameters 字段顺序.

    Raises
    ------
    KeyError
        缺任一必需键时抛出.
    """
    missing = [k for k in _BROWN_CONRADY_UD_KEYS if k not in normalized]
    if missing:
        raise KeyError(f"missing required keys for BrownConradyUD: {missing}")
    return [float(normalized[k]) for k in _BROWN_CONRADY_UD_KEYS]
