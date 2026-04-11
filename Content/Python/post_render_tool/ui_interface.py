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
import tempfile
from typing import List, Tuple

import unreal


# ---------------------------------------------------------------------------
# Public utilities
# ---------------------------------------------------------------------------

def browse_csv_file() -> str:
    """Open a native file-picker dialog and return the chosen CSV path.

    Returns
    -------
    str
        The selected absolute file path, or an empty string if the user
        cancelled or the dialog is unavailable.
    """
    try:
        dialog_title = "Select Disguise Designer CSV Dense File"
        default_path = ""
        default_file = ""
        file_types = "CSV Files (*.csv)|*.csv"

        # unreal.DesktopPlatformBlueprintLibrary is available in Editor builds.
        result = unreal.DesktopPlatformBlueprintLibrary.open_file_dialog(
            dialog_title,
            default_path,
            default_file,
            file_types,
            False,  # bAllowMultiSelect
        )

        # The API returns (bool_success, [file_paths]).
        # In some UE versions it returns just a list or a struct — handle both.
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            # (success_bool, [paths]) form
            _success_flag = result[0]
            paths = result[1]
            if isinstance(paths, (list, tuple)) and len(paths) > 0:
                return str(paths[0])
        elif isinstance(result, (list, tuple)) and len(result) == 1:
            # bare [path] form (some wrappers)
            return str(result[0])

        return ""

    except AttributeError:
        # Fallback: try the AppReturnType / slate dialog approach (older UE).
        try:
            paths = unreal.AppReturnType.open_file_dialog(
                "Select CSV",
                "",
                "",
                "CSV Files (*.csv)|*.csv",
                False,
            )
            if paths:
                return str(paths[0])
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(f"[ui_interface] browse_csv_file fallback failed: {exc}")

        return ""

    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(f"[ui_interface] browse_csv_file error: {exc}")
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
        subsystem = unreal.get_editor_subsystem(unreal.LevelSequenceEditorSubsystem)
        subsystem.open_level_sequence(level_sequence)
        unreal.log("[ui_interface] Sequencer opened.")
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"[ui_interface] open_sequencer error: {exc}")


def open_movie_render_queue() -> None:
    """Open the Movie Render Queue editor window."""
    try:
        # Try the subsystem approach (UE 5.x preferred).
        subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineEditorLibrary)
        subsystem.open_queue()
    except Exception:  # noqa: BLE001
        try:
            # Fallback: execute editor command to open the MRQ tab.
            unreal.SystemLibrary.execute_console_command(
                None,
                "MovieRenderPipeline.OpenQueue",
            )
            unreal.log("[ui_interface] Movie Render Queue opened via console command.")
        except Exception as exc2:  # noqa: BLE001
            unreal.log_error(f"[ui_interface] open_movie_render_queue error: {exc2}")


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
    ("Camera Calibration", "LensFile",
     "Edit > Plugins > search 'Camera Calibration' > Enable > Restart"),
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
# Test camera
# ---------------------------------------------------------------------------

_TEST_CAMERA_LABEL = "TestCam_PostRender"
_TEST_CAMERA_TAG = "PostRenderTool_TestCam"


def spawn_test_camera(
    ue_x: float,
    ue_y: float,
    ue_z: float,
    pitch: float,
    yaw: float,
    roll: float,
    sensor_width_mm: float = 35.0,
    label: str = _TEST_CAMERA_LABEL,
) -> object:
    """Spawn a CineCameraActor at the given UE coordinates and pilot to it.

    If a previous test camera created by this tool exists it is replaced.
    Ownership is tracked via the actor tag ``PostRenderTool_TestCam``, not
    the editable label, so user-created actors with the same display name
    are never touched.

    Returns
    -------
    unreal.CineCameraActor
        The spawned actor.
    """
    location = unreal.Vector(ue_x, ue_y, ue_z)
    rotation = unreal.Rotator(pitch, yaw, roll)

    # Create new camera FIRST — only clean up old one after success
    camera = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CineCameraActor, location, rotation
    )
    camera.set_actor_label(label)
    camera.tags.append(_TEST_CAMERA_TAG)

    # Configure sensor width
    comp = camera.get_cine_camera_component()
    filmback = comp.filmback
    filmback.sensor_width = sensor_width_mm
    comp.filmback = filmback

    # Now that the new camera exists, remove any previous test camera
    # identified by our ownership tag (not by label)
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if actor == camera:
            continue
        if _TEST_CAMERA_TAG in actor.tags:
            actor.destroy_actor()

    # Pilot the viewport to this camera
    try:
        unreal.EditorLevelLibrary.pilot_level_actor(camera)
        unreal.log(f"[ui_interface] Test camera spawned and piloted: {label}")
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(
            f"[ui_interface] Camera spawned but pilot failed: {exc}. "
            "Right-click the camera in Outliner > Pilot."
        )

    return camera


# ---------------------------------------------------------------------------
# Axis mapping persistence
# ---------------------------------------------------------------------------

def save_axis_mapping(
    pos_mapping: dict,
    rot_mapping: dict,
    config_path: str | None = None,
) -> None:
    """Write POSITION_MAPPING and ROTATION_MAPPING back to config.py.

    Parameters
    ----------
    pos_mapping:
        ``{"x": (idx, scale), "y": ..., "z": ...}``
    rot_mapping:
        ``{"pitch": (idx, scale), "yaw": ..., "roll": ...}``
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
