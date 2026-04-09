"""Lens File Builder — VP Post-Render Tool.

将 Disguise Designer CSV 中的畸变数据转换为 UE LensFile 资产。
仅能在 UE Editor Python 环境中运行，不可在外部测试。
"""

from __future__ import annotations

import logging
from typing import Dict

# unreal 模块只在 UE Editor 进程内可用
import unreal

from . import config
from .csv_parser import CsvDenseResult, FrameData

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _compute_normalized_distortion(frame_data: FrameData) -> dict:
    """将 Designer mm 单位的畸变参数转换为 UE 归一化坐标系。

    Parameters
    ----------
    frame_data:
        单帧相机数据，来自 csv_parser.FrameData。

    Returns
    -------
    dict
        包含键 fx, fy, cx, cy, k1, k2, k3, p1, p2 的归一化参数字典。
    """
    pa_width = frame_data.sensor_width_mm
    focal_mm = frame_data.focal_length_mm
    aspect = frame_data.aspect_ratio

    fx = focal_mm / pa_width
    fy = fx * aspect
    cx = 0.5 + frame_data.center_shift_x_mm / pa_width
    # 传感器高度 = paWidthMM / aspectRatio
    pa_height = pa_width / aspect
    cy = 0.5 + frame_data.center_shift_y_mm / pa_height

    return {
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
        "k1": frame_data.k1,
        "k2": frame_data.k2,
        "k3": frame_data.k3,
        "p1": 0.0,
        "p2": 0.0,
    }


