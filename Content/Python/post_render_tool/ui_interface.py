"""UI Interface — VP Post-Render Tool.

Lightweight utility functions for the VP Post-Render Tool widget.
All UI state and pipeline orchestration is handled by widget.py.

Only usable inside UE Editor Python environment.
"""

from __future__ import annotations

import ast
import importlib
import os
import re
import subprocess
import sys
import tempfile
from typing import List, Tuple

import unreal


# ---------------------------------------------------------------------------
# Public utilities
# ---------------------------------------------------------------------------

_DIALOG_TITLE = "Select Disguise Designer CSV Dense File"


def browse_csv_file() -> str:
    """Open a native file-picker dialog and return the chosen CSV path.

    UE 5.7 does not expose ``DesktopPlatformBlueprintLibrary`` to Python by
    default, so this function uses platform-native fallbacks:

    1. ``unreal.DesktopPlatformBlueprintLibrary`` if it happens to be present
    2. macOS: ``osascript`` ``choose file`` dialog
    3. ``tkinter.filedialog`` (cross-platform, requires Tk to be importable)

    Returns
    -------
    str
        The selected absolute file path, or an empty string if the user
        cancelled or every backend failed.
    """
    # Backend 1 — UE BP library, if available in this build.
    if hasattr(unreal, "DesktopPlatformBlueprintLibrary"):
        try:
            result = unreal.DesktopPlatformBlueprintLibrary.open_file_dialog(
                _DIALOG_TITLE,
                "",
                "",
                "CSV Files (*.csv)|*.csv",
                False,
            )
            path = _extract_first_path(result)
            if path:
                return path
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(
                f"[ui_interface] DesktopPlatformBlueprintLibrary failed: {exc}"
            )

    # Backend 2 — macOS native dialog via osascript.
    if sys.platform == "darwin":
        path = _browse_via_osascript()
        if path:
            return path

    # Backend 3 — tkinter fallback.
    path = _browse_via_tkinter()
    if path:
        return path

    return ""


def _extract_first_path(result) -> str:
    """Normalize the various return shapes of open_file_dialog into a path."""
    if isinstance(result, (list, tuple)) and len(result) >= 2:
        paths = result[1]
        if isinstance(paths, (list, tuple)) and len(paths) > 0:
            return str(paths[0])
    elif isinstance(result, (list, tuple)) and len(result) == 1:
        return str(result[0])
    return ""


def _browse_via_osascript() -> str:
    """macOS: invoke `choose file` via osascript and return POSIX path."""
    script = (
        f'POSIX path of (choose file with prompt "{_DIALOG_TITLE}" '
        'of type {"csv", "public.comma-separated-values-text"})'
    )
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError:
        unreal.log_warning("[ui_interface] osascript not available on this machine.")
        return ""
    except subprocess.TimeoutExpired:
        unreal.log_warning("[ui_interface] osascript file dialog timed out.")
        return ""

    if proc.returncode != 0:
        # User cancelled (-128) is the common case — stay silent.
        stderr = (proc.stderr or "").strip()
        if stderr and "User canceled" not in stderr and "-128" not in stderr:
            unreal.log_warning(f"[ui_interface] osascript error: {stderr}")
        return ""

    return (proc.stdout or "").strip()


def _browse_via_tkinter() -> str:
    """Cross-platform Tk file dialog. Returns "" if Tk is unusable."""
    try:
        import tkinter
        from tkinter import filedialog
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(f"[ui_interface] tkinter unavailable: {exc}")
        return ""

    try:
        root = tkinter.Tk()
        root.withdraw()
        root.update_idletasks()
        path = filedialog.askopenfilename(
            title=_DIALOG_TITLE,
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        root.destroy()
        return path or ""
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(f"[ui_interface] tkinter dialog failed: {exc}")
        return ""


def open_sequencer(level_sequence=None) -> None:
    """Open the Sequencer editor for a given LevelSequence.

    Parameters
    ----------
    level_sequence:
        The LevelSequence asset to open. If None, does nothing.
    """
    if level_sequence is None:
        unreal.log_warning(
            "[ui_interface] open_sequencer: no LevelSequence provided."
        )
        return

    try:
        # UE 5.7: OpenLevelSequence 是 ULevelSequenceEditorBlueprintLibrary 的静态
        # UFUNCTION（LevelSequenceEditorBlueprintLibrary.h:35-36），不在 subsystem 上。
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(level_sequence)
        unreal.log("[ui_interface] Sequencer opened.")
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"[ui_interface] open_sequencer error: {exc}")


