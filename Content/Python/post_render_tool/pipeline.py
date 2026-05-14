"""Pipeline Orchestrator — VP Post-Render Tool.

主入口：将 Disguise Designer CSV Dense 文件导入为 UE 资产。
流程：CSV 解析 → CineCameraActor + DistortionController → LevelSequence
     (含 7 条 distortion 关键帧轨) → 验证报告。

Distortion 由 PostRenderDistortionControllerComponent + M_PRT_OfficialSensorInverse
post-process material 完成, 每帧 K1/K2/K3/CenterU/CenterV/Aspect/DistortionWeight
通过 Sequencer Interp float track 驱动.

Path A (LensFile + BrownConradyUD M_RAT6) 已下架 (2026-05-08), 历史代码归档
在 ``archive/path_a_runtime/``.

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
from .csv_parser import CsvDenseResult, CsvParseError, parse_csv_dense, trim_static_padding
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
    # 字段保留以维持调用方兼容; Path A 下架后永远为 None.
    lens_file: Optional[object] = None       # unreal.LensFile (deprecated, always None)
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

def run_import(csv_path: str, fps: float) -> PipelineResult:
    """Main pipeline entry point: CSV → UE assets.

    Parameters
    ----------
    csv_path:
        Absolute or relative path to the Disguise Designer CSV Dense file.
    fps:
        Target frame rate. Must be > 0.

    Returns
    -------
    PipelineResult
        Always returned (never raises). Check `.success` and `.error_message`.
    """
    try:
        csv_stem = Path(csv_path).stem
        stem = _sanitize_stem(csv_stem)
        package_path = f"{config.ASSET_BASE_PATH}/{stem}"

        if fps <= 0.0:
            return PipelineResult(
                success=False,
                error_message="无法确定帧率：请在 UI 中手动指定 fps（> 0）。",
                package_path=package_path,
            )

        # ── 检查 deployed Material asset 是否跟 Python HLSL 源码一致 ──
        # Codex adversarial review (2026-05-07): 仅改 Python 源码不能保证 runtime
        # shader 跟着更新, MRQ 仍然 hit 旧 .uasset. 启动前主动校验.
        from . import build_distortion_material as bdm
        is_fresh, msg = bdm.verify_material_freshness()
        if not is_fresh:
            return PipelineResult(
                success=False,
                error_message=f"Material 资产校验失败: {msg}",
                package_path=package_path,
            )
        unreal.log(f"[pipeline] Material 资产校验通过: {msg}")

        unreal.log(f"[pipeline] 开始导入: {csv_path}")
        unreal.log(f"[pipeline] 资产目标路径: {package_path}")
        unreal.log(f"[pipeline] 使用帧率: {fps} fps")

        unreal.log("[pipeline] 步骤 1/4 — 解析 CSV Dense 文件...")
        # Pass fps so csv_parser builds structured Timecode + runs SMPTE
        # equivalence check (P0 timecode-sync); sequence_builder reads
        # csv_result.start_timecode and persists it to the sample DataAsset.
        csv_result: CsvDenseResult = parse_csv_dense(csv_path, fps=fps)
        original_count = csv_result.frame_count
        csv_result = trim_static_padding(csv_result)
        if csv_result.frame_count != original_count:
            unreal.log(
                f"[pipeline] 裁掉首尾静止帧: {original_count} → "
                f"{csv_result.frame_count} 帧 (运动起点 d3 frame "
                f"{csv_result.frames[0].frame_number})"
            )
        unreal.log(
            f"[pipeline] CSV 解析完成: {csv_result.frame_count} 帧, "
            f"传感器宽度 {csv_result.sensor_width_mm:.3f} mm, "
            f"aspect {csv_result.aspect_ratio:.4f}"
        )

        # CSV 元数据校验必须早于任何资产写入.
        if csv_result.sensor_width_mm <= 0:
            raise RuntimeError(
                f"CSV sensor_width_mm 非法 ({csv_result.sensor_width_mm})，"
                f"无法推算 Filmback。"
            )
        if csv_result.aspect_ratio <= 0:
            raise RuntimeError(
                f"CSV aspect_ratio 非法 ({csv_result.aspect_ratio})，"
                f"无法推算 sensor_height。"
            )
        sensor_height_mm = csv_result.sensor_width_mm / csv_result.aspect_ratio

        # ------------------------------------------------------------------
        # 确保内容浏览器目录存在
        # ------------------------------------------------------------------
        _ensure_directory(package_path)

        # ------------------------------------------------------------------
        # 步骤 2/4: 创建 CineCameraActor + 挂 DistortionController
        # ------------------------------------------------------------------
        # Disguise Designer 不直接导出 sensor_height，aspectRatio 是 image aspect
        # (w/h)，所以 h = w / aspect。aspect/width 校验已前置在 step 1 之后。
        # build_camera 内部会挂 PostRenderDistortionControllerComponent + 绑
        # M_PRT_OfficialSensorInverse material (Path C distortion 实施层).
        unreal.log("[pipeline] 步骤 2/4 — 创建 CineCameraActor + 挂 DistortionController...")
        camera_actor = build_camera(
            sensor_width_mm=csv_result.sensor_width_mm,
            sensor_height_mm=sensor_height_mm,
            actor_label=f"CineCamera_{stem}",
        )
        unreal.log("[pipeline] CineCameraActor 创建完成 (含 DistortionController).")

        # ------------------------------------------------------------------
        # 步骤 3/4: 构建 LevelSequence (含 7 条 Path C distortion 关键帧轨)
        # ------------------------------------------------------------------
        unreal.log("[pipeline] 步骤 3/4 — 构建 LevelSequence 资产 (含 distortion tracks)...")
        level_sequence = build_sequence(
            csv_result=csv_result,
            camera_actor=camera_actor,
            fps=fps,
            asset_name=f"LS_{stem}",
            package_path=package_path,
        )
        unreal.log("[pipeline] LevelSequence 构建完成 (7 条 distortion 关键帧轨已写).")

        # ------------------------------------------------------------------
        # 步骤 4/4: 生成验证报告
        # ------------------------------------------------------------------
        unreal.log("[pipeline] 步骤 4/4 — 生成验证报告...")
        report = generate_report(csv_result=csv_result, fps=fps)
        unreal.log(report.format_report())

        unreal.log(
            f"[pipeline] 导入成功完成！资产路径: {package_path}"
        )

        return PipelineResult(
            success=True,
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
