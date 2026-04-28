"""把 4 通道 STMap EXR 写入 UE LensFile 的 STMap table。

UE 5.7 API 链：
  AssetImportTask + AssetTools.import_asset_tasks() →  /Game/.../STMap_xxx (UTexture2D)
  unreal.STMapInfo() 构造，distortion_map ← 导入的纹理，map_format 用默认
  lens_file.add_stmap_point(new_focus, new_zoom, new_point)

通道布局（必须与 build_stmap.py 输出一致）：
  R, G  = undistortion UV
  B, A  = distortion UV
默认 FCalibratedMapFormat 直接消费这套布局（CalibratedMapFormat.h:43-47）。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import unreal

logger = logging.getLogger(__name__)


def _import_stmap_texture(
    exr_path: str,
    destination_path: str,
    asset_name: str,
) -> "unreal.Texture2D":
    """通过 AssetImportTask 把 EXR 导入为 UTexture2D。

    Parameters
    ----------
    exr_path
        本地 EXR 文件绝对路径。
    destination_path
        UE 内容浏览器目录，如 "/Game/PostRender/STMaps"。
    asset_name
        导入后的资产名（不含扩展），如 "STMap_take001"。

    Returns
    -------
    unreal.Texture2D
        已导入并保存的纹理。
    """
    if not os.path.isfile(exr_path):
        raise FileNotFoundError(f"STMap EXR not found: {exr_path}")

    task = unreal.AssetImportTask()
    task.filename = exr_path
    task.destination_path = destination_path
    task.destination_name = asset_name
    task.replace_existing = True
    task.replace_existing_settings = True
    task.automated = True
    task.save = True

    # TextureFactory 默认会自动选中（filename 后缀决定）；EXR 走 ExrImageWrapper
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    asset_tools.import_asset_tasks([task])

    full_asset_path = f"{destination_path}/{asset_name}"
    texture = unreal.load_asset(full_asset_path)
    if texture is None:
        raise RuntimeError(
            f"texture import succeeded but load_asset returned None: {full_asset_path}"
        )
    if not isinstance(texture, unreal.Texture):
        raise RuntimeError(
            f"imported asset is not a Texture: {type(texture).__name__} at {full_asset_path}"
        )

    logger.info("STMap 纹理已导入: %s (%dx%d)", full_asset_path, texture.blueprint_get_size_x(), texture.blueprint_get_size_y())
    return texture


def _build_stmap_info(texture: "unreal.Texture") -> "unreal.STMapInfo":
    """构造 FSTMapInfo，使用默认 MapFormat（PixelOrigin=TopLeft, Undist=RG, Dist=BA）。"""
    info = unreal.STMapInfo()
    info.distortion_map = texture
    # MapFormat 默认值已经匹配 build_stmap.py 输出布局，无需显式赋值。
    # 若要覆盖，可写：
    #   fmt = unreal.CalibratedMapFormat()
    #   fmt.pixel_origin = unreal.CalibratedMapPixelOrigin.TOP_LEFT
    #   fmt.undistortion_channels = unreal.CalibratedMapChannels.RG
    #   fmt.distortion_channels = unreal.CalibratedMapChannels.BA
    #   info.map_format = fmt
    return info


def add_stmap_to_lensfile(
    lens_file_path: str,
    stmap_exr_path: str,
    *,
    focus: float = 0.0,
    zoom: float = 0.0,
    texture_destination_path: str = "/Game/PostRender/STMaps",
    texture_asset_name: str | None = None,
) -> "unreal.LensFile":
    """主入口：把一张 STMap EXR 注册到 LensFile 的 STMap table。

    Parameters
    ----------
    lens_file_path
        LensFile 资产的 UE 路径，如 "/Game/PostRender/LensFiles/MyLens.MyLens"。
        若只给到包路径（不含 .Asset 后缀），会自动尝试 load_asset。
    stmap_exr_path
        本地 4 通道 STMap EXR 绝对路径（build_stmap.py 输出）。
    focus, zoom
        在 STMap table 里的 (focus, zoom) 索引。Per-take 标定通常用 (0, 0)。
    texture_destination_path
        导入纹理的 UE 内容浏览器目标目录。
    texture_asset_name
        导入后的纹理资产名；默认从 EXR 文件名派生。

    Returns
    -------
    unreal.LensFile
        已写入并保存的 LensFile。
    """
    lens_file = unreal.load_asset(lens_file_path)
    if not isinstance(lens_file, unreal.LensFile):
        raise RuntimeError(
            f"asset at {lens_file_path} is not a LensFile: {type(lens_file).__name__ if lens_file else None}"
        )

    if texture_asset_name is None:
        stem = Path(stmap_exr_path).stem
        texture_asset_name = f"T_{stem}"

    texture = _import_stmap_texture(
        exr_path=stmap_exr_path,
        destination_path=texture_destination_path,
        asset_name=texture_asset_name,
    )

    info = _build_stmap_info(texture)

    lens_file.add_stmap_point(new_focus=focus, new_zoom=zoom, new_point=info)
    logger.info(
        "lens_file.add_stmap_point(focus=%.3f, zoom=%.3f, distortion_map=%s)",
        focus, zoom, texture.get_path_name(),
    )

    unreal.EditorAssetLibrary.save_loaded_asset(lens_file)
    logger.info("LensFile 已保存: %s", lens_file.get_path_name())
    return lens_file


__all__ = ["add_stmap_to_lensfile"]