def open_movie_render_queue(level_sequence=None) -> None:
    """把 LevelSequence 预填到 MRQ queue + 配 absolute CSV frame 文件名,
    并打印手动打开指引。

    UE 5.7 未暴露 FGlobalTabmanager::TryInvokeTab 到 Python，脚本无法直接
    打开 MRQ tab；此函数仅做 queue 预填 + 人工操作指引。
    """
    if level_sequence is not None:
        try:
            queue_subsystem = unreal.get_editor_subsystem(
                unreal.MoviePipelineQueueSubsystem
            )
            if queue_subsystem is None:
                unreal.log_warning(
                    "[ui_interface] MoviePipelineQueueSubsystem 不可用"
                )
            else:
                queue = queue_subsystem.get_queue()
                job = unreal.MoviePipelineEditorLibrary.create_job_from_sequence(
                    queue, level_sequence
                )
                if job is not None:
                    unreal.MoviePipelineEditorLibrary.ensure_job_has_default_settings(
                        job
                    )
                    configured = _apply_csv_frame_filename_offset(
                        job, level_sequence
                    )
                    if configured:
                        unreal.log(
                            f"[ui_interface] 已把 {level_sequence.get_name()} "
                            "添加到 MRQ queue (FrameNumberOffset 已配, "
                            "请不要在 MRQ UI 删除 {frame_number} token)"
                        )
                    else:
                        unreal.log(
                            f"[ui_interface] 已把 {level_sequence.get_name()} "
                            "添加到 MRQ queue (未配 FrameNumberOffset — "
                            "见上方 warning)"
                        )
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(f"[ui_interface] MRQ queue 预填失败: {exc}")

    unreal.log(
        "[ui_interface] 请手动打开 Movie Render Queue: "
        "菜单 Window → Cinematics → Movie Render Queue"
    )


def _apply_csv_frame_filename_offset(job, level_sequence) -> bool:
    """配 MRQ output 让渲出的文件名带 absolute CSV frame number.

    从 LevelSequence 关联的 UPostRenderCameraSamples DataAsset 读
    source_frame_numbers[0] / [-1], 设给 UMoviePipelineOutputSetting:
      - FrameNumberOffset = first_csv_frame   (MRQ 把 {frame_number}
        token 加上 offset, 见 MoviePipelineBlueprintLibrary.cpp:1059)
      - ZeroPadFrameNumbers = max(7, len(str(last_csv_frame)))   动态算
        宽度防 7→8 位跨越导致文件名排序错乱
      - FileNameFormat: 现有 default 若已含 `{frame_number}` token 则
        保留 (e.g. 用户可能预设了 "{sequence_name}/render.{frame_number}"),
        否则覆盖成 "render.{frame_number}"

    UE 5.7 MoviePipelineOutputSetting.h:101 frame_number_offset UPROPERTY
    标记 BlueprintReadWrite, Python 原生可见。

    Returns:
        True 若 frame_number_offset 配置完成, False 若 LevelSequence
        缺 UPostRenderCameraTrack / sample asset。
    """
    config = job.get_configuration()
    output_setting = config.find_or_add_setting_by_class(
        unreal.MoviePipelineOutputSetting
    )

    bounds = _find_csv_frame_bounds_from_sequence(level_sequence)
    if bounds is None:
        unreal.log_warning(
            "[ui_interface] 未找到 UPostRenderCameraSamples DataAsset, "
            "跳过 FrameNumberOffset 配置 — MRQ 文件名用默认 0 起的"
        )
        return False

    first_frame, last_frame = bounds
    padding = max(7, len(str(int(last_frame))))

    output_setting.set_editor_property("frame_number_offset", int(first_frame))
    output_setting.set_editor_property("zero_pad_frame_numbers", padding)

    # 只在 default 不含 {frame_number} token 时覆盖, 保留用户可能的
    # 自定义 path prefix / sequence name token。
    current_format = ""
    try:
        current_format = str(output_setting.get_editor_property("file_name_format"))
    except Exception:  # noqa: BLE001
        current_format = ""
    if "{frame_number}" not in current_format:
        output_setting.set_editor_property(
            "file_name_format", "render.{frame_number}"
        )
        unreal.log(
            f"[ui_interface] MRQ output: FrameNumberOffset={first_frame}, "
            f"FileNameFormat=render.{{frame_number}} ({padding}-digit pad)"
        )
    else:
        unreal.log(
            f"[ui_interface] MRQ output: FrameNumberOffset={first_frame}, "
            f"FileNameFormat preserved ({current_format!r}), pad={padding}"
        )
    return True


