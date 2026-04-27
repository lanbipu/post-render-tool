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
from .distortion_packing import to_spherical_parameters

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
    # 1. 创建或复用资产（幂等）
    # ------------------------------------------------------------------
    # 策略：资产已存在 → load + ClearAll() 清空所有 tables → 落到下面重填。
    # 原因：LensFile 可能已被场景里的 CineCameraActor 引用，此时 create_asset
    # 会失败（AssetTools 弹 "is in use" 对话框）。清空 in-place 既不破坏引用，
    # 又能反映 CSV 最新内容 —— 避免"同名 CSV 改过内容后畸变数据仍是旧值"的
    # 静默错误（LensFile.h:222-223 UFUNCTION ULensFile::ClearAll）。
    full_asset_path = f"{package_path}/{asset_name}"
    lens_file: "unreal.LensFile | None" = None

    if unreal.EditorAssetLibrary.does_asset_exist(full_asset_path):
        existing = unreal.EditorAssetLibrary.load_asset(full_asset_path)
        if existing is not None:
            logger.info("LensFile 已存在，清空旧 tables 后重建: %s", full_asset_path)
            existing.clear_all()
            lens_file = existing
        else:
            logger.warning(
                "LensFile 资产存在但 load 失败，尝试重新创建: %s", full_asset_path
            )

    if lens_file is None:
        logger.info("正在创建 LensFile 资产: %s", full_asset_path)
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

        # UE 5.7: ULensFileFactoryNew 在 CameraCalibrationEditor Private 模块，
        # 未导出给 Python。create_asset 接受 factory=None 时走 NewObject 默认路径
        # (AssetTools.cpp:1762-1764)。保留对旧版本 factory 的兼容兜底。
        factory_obj = None
        factory_cls = getattr(unreal, "LensFileFactoryNew", None)
        if factory_cls is not None:
            try:
                factory_obj = factory_cls()
                logger.info("使用 LensFileFactoryNew 创建资产")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "LensFileFactoryNew 实例化失败，回落到 factory=None: %s", exc
                )
                factory_obj = None
        else:
            logger.info("UE 5.7 未导出 LensFileFactoryNew，使用 factory=None 默认路径")

        lens_file = asset_tools.create_asset(
            asset_name=asset_name,
            package_path=package_path,
            asset_class=unreal.LensFile,
            factory=factory_obj,
        )

        if lens_file is None:
            raise RuntimeError(
                f"LensFile 资产创建失败: {full_asset_path}"
            )
        logger.info("资产创建成功，开始写入畸变数据...")
    else:
        logger.info("开始向已有 LensFile 写入畸变数据...")

    # ------------------------------------------------------------------
    # 2. 写入 LensInfo.SensorDimensions（标定传感器尺寸）
    # ------------------------------------------------------------------
    # 运行时 FxFyScale = LensInfo.SensorDimensions / CameraFilmback
    # (LensFile.cpp:453)，然后 FxFy_runtime = FxFy_stored * FxFyScale。
    # 必须让 LensInfo 跟我们下游 CineCameraComponent.Filmback 写的是同一尺寸，
    # 否则 Distortion 映射和 Filmback 两边会错位，导致镜头比例异常。
    pa_width = csv_result.sensor_width_mm
    aspect = csv_result.aspect_ratio
    # 上游 pipeline.run_import 在 step 1 之后已拒绝 aspect<=0 / width<=0 的
    # CSV，这里不再兜底 —— fallback 会生成"能保存但尺寸错"的 LensFile，反而
    # 让静默错误绕过校验。
    pa_height = pa_width / aspect
    try:
        lens_info = lens_file.get_editor_property("lens_info")
        lens_info.sensor_dimensions = unreal.Vector2D(pa_width, pa_height)
        # LensInfo.LensModel 显式写为 Spherical：默认 None 时 LensComponent 走
        # SetLensFilePicker → SetLensModel(null) 路径 (LensComponent.cpp:602)，
        # CreateDistortionHandler 不会跑、LensDistortionHandlerMap 留空、
        # TickComponent 拿不到 handler → distortion 整段静默跳过。
        # camera_builder 那边也独立写了一次（双保险），这里写在资产上让所有
        # 路径（LensFile Editor preview、ICVFX 等）共享同一个真相源。
        spherical_cls = unreal.load_class(
            None, "/Script/CameraCalibrationCore.SphericalLensModel"
        )
        if spherical_cls is not None:
            lens_info.lens_model = spherical_cls
        lens_file.set_editor_property("lens_info", lens_info)
        logger.info(
            "LensInfo 已设置: SensorDimensions=%.3fx%.3f mm, LensModel=%s",
            pa_width, pa_height, lens_info.lens_model,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"LensInfo 写入失败: {exc}"
        ) from exc

    # ------------------------------------------------------------------
    # 3. 按焦距分组
    # ------------------------------------------------------------------
    groups = _group_by_focal_length(
        csv_result.frames,
        config.FOCAL_LENGTH_GROUP_TOLERANCE_MM,
    )
    logger.info("焦距分组完成，共 %d 组: %s", len(groups),
                [round(fl, 3) for fl in sorted(groups)])

    # ------------------------------------------------------------------
    # 4. 写入各组畸变点
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

        # UE 5.7 LensFile API（CameraCalibrationCore/Public/LensFile.h:174-183）：
        #   - AddDistortionPoint(focus, zoom, FDistortionInfo, FFocalLengthInfo)
        #   - AddImageCenterPoint(focus, zoom, FImageCenterInfo)
        # Struct 字段（LensData.h:162-220）：
        #   - FDistortionInfo.Parameters: TArray<float>       → parameters
        #   - FFocalLengthInfo.FxFy:      FVector2D           → fx_fy
        #   - FImageCenterInfo.PrincipalPoint: FVector2D      → principal_point
        # focus=0（固定对焦点）。
        # zoom key 单位必须是毫米，与运行时 LensComponent UseCameraSettings 模式
        # 喂进来的 EvalInputs.Zoom 一致 —— LensComponent.cpp:100 把
        # CineCameraComponent.CurrentFocalLength (mm) 缓存到 OriginalFocalLength,
        # line 1017 直接赋给 EvalInputs.Zoom, line 136 再传给 EvaluateDistortionData。
        # 历史 Bug：曾用归一化值 focal_mm/sensor_width_mm（0.5–2 量级），多焦距
        # CSV 下运行时拿 mm 量级的 30/50/70 去查表会落在所有 key 的右侧极值，
        # LensFile 内部 clamp 后只返回最后一组畸变 → 变焦时畸变与焦距脱钩。
        zoom_value = float(focal_mm)
        try:
            distortion_info = unreal.DistortionInfo()
            # 必须按 FSphericalDistortionParameters 字段声明顺序 (K1, K2, K3, P1, P2)
            # 打包，详见 distortion_packing.py 与 SphericalLensModel.h 注释。
            distortion_info.parameters = to_spherical_parameters(nd)

            focal_info = unreal.FocalLengthInfo()
            focal_info.fx_fy = unreal.Vector2D(nd["fx"], nd["fy"])

            image_center = unreal.ImageCenterInfo()
            image_center.principal_point = unreal.Vector2D(nd["cx"], nd["cy"])

            lens_file.add_distortion_point(
                new_focus=0.0,
                new_zoom=zoom_value,
                new_point=distortion_info,
                new_focal_length=focal_info,
            )
            lens_file.add_image_center_point(
                new_focus=0.0,
                new_zoom=zoom_value,
                new_point=image_center,
            )
            logger.info("    写入成功 (zoom=%.3f mm)", zoom_value)
            success_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "    焦距 %.3f mm 写入失败 [%s]: %s",
                focal_mm, type(exc).__name__, exc,
            )

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
    # 5. 保存资产
    # ------------------------------------------------------------------
    # save_asset 需要 Object 路径（含 .asset_name 对象后缀），不同于 package 路径。
    save_path = f"{full_asset_path}.{asset_name}"
    unreal.EditorAssetLibrary.save_asset(save_path, only_if_is_dirty=False)
    logger.info("LensFile 已保存: %s", save_path)

    return lens_file