def _group_by_focal_length(
    frames: list,
    tolerance_mm: float,
) -> Dict[float, FrameData]:
    """按焦距对帧数据分组，容差范围内归为同一组。

    对于每个唯一焦距区间，保留该组中第一帧作为代表。
    算法：按焦距排序后，逐步合并距离上一组代表值在 tolerance_mm 内的帧。

    Parameters
    ----------
    frames:
        FrameData 列表（来自 CsvDenseResult.frames）。
    tolerance_mm:
        合并阈值（毫米）。配置项 FOCAL_LENGTH_GROUP_TOLERANCE_MM。

    Returns
    -------
    dict
        {focal_length_mm: FrameData}，键为该组代表焦距。
    """
    if not frames:
        return {}

    sorted_frames = sorted(frames, key=lambda f: f.focal_length_mm)
    groups: Dict[float, FrameData] = {}

    for frame in sorted_frames:
        fl = frame.focal_length_mm
        # 检查是否已有足够近的代表焦距
        matched = False
        for rep_fl in groups:
            if abs(fl - rep_fl) <= tolerance_mm:
                matched = True
                break
        if not matched:
            groups[fl] = frame

    return groups


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def build_lens_file(
    csv_result: CsvDenseResult,
    asset_name: str,
    package_path: str,
) -> "unreal.LensFile":
    """从 CSV 解析结果构建 UE LensFile 资产。

    流程：
    1. 通过 AssetTools 创建 LensFile 资产。
    2. 按焦距分组（容差 = FOCAL_LENGTH_GROUP_TOLERANCE_MM）。
    3. 对每组计算归一化畸变参数并写入 LensFile。
    4. 保存资产到内容浏览器。

    Parameters
    ----------
    csv_result:
        由 csv_parser.parse_csv_dense() 返回的解析结果。
    asset_name:
        目标资产名称（不含路径），如 "LF_Camera01"。
    package_path:
        内容浏览器中的目标路径，如 "/Game/PostRender/LensFiles"。

    Returns
    -------
    unreal.LensFile
        已创建并保存的 LensFile 对象。

    Raises
    ------
    RuntimeError
        资产创建失败时抛出。
    """
    # ------------------------------------------------------------------
    # 1. 创建资产
    # ------------------------------------------------------------------
    logger.info("正在创建 LensFile 资产: %s/%s", package_path, asset_name)
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    lens_file: unreal.LensFile = asset_tools.create_asset(
        asset_name=asset_name,
        package_path=package_path,
        asset_class=unreal.LensFile,
        factory=unreal.LensFileFactoryNew(),
    )

    if lens_file is None:
        raise RuntimeError(
            f"LensFile 资产创建失败: {package_path}/{asset_name}"
        )
    logger.info("资产创建成功，开始写入畸变数据...")

    # ------------------------------------------------------------------
    # 2. 按焦距分组
    # ------------------------------------------------------------------
    groups = _group_by_focal_length(
        csv_result.frames,
        config.FOCAL_LENGTH_GROUP_TOLERANCE_MM,
    )
    logger.info("焦距分组完成，共 %d 组: %s", len(groups),
                [round(fl, 3) for fl in sorted(groups)])

    # ------------------------------------------------------------------
    # 3. 写入各组畸变点
    # ------------------------------------------------------------------
    success_count = 0
    for focal_mm, frame in sorted(groups.items()):
        nd = _compute_normalized_distortion(frame)
        logger.info(
            "  写入焦距 %.3f mm → fx=%.4f fy=%.4f cx=%.4f cy=%.4f "
            "k1=%.6f k2=%.6f k3=%.6f",
            focal_mm, nd["fx"], nd["fy"], nd["cx"], nd["cy"],
            nd["k1"], nd["k2"], nd["k3"],
        )

        # UE LensFile Python API 在不同引擎版本中签名略有差异，使用 try/except 兜底
        added = False

        # 尝试方式 A：add_distortion_point(focus, zoom, params_struct)
        try:
            params = unreal.LensDistortionState()
            params.distortion_info.parameters = [
                nd["k1"], nd["k2"], nd["p1"], nd["p2"], nd["k3"]
            ]
            params.focal_length_info.fx = nd["fx"]
            params.focal_length_info.fy = nd["fy"]
            params.image_center_info.cx = nd["cx"]
            params.image_center_info.cy = nd["cy"]
            # focus=0（固定对焦），zoom 用归一化焦距比（焦距/传感器宽度）
            zoom_value = focal_mm / frame.sensor_width_mm
            lens_file.add_distortion_point(
                focus=0.0,
                zoom=zoom_value,
                distortion_state=params,
            )
            added = True
            logger.info("    [方式A] 写入成功 (zoom=%.4f)", zoom_value)
        except (AttributeError, TypeError, Exception) as exc_a:  # noqa: BLE001
            logger.warning("    [方式A] 失败: %s", exc_a)

        # 尝试方式 B：add_distortion_point 使用 DistortionInfo / separate structs
        if not added:
            try:
                distortion_info = unreal.DistortionInfo()
                distortion_info.parameters = [
                    nd["k1"], nd["k2"], nd["p1"], nd["p2"], nd["k3"]
                ]
                focal_info = unreal.FocalLengthInfo()
                focal_info.fx = nd["fx"]
                focal_info.fy = nd["fy"]
                image_center = unreal.ImageCenterInfo()
                image_center.cx = nd["cx"]
                image_center.cy = nd["cy"]
                zoom_value = focal_mm / frame.sensor_width_mm
                lens_file.add_distortion_point(
                    focus=0.0,
                    zoom=zoom_value,
                    distortion_info=distortion_info,
                    focal_length_info=focal_info,
                    image_center_info=image_center,
                )
                added = True
                logger.info("    [方式B] 写入成功 (zoom=%.4f)", zoom_value)
            except (AttributeError, TypeError, Exception) as exc_b:  # noqa: BLE001
                logger.warning("    [方式B] 失败: %s", exc_b)

        if not added:
            logger.error(
                "    焦距 %.3f mm 畸变数据写入失败，已跳过。"
                "请检查当前 UE 版本的 LensFile Python API。",
                focal_mm,
            )
        else:
            success_count += 1

    logger.info("畸变数据写入完成: %d/%d 组成功", success_count, len(groups))

    if success_count == 0 and len(groups) > 0:
        raise RuntimeError(
            f"LensFile 畸变数据写入全部失败（{len(groups)} 个焦距组）。"
            "请检查当前 UE 版本的 LensFile Python API 是否兼容。"
        )

    if success_count < len(groups):
        logger.warning(
            "部分焦距组写入失败: %d/%d 成功。LensFile 数据可能不完整。",
            success_count, len(groups),
        )

    # ------------------------------------------------------------------
    # 4. 保存资产
    # ------------------------------------------------------------------
    full_asset_path = f"{package_path}/{asset_name}.{asset_name}"
    unreal.EditorAssetLibrary.save_asset(full_asset_path, only_if_is_dirty=False)
    logger.info("LensFile 已保存: %s", full_asset_path)

    return lens_file