def _find_csv_frame_bounds_from_sequence(level_sequence):
    """遍历 sequence bindings → UPostRenderCameraTrack → sections →
    sample_asset 拿 (first, last) CSV frame numbers.

    返回 None 当 sequence 没挂 plugin 的 custom track / 没有 sample。

    `unreal.PostRenderCameraTrack` 在 plugin runtime 没暴露成 Python
    class symbol (只反射 base UMovieSceneTrack), 所以走 get_class()
    name 字符串匹配。如果未来 C++ 改 class 名,这里会静默 fall through;
    `unreal_get_class_name()` 任何异常都 log warning 而不是静默, 让
    误判暴露。
    """
    try:
        bindings = level_sequence.get_bindings()
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(
            f"[ui_interface] level_sequence.get_bindings() 抛错: {exc} — "
            "MRQ FrameNumberOffset 配置跳过"
        )
        return None

    for binding in bindings:
        try:
            tracks = binding.get_tracks()
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(
                f"[ui_interface] binding.get_tracks() 抛错: {exc}"
            )
            continue
        for track in tracks:
            try:
                cls_name = track.get_class().get_name()
            except Exception as exc:  # noqa: BLE001
                unreal.log_warning(
                    f"[ui_interface] track.get_class().get_name() 抛错: {exc}"
                )
                continue
            if cls_name != "PostRenderCameraTrack":
                continue
            for section in track.get_sections():
                sample_asset = section.get_editor_property("sample_asset")
                if sample_asset is None:
                    continue
                frame_numbers = sample_asset.source_frame_numbers
                if frame_numbers:
                    return int(frame_numbers[0]), int(frame_numbers[-1])
    return None


# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

_PREREQUISITE_CHECKS: List[Tuple[str, str, str]] = [
    # Python Editor Script Plugin: if we're running Python, it's loaded.
    # Use empty string as sentinel — get_prerequisite_status() handles it.
    ("Python Editor Script Plugin", "",
     "Edit > Plugins > search 'Python Editor Script' > Enable > Restart"),
    ("Editor Scripting Utilities", "EditorAssetLibrary",
     "Edit > Plugins > search 'Editor Scripting' > Enable > Restart"),
    # Camera Calibration / LensFile 已不再需要 (Path A 下架, 2026-05-08).
    # Distortion 走 Path C Custom Post-Process Material, 不依赖 CameraCalibrationCore 模块.
    ("CineCameraActor", "CineCameraActor", ""),
    ("LevelSequence", "LevelSequence",
     "Edit > Plugins > search 'Level Sequence Editor' > Enable > Restart"),
    ("EditorUtilitySubsystem", "EditorUtilitySubsystem", ""),
]


def get_prerequisite_status() -> List[Tuple[str, bool, str]]:
    """Check required plugins/classes and return structured results.

    Returns
    -------
    list[tuple[str, bool, str]]
        Each entry is ``(display_name, is_ok, fix_hint)``.
    """
    results: List[Tuple[str, bool, str]] = []
    for name, class_name, hint in _PREREQUISITE_CHECKS:
        if not class_name:
            # Empty class_name means always OK (e.g., Python plugin — if
            # this code is running, the plugin is loaded).
            ok = True
        else:
            ok = hasattr(unreal, class_name)
        results.append((name, ok, hint))
    return results


# ---------------------------------------------------------------------------
# Axis mapping persistence
# ---------------------------------------------------------------------------

