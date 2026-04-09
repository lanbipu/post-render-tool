"""UI Interface — VP Post-Render Tool.

Blueprint-callable Python functions for the VP Post-Render Tool UI.
Each public function returns a JSON string for easy Blueprint parsing.

Only usable inside UE Editor Python environment.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import unreal

from .csv_parser import CsvDenseResult, CsvParseError, parse_csv_dense
from .pipeline import PipelineResult, run_import

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared UI state singleton
# ---------------------------------------------------------------------------

class UIState:
    """Singleton holding shared UI state between Blueprint calls."""

    _instance: Optional["UIState"] = None

    def __init__(self) -> None:
        self.csv_path: str = ""
        self.csv_preview: dict = {}
        self.fps: float = 0.0
        self.last_result: Optional[PipelineResult] = None

    @classmethod
    def get(cls) -> "UIState":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ok(data: dict) -> str:
    return json.dumps({"success": True, **data}, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"success": False, "error": message}, ensure_ascii=False)


def _preview_from_result(result: CsvDenseResult) -> dict:
    """Build the preview dict from a CsvDenseResult."""
    fl_min, fl_max = result.focal_length_range
    return {
        "frame_count": result.frame_count,
        "timecode_start": result.timecode_start,
        "timecode_end": result.timecode_end,
        "focal_length_min": round(fl_min, 4),
        "focal_length_max": round(fl_max, 4),
        "sensor_width_mm": round(result.sensor_width_mm, 4),
        "detected_fps": result.detected_fps,
        "camera_prefix": result.camera_prefix,
    }


# ---------------------------------------------------------------------------
# Public API — Blueprint callable
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


def load_csv_preview(csv_path: str) -> str:
    """Parse CSV header/data without running the full import pipeline.

    Parameters
    ----------
    csv_path:
        Absolute path to the Disguise Designer CSV Dense file.

    Returns
    -------
    str
        JSON: ``{"success": true, "data": {...}}`` or
        ``{"success": false, "error": "..."}``
    """
    if not csv_path:
        return _err("csv_path is empty")

    try:
        result: CsvDenseResult = parse_csv_dense(csv_path)
        preview = _preview_from_result(result)

        state = UIState.get()
        state.csv_path = csv_path
        state.csv_preview = preview

        unreal.log(f"[ui_interface] CSV preview loaded: {csv_path}")
        return _ok({"data": preview})

    except CsvParseError as exc:
        msg = f"CSV parse error: {exc}"
        unreal.log_warning(f"[ui_interface] {msg}")
        return _err(msg)

    except FileNotFoundError as exc:
        msg = f"File not found: {exc}"
        unreal.log_warning(f"[ui_interface] {msg}")
        return _err(msg)

    except Exception as exc:  # noqa: BLE001
        msg = f"Unexpected error [{type(exc).__name__}]: {exc}"
        unreal.log_error(f"[ui_interface] {msg}")
        return _err(msg)


def execute_import(csv_path: str, fps: float = 0.0) -> str:
    """Run the full import pipeline and return a JSON result string.

    Parameters
    ----------
    csv_path:
        Absolute path to the CSV Dense file.
    fps:
        Target frame rate. Pass 0.0 to auto-detect from CSV.

    Returns
    -------
    str
        JSON: ``{"success": true, "report": "...", "asset_path": "..."}`` or
        ``{"success": false, "error": "..."}``
    """
    if not csv_path:
        return _err("csv_path is empty")

    unreal.log(f"[ui_interface] execute_import: {csv_path}, fps={fps}")

    pipeline_result: PipelineResult = run_import(csv_path, fps)

    state = UIState.get()
    state.last_result = pipeline_result
    state.csv_path = csv_path
    state.fps = fps

    if pipeline_result.success:
        report_text = (
            pipeline_result.report.format_report()
            if pipeline_result.report is not None
            else ""
        )
        return _ok({
            "report": report_text,
            "asset_path": pipeline_result.package_path,
        })
    else:
        return _err(pipeline_result.error_message)


def open_sequencer() -> None:
    """Open the Sequencer editor for the last imported LevelSequence.

    Uses ``unreal.LevelSequenceEditorSubsystem``.
    Does nothing if no LevelSequence has been created yet.
    """
    state = UIState.get()
    if state.last_result is None or state.last_result.level_sequence is None:
        unreal.log_warning(
            "[ui_interface] open_sequencer: no LevelSequence available. "
            "Run execute_import first."
        )
        return

    try:
        subsystem = unreal.get_editor_subsystem(unreal.LevelSequenceEditorSubsystem)
        subsystem.open_level_sequence(state.last_result.level_sequence)
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
# cmd_* one-liner helpers (callable from Blueprint as single strings)
# ---------------------------------------------------------------------------

def cmd_browse() -> str:
    """Browse for a CSV file, load its preview, and return JSON result.

    Combines ``browse_csv_file()`` + ``load_csv_preview()``.

    Returns
    -------
    str
        JSON with ``{"success": true, "csv_path": "...", "data": {...}}`` or
        ``{"success": false, "error": "..."}``
    """
    csv_path = browse_csv_file()
    if not csv_path:
        return _err("No file selected")

    preview_json = load_csv_preview(csv_path)
    preview_data: dict = json.loads(preview_json)

    if not preview_data.get("success"):
        return preview_json  # propagate the error as-is

    return json.dumps(
        {
            "success": True,
            "csv_path": csv_path,
            "data": preview_data.get("data", {}),
        },
        ensure_ascii=False,
    )


def cmd_import(csv_path: str, fps: float = 0.0) -> str:
    """Execute the full import pipeline and return JSON result.

    Thin wrapper around ``execute_import()`` for one-liner Blueprint calls.

    Parameters
    ----------
    csv_path:
        Absolute path to the CSV Dense file.
    fps:
        Target frame rate; 0.0 = auto-detect.

    Returns
    -------
    str
        JSON string (same schema as ``execute_import``).
    """
    return execute_import(csv_path, fps)
