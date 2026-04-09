"""Pipeline Orchestrator — VP Post-Render Tool.

主入口：将 Disguise Designer CSV Dense 文件导入为 UE 资产。
流程：CSV 解析 → LensFile → CineCameraActor → LevelSequence → 验证报告。

仅能在 UE Editor Python 环境中运行。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import unreal

from . import config
from .camera_builder import build_camera
from .csv_parser import CsvDenseResult, CsvParseError, parse_csv_dense
from .lens_file_builder import build_lens_file
from .sequence_builder import build_sequence
from .validator import ValidationReport, generate_report

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Outcome of a single run_import() call."""

    success: bool
    error_message: str = ""
    lens_file: Optional[object] = None       # unreal.LensFile
    camera_actor: Optional[object] = None    # unreal.CineCameraActor
    level_sequence: Optional[object] = None  # unreal.LevelSequence
    report: Optional[ValidationReport] = None
    package_path: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sanitize_stem(name: str) -> str:
    """Replace spaces and non-alphanumeric/underscore chars with '_'."""
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def _ensure_directory(package_path: str) -> None:
    """Create Content Browser directory if it does not already exist.

    Parameters
    ----------
    package_path:
        Content Browser path, e.g. "/Game/PostRender/MyShot".
    """
    if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
        unreal.EditorAssetLibrary.make_directory(package_path)
        logger.info("已创建内容浏览器目录: %s", package_path)
    else:
        logger.info("目录已存在: %s", package_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_import(csv_path: str, fps: float = 0.0) -> PipelineResult:
    """Main pipeline entry point: CSV → UE assets.

    Parameters
    ----------
    csv_path:
        Absolute or relative path to the Disguise Designer CSV Dense file.
    fps:
        Target frame rate. If <= 0, the value detected from the CSV is used.
        If no FPS can be determined, the pipeline aborts with an error.

    Returns
    -------
    PipelineResult
        Always returned (never raises). Check `.success` and `.error_message`.
    """
    # ------------------------------------------------------------------
    # 步骤 0: 准备元数据（stem、sanitize、package path）
    # ------------------------------------------------------------------
    try:
        csv_stem = Path(csv_path).stem
        stem = _sanitize_stem(csv_stem)
        package_path = f"{config.ASSET_BASE_PATH}/{stem}"

        unreal.log(f"[pipeline] 开始导入: {csv_path}")
        unreal.log(f"[pipeline] 资产目标路径: {package_path}")

        # ------------------------------------------------------------------
        # 步骤 1/5: 解析 CSV
        # ------------------------------------------------------------------
        unreal.log("[pipeline] 步骤 1/5 — 解析 CSV Dense 文件...")
        csv_result: CsvDenseResult = parse_csv_dense(csv_path)
        unreal.log(
            f"[pipeline] CSV 解析完成: {csv_result.frame_count} 帧, "
            f"传感器宽度 {csv_result.sensor_width_mm:.3f} mm, "
            f"检测帧率 {csv_result.detected_fps}"
        )

        # ------------------------------------------------------------------
        # 确定最终 FPS
        # ------------------------------------------------------------------
        effective_fps = fps if fps > 0.0 else csv_result.detected_fps

        if effective_fps is None:
            return PipelineResult(
                success=False,
                error_message=(
                    "无法确定帧率：CSV 中未检测到稳定帧率，且未提供 fps 参数。"
                    "请手动指定 fps。"
                ),
                package_path=package_path,
            )

        unreal.log(f"[pipeline] 使用帧率: {effective_fps} fps")

        # ------------------------------------------------------------------
        # 确保内容浏览器目录存在
        # ------------------------------------------------------------------
        _ensure_directory(package_path)

        # ------------------------------------------------------------------
        # 步骤 2/5: 构建 LensFile
        # ------------------------------------------------------------------
        unreal.log("[pipeline] 步骤 2/5 — 构建 LensFile 资产...")
        lens_file = build_lens_file(
            csv_result=csv_result,
            asset_name=f"LF_{stem}",
            package_path=package_path,
        )
        unreal.log("[pipeline] LensFile 构建完成。")

        # ------------------------------------------------------------------
        # 步骤 3/5: 创建 CineCameraActor
        # ------------------------------------------------------------------
        unreal.log("[pipeline] 步骤 3/5 — 创建 CineCameraActor...")
        camera_actor = build_camera(
            sensor_width_mm=csv_result.sensor_width_mm,
            lens_file=lens_file,
            actor_label=f"CineCamera_{stem}",
        )
        unreal.log("[pipeline] CineCameraActor 创建完成。")

        # ------------------------------------------------------------------
        # 步骤 4/5: 构建 LevelSequence
        # ------------------------------------------------------------------
        unreal.log("[pipeline] 步骤 4/5 — 构建 LevelSequence 资产...")
        level_sequence = build_sequence(
            csv_result=csv_result,
            camera_actor=camera_actor,
            fps=effective_fps,
            asset_name=f"LS_{stem}",
            package_path=package_path,
        )
        unreal.log("[pipeline] LevelSequence 构建完成。")

        # ------------------------------------------------------------------
        # 步骤 5/5: 生成验证报告
        # ------------------------------------------------------------------
        unreal.log("[pipeline] 步骤 5/5 — 生成验证报告...")
        report = generate_report(csv_result=csv_result, fps=effective_fps)
        unreal.log(report.format_report())

        unreal.log(
            f"[pipeline] 导入成功完成！资产路径: {package_path}"
        )

        return PipelineResult(
            success=True,
            lens_file=lens_file,
            camera_actor=camera_actor,
            level_sequence=level_sequence,
            report=report,
            package_path=package_path,
        )

    except CsvParseError as exc:
        msg = f"CSV 解析错误: {exc}"
        logger.error(msg)
        unreal.log_error(f"[pipeline] {msg}")
        return PipelineResult(
            success=False,
            error_message=msg,
            package_path=package_path if "package_path" in dir() else "",
        )

    except RuntimeError as exc:
        msg = f"运行时错误: {exc}"
        logger.error(msg)
        unreal.log_error(f"[pipeline] {msg}")
        return PipelineResult(
            success=False,
            error_message=msg,
            package_path=package_path if "package_path" in dir() else "",
        )

    except Exception as exc:  # noqa: BLE001
        msg = f"未预期的错误 [{type(exc).__name__}]: {exc}"
        logger.exception(msg)
        unreal.log_error(f"[pipeline] {msg}")
        return PipelineResult(
            success=False,
            error_message=msg,
            package_path=package_path if "package_path" in dir() else "",
        )
