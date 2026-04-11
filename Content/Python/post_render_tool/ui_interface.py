"""UI Interface — VP Post-Render Tool.

Lightweight utility functions for the VP Post-Render Tool widget.
All UI state and pipeline orchestration is handled by widget.py.

Only usable inside UE Editor Python environment.
"""

from __future__ import annotations

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