def save_axis_mapping(
    pos_mapping: dict,
    rot_mapping: dict,
    rot_offset: dict,
    config_path: str | None = None,
) -> None:
    """Write POSITION_MAPPING, ROTATION_MAPPING and ROTATION_OFFSET_DEG back to config.py.

    Parameters
    ----------
    pos_mapping:
        ``{"x": (idx, scale), "y": ..., "z": ...}``
    rot_mapping:
        ``{"pitch": (idx, scale), "yaw": ..., "roll": ...}``
    rot_offset:
        ``{"pitch": float_deg, "yaw": float_deg, "roll": float_deg}``
    config_path:
        Absolute path to config.py. If None, derived from the config module.
    """
    from . import config

    if config_path is None:
        config_path = os.path.abspath(config.__file__)
    if config_path.endswith(".pyc"):
        config_path = config_path[:-1]

    with open(config_path, "r", encoding="utf-8") as fh:
        source = fh.read()

    axis_labels = {0: "X", 1: "Y", 2: "Z"}

    # Build POSITION_MAPPING replacement
    pos_lines = []
    for key in ("x", "y", "z"):
        idx, scale = pos_mapping[key]
        src = axis_labels.get(idx, str(idx))
        pos_lines.append(
            f'    "{key}": ({idx}, {scale}),  '
            f"# UE.{key.upper()} <- Designer.{src} * {scale}"
        )
    pos_block = "POSITION_MAPPING = {\n" + "\n".join(pos_lines) + "\n}"

    # Build ROTATION_MAPPING replacement
    rot_lines = []
    for key in ("pitch", "yaw", "roll"):
        idx, scale = rot_mapping[key]
        src = axis_labels.get(idx, str(idx))
        rot_lines.append(
            f'    "{key}": ({idx}, {scale}),  '
            f"# UE.{key.capitalize()} <- Designer.rot_{src} * {scale}"
        )
    rot_block = "ROTATION_MAPPING = {\n" + "\n".join(rot_lines) + "\n}"

    # Build ROTATION_OFFSET_DEG replacement (degrees, applied after mapping)
    off_lines = []
    for key in ("pitch", "yaw", "roll"):
        value = float(rot_offset[key])
        off_lines.append(
            f'    "{key}": {value},  '
            f"# UE.{key.capitalize()} += {value}°"
        )
    off_block = "ROTATION_OFFSET_DEG = {\n" + "\n".join(off_lines) + "\n}"

    # Replace in source (with match validation)
    new_source = re.sub(
        r"POSITION_MAPPING\s*=\s*\{[^}]*\}",
        pos_block,
        source,
        count=1,
    )
    if new_source == source:
        raise RuntimeError("POSITION_MAPPING block not found in config.py")
    source = new_source

    new_source = re.sub(
        r"ROTATION_MAPPING\s*=\s*\{[^}]*\}",
        rot_block,
        source,
        count=1,
    )
    if new_source == source:
        raise RuntimeError("ROTATION_MAPPING block not found in config.py")
    source = new_source

    new_source = re.sub(
        r"ROTATION_OFFSET_DEG\s*=\s*\{[^}]*\}",
        off_block,
        source,
        count=1,
    )
    if new_source == source:
        # Legacy config.py (pre-offset installations) doesn't have the block —
        # insert it right after ROTATION_MAPPING instead of failing. re.sub
        # above already replaced ROTATION_MAPPING with the new rot_block, so
        # we anchor on the freshly-written block in `source`.
        anchor = re.search(r"ROTATION_MAPPING\s*=\s*\{[^}]*\}", source)
        if anchor is None:
            raise RuntimeError(
                "Cannot insert ROTATION_OFFSET_DEG: ROTATION_MAPPING anchor missing"
            )
        end = anchor.end()
        insertion = (
            "\n\n# Per-axis rotation offset (degrees), applied AFTER the mapping above.\n"
            + off_block
        )
        source = source[:end] + insertion + source[end:]
    else:
        source = new_source

    # Validate syntax before writing — never corrupt config.py
    try:
        ast.parse(source)
    except SyntaxError as exc:
        raise RuntimeError(
            f"Generated config.py has invalid syntax (bug in save_axis_mapping): {exc}"
        ) from exc

    # Atomic write: temp file → validate → backup → os.replace()
    config_dir = os.path.dirname(config_path)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".py", prefix=".config_tmp_", dir=config_dir
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(source)

        # Create .bak backup of the original
        bak_path = config_path + ".bak"
        try:
            if os.path.exists(config_path):
                # Copy rather than rename — we need the original in place
                # until os.replace atomically swaps it
                import shutil
                shutil.copy2(config_path, bak_path)
        except OSError:
            pass  # best-effort backup

        # Atomic replace
        os.replace(tmp_path, config_path)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Reload config module so in-memory state matches disk
    importlib.reload(config)
    unreal.log(f"[ui_interface] Axis mapping saved to {config_path}")
