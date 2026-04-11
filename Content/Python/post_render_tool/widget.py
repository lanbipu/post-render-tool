"""Widget — VP Post-Render Tool.

Python-based EditorUtilityWidget that builds the full UI at runtime.
Only usable inside UE Editor Python environment.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import unreal

from .csv_parser import CsvParseError, parse_csv_dense
from .pipeline import PipelineResult, run_import
from .ui_interface import browse_csv_file, open_sequencer, open_movie_render_queue

logger = logging.getLogger(__name__)


@unreal.uclass()
class OPostRenderToolWidget(unreal.EditorUtilityWidget):
    """VP Post-Render Tool Editor Utility Widget.

    Programmatically builds the UMG layout in construct() and handles
    all user interactions (browse, import, open sequencer, open MRQ).
    """

    # ---------------------------------------------------------------
    # State
    # ---------------------------------------------------------------
    _csv_path: str = ""
    _fps: float = 24.0
    _last_result: Optional[PipelineResult] = None

    # Widget references (populated in _build_ui)
    _txt_file_path: Optional[unreal.TextBlock] = None
    _txt_detected_fps: Optional[unreal.TextBlock] = None
    _txt_frame_count: Optional[unreal.TextBlock] = None
    _txt_focal_range: Optional[unreal.TextBlock] = None
    _txt_timecode: Optional[unreal.TextBlock] = None
    _txt_sensor_width: Optional[unreal.TextBlock] = None
    _txt_results: Optional[unreal.MultiLineEditableText] = None
    _spn_fps: Optional[unreal.SpinBox] = None
    _btn_import: Optional[unreal.Button] = None
    _btn_open_seq: Optional[unreal.Button] = None
    _btn_open_mrq: Optional[unreal.Button] = None

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    @unreal.ufunction(override=True)
    def construct(self):
        """Called when the widget is initialized. Builds the full UI."""
        self._build_ui()

    # ---------------------------------------------------------------
    # UI Construction
    # ---------------------------------------------------------------

    def _build_ui(self):
        """Build the entire UMG widget tree dynamically."""
        root = self._make_widget(unreal.VerticalBox)
        self.set_content(root)

        # --- Title ---
        title = self._make_text("VP Post-Render Tool", size=18, is_bold=True)
        root.add_child(title)
        self._add_spacer(root, 12.0)

        # --- CSV File Row ---
        file_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(file_row)

        lbl_file = self._make_text("CSV File: ")
        file_row.add_child(lbl_file)

        self._txt_file_path = self._make_text(
            "No file selected", color=unreal.SlateColor(unreal.LinearColor(0.5, 0.5, 0.5, 1.0))
        )
        file_row.add_child(self._txt_file_path)
        slot = self._txt_file_path.slot
        if hasattr(slot, 'set_editor_property'):
            try:
                slot.set_editor_property("size", unreal.SlateChildSize(1.0))
            except Exception:
                pass

        btn_browse = self._make_button("Browse...", self._on_browse_clicked)
        file_row.add_child(btn_browse)

        self._add_spacer(root, 8.0)

        # --- FPS Row ---
        fps_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(fps_row)

        lbl_fps = self._make_text("FPS: ")
        fps_row.add_child(lbl_fps)

        self._spn_fps = self._make_widget(unreal.SpinBox)
        self._spn_fps.set_editor_property("min_value", 1.0)
        self._spn_fps.set_editor_property("max_value", 120.0)
        self._spn_fps.set_editor_property("value", 24.0)
        self._spn_fps.on_value_changed.add_callable(self._on_fps_changed)
        fps_row.add_child(self._spn_fps)

        self._txt_detected_fps = self._make_text("Auto: --", color=unreal.SlateColor(
            unreal.LinearColor(0.5, 0.5, 0.5, 1.0)
        ))
        fps_row.add_child(self._txt_detected_fps)

        self._add_spacer(root, 8.0)

        # --- Preview Section ---
        preview_header = self._make_text("── CSV Preview ──")
        root.add_child(preview_header)

        self._txt_frame_count = self._make_text("Frames: —")
        root.add_child(self._txt_frame_count)

        self._txt_focal_range = self._make_text("Focal Length: —")
        root.add_child(self._txt_focal_range)

        self._txt_timecode = self._make_text("Timecode: —")
        root.add_child(self._txt_timecode)

        self._txt_sensor_width = self._make_text("Sensor Width: —")
        root.add_child(self._txt_sensor_width)

        self._add_spacer(root, 12.0)

        # --- Import Button ---
        self._btn_import = self._make_button("Import", self._on_import_clicked)
        root.add_child(self._btn_import)

        self._add_spacer(root, 8.0)

        # --- Results Area ---
        lbl_results = self._make_text("── Results ──")
        root.add_child(lbl_results)

        self._txt_results = self._make_widget(unreal.MultiLineEditableText)
        self._txt_results.set_editor_property("is_read_only", True)
        self._txt_results.set_text(unreal.Text(""))
        root.add_child(self._txt_results)

        self._add_spacer(root, 8.0)

        # --- Action Buttons Row ---
        action_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(action_row)

        self._btn_open_seq = self._make_button("Open Sequencer", self._on_open_sequencer_clicked)
        action_row.add_child(self._btn_open_seq)

        self._btn_open_mrq = self._make_button("Open Movie Render Queue", self._on_open_mrq_clicked)
        action_row.add_child(self._btn_open_mrq)

    # ---------------------------------------------------------------
    # Widget Factory Helpers
    # ---------------------------------------------------------------

    def _make_widget(self, widget_class):
        """Create a UMG widget owned by this widget's outer."""
        try:
            return unreal.create_widget(self, widget_class)
        except Exception:
            return widget_class()

    def _make_text(self, text: str, size: int = 0, is_bold: bool = False,
                   color=None) -> unreal.TextBlock:
        """Create a TextBlock with optional styling."""
        tb = self._make_widget(unreal.TextBlock)
        tb.set_text(unreal.Text(text))
        if size > 0 or is_bold:
            font = tb.get_editor_property("font")
            if size > 0:
                font.size = size
            if is_bold:
                font.typeface_font_name = "Bold"
            tb.set_editor_property("font", font)
        if color is not None:
            tb.set_editor_property("color_and_opacity", color)
        return tb

    def _make_button(self, label: str, callback) -> unreal.Button:
        """Create a Button with a TextBlock child and an OnClicked callback."""
        btn = self._make_widget(unreal.Button)
        btn_text = self._make_text(label)
        btn.add_child(btn_text)
        btn.on_clicked.add_callable(callback)
        return btn

    def _add_spacer(self, parent, height: float):
        """Add a Spacer widget to a panel."""
        spacer = self._make_widget(unreal.Spacer)
        parent.add_child(spacer)
        slot = spacer.slot
        if hasattr(slot, 'set_editor_property'):
            try:
                slot.set_editor_property("size", unreal.Vector2D(0, height))
            except Exception:
                pass

    # ---------------------------------------------------------------
    # Event Handlers
    # ---------------------------------------------------------------

    def _on_browse_clicked(self):
        """Handle Browse button: open file dialog and load CSV preview."""
        csv_path = browse_csv_file()
        if not csv_path:
            unreal.log_warning("[widget] No file selected.")
            return

        self._csv_path = csv_path
        self._txt_file_path.set_text(unreal.Text(csv_path))

        try:
            result = parse_csv_dense(csv_path)
            fl_min, fl_max = result.focal_length_range
            self._txt_frame_count.set_text(unreal.Text(f"Frames: {result.frame_count}"))
            self._txt_focal_range.set_text(
                unreal.Text(f"Focal Length: {fl_min:.2f} – {fl_max:.2f} mm")
            )
            self._txt_timecode.set_text(
                unreal.Text(f"Timecode: {result.timecode_start} → {result.timecode_end}")
            )
            self._txt_sensor_width.set_text(
                unreal.Text(f"Sensor Width: {result.sensor_width_mm:.2f} mm")
            )
            if result.detected_fps is not None:
                self._txt_detected_fps.set_text(
                    unreal.Text(f"Auto: {result.detected_fps} fps")
                )
            else:
                self._txt_detected_fps.set_text(unreal.Text("Auto: N/A"))

            unreal.log(f"[widget] CSV preview loaded: {csv_path}")

        except CsvParseError as exc:
            self._txt_results.set_text(unreal.Text(f"CSV Error: {exc}"))
            unreal.log_warning(f"[widget] CSV parse error: {exc}")
        except Exception as exc:
            self._txt_results.set_text(unreal.Text(f"Error: {exc}"))
            unreal.log_error(f"[widget] Preview error: {exc}")

    def _on_fps_changed(self, value: float):
        """Handle FPS SpinBox value change."""
        self._fps = value

    def _on_import_clicked(self):
        """Handle Import button: run the full pipeline."""
        if not self._csv_path:
            self._txt_results.set_text(unreal.Text("Error: No CSV file selected. Click Browse first."))
            return

        self._txt_results.set_text(unreal.Text("Importing..."))

        fps = self._fps if self._fps > 0 else 0.0
        pipeline_result = run_import(self._csv_path, fps)
        self._last_result = pipeline_result

        if pipeline_result.success:
            report_text = (
                pipeline_result.report.format_report()
                if pipeline_result.report is not None
                else "Import successful (no report generated)."
            )
            self._txt_results.set_text(unreal.Text(report_text))
            unreal.log(f"[widget] Import successful: {pipeline_result.package_path}")
        else:
            self._txt_results.set_text(unreal.Text(f"Import Failed:\n{pipeline_result.error_message}"))
            unreal.log_error(f"[widget] Import failed: {pipeline_result.error_message}")

    def _on_open_sequencer_clicked(self):
        """Handle Open Sequencer button."""
        if self._last_result is None or self._last_result.level_sequence is None:
            unreal.log_warning("[widget] No LevelSequence available. Run Import first.")
            return
        open_sequencer()

    def _on_open_mrq_clicked(self):
        """Handle Open Movie Render Queue button."""
        open_movie_render_queue()
