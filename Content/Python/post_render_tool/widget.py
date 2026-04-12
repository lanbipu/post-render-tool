"""Widget — VP Post-Render Tool (Designer-driven UI).

The UMG layout is now built manually in the UE Editor Widget Designer.
This module only:

  1. Discovers controls by their Blueprint variable name
     (``host.get_editor_property(name)``)
  2. Binds Python callbacks to the relevant ``on_clicked`` /
     ``on_value_changed`` events
  3. Pushes data into the bound TextBlocks / SpinBoxes when the user
     interacts with the tool

Phase 1 only binds the minimal Browse → Preview → Results loop:

  - ``btn_browse``       (Button)
  - ``txt_file_path``    (TextBlock)
  - ``txt_results``      (MultiLineEditableText)

Add more controls in later phases — see ``_REQUIRED_PHASE1_VARS`` for the
naming contract the Designer template must satisfy.

Only usable inside UE Editor Python environment.
"""

from __future__ import annotations

from typing import Optional

import unreal

from .csv_parser import CsvDenseResult, CsvParseError, parse_csv_dense
from .ui_interface import browse_csv_file


_REQUIRED_PHASE1_VARS = ("btn_browse", "txt_file_path", "txt_results")


class PostRenderToolUI:
    """VP Post-Render Tool — binds a Designer-built EUW template."""

    def __init__(self, host_widget):
        self._host = host_widget

        # State
        self._csv_path: str = ""
        self._csv_result: Optional[CsvDenseResult] = None

        # --- Phase 1 widget refs ---
        self._btn_browse: Optional[unreal.Button] = self._find_widget(
            "btn_browse", unreal.Button
        )
        self._txt_file_path: Optional[unreal.TextBlock] = self._find_widget(
            "txt_file_path", unreal.TextBlock
        )
        self._txt_results = self._find_widget(
            "txt_results", unreal.MultiLineEditableText
        )

        self._bind_phase1()
        self._report_phase1_status()

    # ---------------------------------------------------------------
    # Discovery helpers
    # ---------------------------------------------------------------

    def _find_widget(self, var_name: str, expected_class):
        """Look up a Designer widget variable on the host EUW.

        Returns ``None`` (with a warning) if the variable is missing,
        unbound, or has an unexpected type — never raises, so a partially
        completed Designer template still loads.
        """
        try:
            widget = self._host.get_editor_property(var_name)
        except Exception as exc:
            unreal.log_warning(
                f"[widget] '{var_name}' not exposed on template "
                f"({exc}). Did you tick 'Is Variable' in the Details panel?"
            )
            return None

        if widget is None:
            unreal.log_warning(
                f"[widget] '{var_name}' UPROPERTY exists but is None. "
                "Recompile the EUW after marking it as a variable."
            )
            return None

        if not isinstance(widget, expected_class):
            unreal.log_warning(
                f"[widget] '{var_name}' is a {type(widget).__name__}, "
                f"expected {expected_class.__name__}."
            )
            return None

        return widget

    # ---------------------------------------------------------------
    # Bindings
    # ---------------------------------------------------------------

    def _bind_phase1(self):
        if self._btn_browse is not None:
            # Clear any callbacks left over from a previous PostRenderToolUI
            # instance — rebuild_widget() reuses the same widget instance, so
            # bound methods from the prior reload would otherwise stack and
            # cause N-fold execution per click.
            self._safe_clear_event(self._btn_browse.on_clicked, "btn_browse.on_clicked")
            self._btn_browse.on_clicked.add_callable(self._on_browse_clicked)
            unreal.log("[widget] Bound btn_browse -> _on_browse_clicked")

    def _safe_clear_event(self, multicast_delegate, label: str):
        """Drop every callable bound to a UMG multicast delegate.

        Uses ``clear()`` when available; falls back to no-op with a warning
        on UE builds where the binding is not exposed (the duplicate binding
        will then need a manual widget close/reopen instead of reload).
        """
        try:
            multicast_delegate.clear()
        except AttributeError:
            unreal.log_warning(
                f"[widget] {label}.clear() unavailable on this UE build — "
                "callbacks may stack across reloads. Close & reopen the tab "
                "instead of rebuild_widget()."
            )
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(f"[widget] Failed to clear {label}: {exc}")

    def _report_phase1_status(self):
        missing = []
        for name in _REQUIRED_PHASE1_VARS:
            attr = "_" + name
            if getattr(self, attr, None) is None:
                missing.append(name)
        if missing:
            unreal.log_warning(
                "[widget] Designer template is missing phase-1 controls: "
                + ", ".join(missing)
                + ". The Browse flow will be partially disabled until you add them."
            )
        else:
            unreal.log("[widget] Phase 1 ready — all required controls bound.")

    # ---------------------------------------------------------------
    # Convenience setters (no-op if widget missing)
    # ---------------------------------------------------------------

    def _set_text(self, text_widget, message: str):
        if text_widget is None:
            return
        text_widget.set_text(unreal.Text(message))

    # ---------------------------------------------------------------
    # Browse → Preview → Results
    # ---------------------------------------------------------------

    def _on_browse_clicked(self):
        path = browse_csv_file()
        if not path:
            unreal.log_warning("[widget] Browse cancelled or failed.")
            return

        self._csv_path = path
        self._set_text(self._txt_file_path, path)

        try:
            result = parse_csv_dense(path)
        except CsvParseError as exc:
            self._csv_result = None
            self._set_text(self._txt_results, f"CSV Error: {exc}")
            unreal.log_warning(f"[widget] CSV parse error: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            self._csv_result = None
            self._set_text(self._txt_results, f"Error: {exc}")
            unreal.log_error(f"[widget] Preview error: {exc}")
            return

        self._csv_result = result
        fl_min, fl_max = result.focal_length_range
        detected = (
            f"{result.detected_fps} fps"
            if result.detected_fps is not None
            else "N/A"
        )
        report = (
            f"CSV loaded: {path}\n"
            f"Frames:        {result.frame_count}\n"
            f"Focal length:  {fl_min:.2f} - {fl_max:.2f} mm\n"
            f"Timecode:      {result.timecode_start} -> {result.timecode_end}\n"
            f"Sensor width:  {result.sensor_width_mm:.2f} mm\n"
            f"Detected FPS:  {detected}"
        )
        self._set_text(self._txt_results, report)
        unreal.log(f"[widget] CSV preview loaded: {path}")
