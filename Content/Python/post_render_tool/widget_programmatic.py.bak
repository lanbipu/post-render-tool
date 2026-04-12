"""Widget — VP Post-Render Tool (programmatic UMG builder).

Structure first (Figma Step B): builds the full 6-section layout into the
user-created template's ``RootPanel`` VerticalBox. Mirrors the Figma
baseline hierarchy (cards, nested groups, embedded results) using default
Slate styling — no rounded corners, no custom fonts, no widget-style
overrides. Colour polish is Step A.

Cards (top → bottom):

  1. Prerequisites           — header with "N / 6 OK" summary + 6 status lines + Recheck
  2. CSV File                — Browse + file path
  3. CSV Preview             — 4 info lines + FPS SpinBox row
  4. Coordinate Verification — Frame row + nested Designer/UE sub-card + Spawn Test Camera
  5. Axis Mapping            — Position group + Rotation group + Apply/Save row
  6. Actions + Results       — Import (primary) + Open Sequencer/MRQ row + Results log

Each card is a ``Border`` containing a ``VerticalBox``. Section headers are
marked with a teal accent prefix ``▌``.

Only usable inside UE Editor Python environment.
"""

from __future__ import annotations

import importlib
from typing import Optional

import unreal

from . import config
from .coordinate_transform import transform_position, transform_rotation
from .csv_parser import CsvDenseResult, CsvParseError, parse_csv_dense
from .pipeline import PipelineResult, run_import
from .ui_interface import (
    browse_csv_file,
    get_prerequisite_status,
    open_movie_render_queue,
    open_sequencer,
    save_axis_mapping,
    spawn_test_camera,
)


_AXIS_OPTIONS = ["X (0)", "Y (1)", "Z (2)"]
_AXIS_INDEX_MAP = {"X (0)": 0, "Y (1)": 1, "Z (2)": 2}
_INDEX_AXIS_MAP = {0: "X (0)", 1: "Y (1)", 2: "Z (2)"}

_MUTED = unreal.SlateColor(unreal.LinearColor(0.5, 0.5, 0.5, 1.0))
_OK = unreal.SlateColor(unreal.LinearColor(0.30, 0.80, 0.30, 1.0))
_ERR = unreal.SlateColor(unreal.LinearColor(0.90, 0.25, 0.25, 1.0))
_ACCENT = unreal.SlateColor(unreal.LinearColor(0.0, 0.749, 0.647, 1.0))  # #00BFA5

# Card / sub-card background tints. Kept subtle under the default Slate
# skin — they exist to satisfy Figma's visual grouping, not to theme the UI.
_CARD_BG = unreal.LinearColor(0.141, 0.141, 0.141, 1.0)      # #242424
_SUBCARD_BG = unreal.LinearColor(0.102, 0.102, 0.102, 1.0)   # #1A1A1A
_CARD_PADDING = unreal.Margin(12.0, 10.0, 12.0, 10.0)
_SUBCARD_PADDING = unreal.Margin(10.0, 8.0, 10.0, 8.0)


class PostRenderToolUI:
    """VP Post-Render Tool — builds and manages the UI."""

    def __init__(self, host_widget):
        self._host = host_widget

        # State
        self._csv_path: str = ""
        self._fps: float = 0.0
        self._csv_result: Optional[CsvDenseResult] = None
        self._last_result: Optional[PipelineResult] = None
        self._test_camera_actor = None

        # Widget refs (populated by _build_ui)
        self._prereq_labels: list = []
        self._prereq_summary: Optional[unreal.TextBlock] = None
        self._txt_file_path: Optional[unreal.TextBlock] = None
        self._txt_frame_count: Optional[unreal.TextBlock] = None
        self._txt_focal_range: Optional[unreal.TextBlock] = None
        self._txt_timecode: Optional[unreal.TextBlock] = None
        self._txt_sensor_width: Optional[unreal.TextBlock] = None
        self._spn_fps: Optional[unreal.SpinBox] = None
        self._txt_detected_fps: Optional[unreal.TextBlock] = None
        self._spn_frame: Optional[unreal.SpinBox] = None
        self._txt_frame_hint: Optional[unreal.TextBlock] = None
        self._txt_designer_pos: Optional[unreal.TextBlock] = None
        self._txt_designer_rot: Optional[unreal.TextBlock] = None
        self._txt_ue_pos: Optional[unreal.TextBlock] = None
        self._txt_ue_rot: Optional[unreal.TextBlock] = None
        self._btn_spawn_cam: Optional[unreal.Button] = None
        self._cmb_pos_x_src: Optional[unreal.ComboBoxString] = None
        self._cmb_pos_y_src: Optional[unreal.ComboBoxString] = None
        self._cmb_pos_z_src: Optional[unreal.ComboBoxString] = None
        self._spn_pos_x_scale: Optional[unreal.SpinBox] = None
        self._spn_pos_y_scale: Optional[unreal.SpinBox] = None
        self._spn_pos_z_scale: Optional[unreal.SpinBox] = None
        self._cmb_rot_pitch_src: Optional[unreal.ComboBoxString] = None
        self._cmb_rot_yaw_src: Optional[unreal.ComboBoxString] = None
        self._cmb_rot_roll_src: Optional[unreal.ComboBoxString] = None
        self._spn_rot_pitch_scale: Optional[unreal.SpinBox] = None
        self._spn_rot_yaw_scale: Optional[unreal.SpinBox] = None
        self._spn_rot_roll_scale: Optional[unreal.SpinBox] = None
        self._btn_import: Optional[unreal.Button] = None
        self._btn_open_seq: Optional[unreal.Button] = None
        self._btn_open_mrq: Optional[unreal.Button] = None
        self._txt_results: Optional[unreal.MultiLineEditableText] = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self._acquire_root_vbox()
        if root is None:
            raise RuntimeError(
                "Template root widget not accessible. "
                "See widget_builder.TEMPLATE_SETUP_INSTRUCTIONS."
            )

        self._build_prerequisites_section(root)
        self._add_spacer(root, 8.0)

        self._build_csv_file_section(root)
        self._add_spacer(root, 8.0)

        self._build_csv_preview_section(root)
        self._add_spacer(root, 8.0)

        self._build_coord_verification_section(root)
        self._add_spacer(root, 8.0)

        self._build_axis_mapping_section(root)
        self._add_spacer(root, 8.0)

        self._build_actions_and_results_section(root)

        self._check_and_display_prereqs()

    # ------------------------------------------------------------------
    # Section 1: Prerequisites
    # ------------------------------------------------------------------

    def _build_prerequisites_section(self, root):
        content, summary = self._begin_card(root, "Prerequisites", show_summary=True)
        self._prereq_summary = summary

        self._prereq_labels = []
        for _ in range(6):
            lbl = self._make_text("  Checking...", color=_MUTED)
            content.add_child(lbl)
            self._prereq_labels.append(lbl)

        self._add_spacer(content, 4.0)
        content.add_child(
            self._make_button("Recheck", self._on_recheck_prereqs)
        )

    # ------------------------------------------------------------------
    # Section 2: CSV File
    # ------------------------------------------------------------------

    def _build_csv_file_section(self, root):
        content, _ = self._begin_card(root, "CSV File")

        row = self._make_widget(unreal.HorizontalBox)
        content.add_child(row)

        row.add_child(self._make_button("Browse...", self._on_browse_clicked))

        self._txt_file_path = self._make_text("  No file selected", color=_MUTED)
        row.add_child(self._txt_file_path)
        self._try_fill_hbox_slot(self._txt_file_path)

    # ------------------------------------------------------------------
    # Section 3: CSV Preview
    # ------------------------------------------------------------------

    def _build_csv_preview_section(self, root):
        content, _ = self._begin_card(root, "CSV Preview")

        self._txt_frame_count = self._make_text("  Frames: --")
        content.add_child(self._txt_frame_count)

        self._txt_focal_range = self._make_text("  Focal Length: --")
        content.add_child(self._txt_focal_range)

        self._txt_timecode = self._make_text("  Timecode: --")
        content.add_child(self._txt_timecode)

        self._txt_sensor_width = self._make_text("  Sensor Width: --")
        content.add_child(self._txt_sensor_width)

        fps_row = self._make_widget(unreal.HorizontalBox)
        content.add_child(fps_row)

        fps_row.add_child(self._make_text("  FPS: "))

        self._spn_fps = self._make_widget(unreal.SpinBox)
        self._spn_fps.set_editor_property("min_value", 0.0)
        self._spn_fps.set_editor_property("max_value", 120.0)
        self._spn_fps.set_editor_property("value", 0.0)
        self._spn_fps.on_value_changed.add_callable(self._on_fps_changed)
        fps_row.add_child(self._spn_fps)

        self._txt_detected_fps = self._make_text(
            "  Auto: N/A  (0 = auto-detect)", color=_MUTED
        )
        fps_row.add_child(self._txt_detected_fps)

    # ------------------------------------------------------------------
    # Section 4: Coordinate Verification
    # ------------------------------------------------------------------

    def _build_coord_verification_section(self, root):
        content, _ = self._begin_card(root, "Coordinate Verification")

        frame_row = self._make_widget(unreal.HorizontalBox)
        content.add_child(frame_row)

        frame_row.add_child(self._make_text("  Frame: "))

        self._spn_frame = self._make_widget(unreal.SpinBox)
        self._spn_frame.set_editor_property("min_value", 0.0)
        self._spn_frame.set_editor_property("max_value", 0.0)
        self._spn_frame.set_editor_property("value", 0.0)
        self._spn_frame.on_value_changed.add_callable(self._on_frame_changed)
        frame_row.add_child(self._spn_frame)

        self._txt_frame_hint = self._make_text("  0 / 0", color=_MUTED)
        frame_row.add_child(self._txt_frame_hint)

        # Nested sub-card for Designer → UE coordinate preview
        self._add_spacer(content, 4.0)
        subcard = self._make_subcard()
        content.add_child(subcard)
        sub_content = self._make_widget(unreal.VerticalBox)
        subcard.add_child(sub_content)

        sub_content.add_child(
            self._make_text("DESIGNER (source)", is_bold=True, color=_MUTED)
        )
        self._txt_designer_pos = self._make_text("  Pos: --")
        sub_content.add_child(self._txt_designer_pos)
        self._txt_designer_rot = self._make_text("  Rot: --")
        sub_content.add_child(self._txt_designer_rot)

        self._add_spacer(sub_content, 4.0)

        accent_arrow = self._make_text("→ UE (result)", is_bold=True)
        accent_arrow.set_editor_property("color_and_opacity", _ACCENT)
        sub_content.add_child(accent_arrow)
        self._txt_ue_pos = self._make_text("  Pos: --")
        sub_content.add_child(self._txt_ue_pos)
        self._txt_ue_rot = self._make_text("  Rot: --")
        sub_content.add_child(self._txt_ue_rot)

        self._add_spacer(content, 6.0)
        self._btn_spawn_cam = self._make_button(
            "Spawn Test Camera", self._on_spawn_test_camera
        )
        content.add_child(self._btn_spawn_cam)

    # ------------------------------------------------------------------
    # Section 5: Axis Mapping
    # ------------------------------------------------------------------

    def _build_axis_mapping_section(self, root):
        content, _ = self._begin_card(root, "Axis Mapping")

        pos_label = self._make_text("POSITION  (m → cm)", is_bold=True)
        pos_label.set_editor_property("color_and_opacity", _ACCENT)
        content.add_child(pos_label)

        pos = config.POSITION_MAPPING
        self._cmb_pos_x_src, self._spn_pos_x_scale = self._make_mapping_row(
            content, "UE.X ←", pos["x"][0], pos["x"][1]
        )
        self._cmb_pos_y_src, self._spn_pos_y_scale = self._make_mapping_row(
            content, "UE.Y ←", pos["y"][0], pos["y"][1]
        )
        self._cmb_pos_z_src, self._spn_pos_z_scale = self._make_mapping_row(
            content, "UE.Z ←", pos["z"][0], pos["z"][1]
        )

        self._add_spacer(content, 6.0)

        rot_label = self._make_text("ROTATION  (deg)", is_bold=True)
        rot_label.set_editor_property("color_and_opacity", _ACCENT)
        content.add_child(rot_label)

        rot = config.ROTATION_MAPPING
        self._cmb_rot_pitch_src, self._spn_rot_pitch_scale = self._make_mapping_row(
            content, "Pitch ←", rot["pitch"][0], rot["pitch"][1]
        )
        self._cmb_rot_yaw_src, self._spn_rot_yaw_scale = self._make_mapping_row(
            content, "Yaw   ←", rot["yaw"][0], rot["yaw"][1]
        )
        self._cmb_rot_roll_src, self._spn_rot_roll_scale = self._make_mapping_row(
            content, "Roll  ←", rot["roll"][0], rot["roll"][1]
        )

        self._add_spacer(content, 6.0)

        btn_row = self._make_widget(unreal.HorizontalBox)
        content.add_child(btn_row)
        btn_row.add_child(self._make_button("Apply Mapping", self._on_apply_mapping))
        btn_row.add_child(
            self._make_button("Save to config.py", self._on_save_mapping)
        )

    # ------------------------------------------------------------------
    # Section 6: Actions
    # ------------------------------------------------------------------

    def _build_actions_and_results_section(self, root):
        content, _ = self._begin_card(root, "Actions")

        # Primary action — Import owns its own row so it reads as primary.
        self._btn_import = self._make_button("Import", self._on_import_clicked)
        content.add_child(self._btn_import)

        self._add_spacer(content, 4.0)

        btn_row = self._make_widget(unreal.HorizontalBox)
        content.add_child(btn_row)

        self._btn_open_seq = self._make_button(
            "Open Sequencer", self._on_open_sequencer_clicked
        )
        btn_row.add_child(self._btn_open_seq)

        self._btn_open_mrq = self._make_button(
            "Open Movie Render Queue", self._on_open_mrq_clicked
        )
        btn_row.add_child(self._btn_open_mrq)

        self._add_spacer(content, 8.0)

        results_label = self._make_text("RESULTS", is_bold=True)
        results_label.set_editor_property("color_and_opacity", _ACCENT)
        content.add_child(results_label)

        self._txt_results = self._make_widget(unreal.MultiLineEditableText)
        self._txt_results.set_editor_property("is_read_only", True)
        self._txt_results.set_text(unreal.Text(""))
        content.add_child(self._txt_results)

    # ------------------------------------------------------------------
    # Widget factory helpers
    # ------------------------------------------------------------------

    def _acquire_root_vbox(self):
        from .widget_builder import ROOT_VBOX_VAR_NAME, TEMPLATE_SETUP_INSTRUCTIONS

        try:
            root_widget = self._host.get_editor_property(ROOT_VBOX_VAR_NAME)
        except Exception as exc:
            unreal.log_warning(
                f"[widget] Template is missing the '{ROOT_VBOX_VAR_NAME}' "
                f"variable: {exc}"
            )
            unreal.log_warning(TEMPLATE_SETUP_INSTRUCTIONS)
            return None

        if root_widget is None:
            unreal.log_warning(
                f"[widget] '{ROOT_VBOX_VAR_NAME}' UPROPERTY exists but is None "
                "(template widget not bound at runtime)."
            )
            return None

        if not isinstance(root_widget, unreal.VerticalBox):
            unreal.log_warning(
                f"[widget] '{ROOT_VBOX_VAR_NAME}' is a "
                f"{type(root_widget).__name__}, expected VerticalBox."
            )
            return None

        root_widget.clear_children()
        return root_widget

    def _make_widget(self, widget_class):
        try:
            return unreal.create_widget(self._host, widget_class)
        except Exception:
            return widget_class()

    def _make_text(
        self,
        text: str,
        size: int = 0,
        is_bold: bool = False,
        color=None,
    ) -> unreal.TextBlock:
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

    def _begin_card(self, root, title: str, show_summary: bool = False):
        """Create a section card (``Border`` wrapping a ``VerticalBox``) and
        append it to *root*.

        Returns ``(content_vbox, summary_text_block_or_None)``. Build the
        section body into *content_vbox*.
        """
        card = self._make_widget(unreal.Border)
        try:
            card.set_brush_color(_CARD_BG)
        except Exception:
            pass
        try:
            card.set_padding(_CARD_PADDING)
        except Exception:
            pass

        inner = self._make_widget(unreal.VerticalBox)
        card.add_child(inner)
        root.add_child(card)

        # Header row: accent bar + bold title (+ optional summary on the right)
        header = self._make_widget(unreal.HorizontalBox)
        inner.add_child(header)

        accent = self._make_text("▌", is_bold=True)
        accent.set_editor_property("color_and_opacity", _ACCENT)
        header.add_child(accent)

        header.add_child(self._make_text(f" {title}", size=13, is_bold=True))

        summary_tb: Optional[unreal.TextBlock] = None
        if show_summary:
            # Flexible spacer pushes the summary toward the right edge.
            spacer = self._make_widget(unreal.Spacer)
            header.add_child(spacer)
            self._try_fill_hbox_slot(spacer)

            summary_tb = self._make_text("", color=_MUTED)
            header.add_child(summary_tb)

        self._add_spacer(inner, 6.0)
        return inner, summary_tb

    def _make_subcard(self) -> unreal.Border:
        """Create an inset ``Border`` used for nested groups (e.g. the
        Designer/UE coordinate pair inside Section 4).
        """
        sub = self._make_widget(unreal.Border)
        try:
            sub.set_brush_color(_SUBCARD_BG)
        except Exception:
            pass
        try:
            sub.set_padding(_SUBCARD_PADDING)
        except Exception:
            pass
        return sub

    def _make_button(self, label: str, callback) -> unreal.Button:
        btn = self._make_widget(unreal.Button)
        btn.add_child(self._make_text(label))
        btn.on_clicked.add_callable(callback)
        return btn

    def _make_combo(self, default_index: int = 0) -> unreal.ComboBoxString:
        combo = self._make_widget(unreal.ComboBoxString)
        for opt in _AXIS_OPTIONS:
            combo.add_option(opt)
        combo.set_selected_option(
            _INDEX_AXIS_MAP.get(default_index, _AXIS_OPTIONS[0])
        )
        return combo

    def _make_scale_spinbox(self, value: float) -> unreal.SpinBox:
        spn = self._make_widget(unreal.SpinBox)
        spn.set_editor_property("min_value", -1000.0)
        spn.set_editor_property("max_value", 1000.0)
        spn.set_editor_property("value", value)
        return spn

    def _make_mapping_row(
        self, parent, label: str, src_index: int, scale: float
    ) -> tuple:
        row = self._make_widget(unreal.HorizontalBox)
        parent.add_child(row)

        row.add_child(self._make_text(f"    {label} "))

        combo = self._make_combo(src_index)
        row.add_child(combo)

        row.add_child(self._make_text("  ×  "))

        spn = self._make_scale_spinbox(scale)
        row.add_child(spn)

        return combo, spn

    def _add_spacer(self, parent, height: float):
        spacer = self._make_widget(unreal.Spacer)
        parent.add_child(spacer)
        slot = spacer.slot
        if slot is not None and hasattr(slot, "set_editor_property"):
            try:
                slot.set_editor_property("size", unreal.Vector2D(0, height))
            except Exception:
                pass

    def _try_fill_hbox_slot(self, widget):
        slot = widget.slot
        if slot is None:
            return
        try:
            slot.set_editor_property("size", unreal.SlateChildSize(1.0))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Prerequisites
    # ------------------------------------------------------------------

    def _check_and_display_prereqs(self):
        statuses = get_prerequisite_status()
        ok_count = 0
        for i, (name, ok, hint) in enumerate(statuses):
            if i >= len(self._prereq_labels):
                break
            lbl = self._prereq_labels[i]
            if ok:
                lbl.set_text(unreal.Text(f"  OK: {name}"))
                lbl.set_editor_property("color_and_opacity", _OK)
                ok_count += 1
            else:
                detail = f" → {hint}" if hint else ""
                lbl.set_text(unreal.Text(f"  MISSING: {name}{detail}"))
                lbl.set_editor_property("color_and_opacity", _ERR)

        if self._prereq_summary is not None:
            total = min(len(statuses), len(self._prereq_labels))
            self._prereq_summary.set_text(unreal.Text(f"{ok_count} / {total} OK"))
            self._prereq_summary.set_editor_property(
                "color_and_opacity", _OK if ok_count == total else _ERR
            )

    def _on_recheck_prereqs(self):
        self._check_and_display_prereqs()
        unreal.log("[widget] Prerequisites rechecked.")

    # ------------------------------------------------------------------
    # CSV File & Preview
    # ------------------------------------------------------------------

    def _on_browse_clicked(self):
        csv_path = browse_csv_file()
        if not csv_path:
            unreal.log_warning("[widget] No file selected.")
            return

        self._csv_path = csv_path
        self._txt_file_path.set_text(unreal.Text(csv_path))

        try:
            result = parse_csv_dense(csv_path)
        except CsvParseError as exc:
            self._csv_result = None
            self._set_results(f"CSV Error: {exc}")
            unreal.log_warning(f"[widget] CSV parse error: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            self._csv_result = None
            self._set_results(f"Error: {exc}")
            unreal.log_error(f"[widget] Preview error: {exc}")
            return

        self._csv_result = result
        fl_min, fl_max = result.focal_length_range

        self._txt_frame_count.set_text(
            unreal.Text(f"  Frames: {result.frame_count}")
        )
        self._txt_focal_range.set_text(
            unreal.Text(f"  Focal Length: {fl_min:.2f} – {fl_max:.2f} mm")
        )
        self._txt_timecode.set_text(
            unreal.Text(
                f"  Timecode: {result.timecode_start} → {result.timecode_end}"
            )
        )
        self._txt_sensor_width.set_text(
            unreal.Text(f"  Sensor Width: {result.sensor_width_mm:.2f} mm")
        )
        if result.detected_fps is not None:
            self._txt_detected_fps.set_text(
                unreal.Text(f"  Auto: {result.detected_fps} fps")
            )
        else:
            self._txt_detected_fps.set_text(unreal.Text("  Auto: N/A"))

        max_frame = max(0.0, float(result.frame_count - 1))
        self._spn_frame.set_editor_property("max_value", max_frame)
        self._spn_frame.set_editor_property("value", 0.0)
        self._txt_frame_hint.set_text(
            unreal.Text(f"  0 / {max(0, result.frame_count - 1)}")
        )

        self._refresh_coord_preview()

        unreal.log(f"[widget] CSV preview loaded: {csv_path}")

    def _on_fps_changed(self, value: float):
        self._fps = value

    # ------------------------------------------------------------------
    # Coordinate Verification
    # ------------------------------------------------------------------

    def _refresh_coord_preview(self):
        if self._csv_result is None or not self._csv_result.frames:
            return

        idx = int(self._spn_frame.get_editor_property("value"))
        idx = max(0, min(idx, len(self._csv_result.frames) - 1))
        frame = self._csv_result.frames[idx]

        self._txt_designer_pos.set_text(
            unreal.Text(
                f"  Pos: ({frame.offset_x:.4f}, "
                f"{frame.offset_y:.4f}, {frame.offset_z:.4f}) m"
            )
        )
        self._txt_designer_rot.set_text(
            unreal.Text(
                f"  Rot: ({frame.rotation_x:.2f}, "
                f"{frame.rotation_y:.2f}, {frame.rotation_z:.2f})°"
            )
        )

        ue_pos = transform_position(frame.offset_x, frame.offset_y, frame.offset_z)
        ue_rot = transform_rotation(
            frame.rotation_x, frame.rotation_y, frame.rotation_z
        )

        self._txt_ue_pos.set_text(
            unreal.Text(
                f"  Pos: ({ue_pos[0]:.1f}, {ue_pos[1]:.1f}, {ue_pos[2]:.1f}) cm"
            )
        )
        self._txt_ue_rot.set_text(
            unreal.Text(
                f"  Rot: P={ue_rot[0]:.2f}  Y={ue_rot[1]:.2f}  R={ue_rot[2]:.2f}°"
            )
        )

        if self._txt_frame_hint is not None:
            total = max(0, len(self._csv_result.frames) - 1)
            self._txt_frame_hint.set_text(unreal.Text(f"  {idx} / {total}"))

    def _on_frame_changed(self, value: float):
        self._refresh_coord_preview()

    def _on_spawn_test_camera(self):
        if self._csv_result is None or not self._csv_result.frames:
            self._set_results("No CSV loaded. Browse a file first.")
            return

        idx = int(self._spn_frame.get_editor_property("value"))
        idx = max(0, min(idx, len(self._csv_result.frames) - 1))
        frame = self._csv_result.frames[idx]

        ue_pos = transform_position(frame.offset_x, frame.offset_y, frame.offset_z)
        ue_rot = transform_rotation(
            frame.rotation_x, frame.rotation_y, frame.rotation_z
        )

        try:
            self._test_camera_actor = spawn_test_camera(
                ue_x=ue_pos[0],
                ue_y=ue_pos[1],
                ue_z=ue_pos[2],
                pitch=ue_rot[0],
                yaw=ue_rot[1],
                roll=ue_rot[2],
                sensor_width_mm=self._csv_result.sensor_width_mm,
            )
            self._set_results(
                f"Test camera spawned at frame {idx}.\n"
                f"Pos: ({ue_pos[0]:.1f}, {ue_pos[1]:.1f}, {ue_pos[2]:.1f}) cm\n"
                f"Rot: P={ue_rot[0]:.2f} Y={ue_rot[1]:.2f} R={ue_rot[2]:.2f}\n"
                f"Viewport piloted to camera."
            )
        except Exception as exc:  # noqa: BLE001
            self._set_results(f"Failed to spawn test camera: {exc}")
            unreal.log_error(f"[widget] Spawn test camera error: {exc}")

    # ------------------------------------------------------------------
    # Axis Mapping
    # ------------------------------------------------------------------

    def _read_mapping_from_ui(self) -> tuple:
        def get_axis(combo):
            return _AXIS_INDEX_MAP.get(combo.get_selected_option(), 0)

        def get_scale(spn):
            return spn.get_editor_property("value")

        pos_mapping = {
            "x": (get_axis(self._cmb_pos_x_src), get_scale(self._spn_pos_x_scale)),
            "y": (get_axis(self._cmb_pos_y_src), get_scale(self._spn_pos_y_scale)),
            "z": (get_axis(self._cmb_pos_z_src), get_scale(self._spn_pos_z_scale)),
        }
        rot_mapping = {
            "pitch": (
                get_axis(self._cmb_rot_pitch_src),
                get_scale(self._spn_rot_pitch_scale),
            ),
            "yaw": (
                get_axis(self._cmb_rot_yaw_src),
                get_scale(self._spn_rot_yaw_scale),
            ),
            "roll": (
                get_axis(self._cmb_rot_roll_src),
                get_scale(self._spn_rot_roll_scale),
            ),
        }
        return pos_mapping, rot_mapping

    def _on_apply_mapping(self):
        pos_mapping, rot_mapping = self._read_mapping_from_ui()

        config.POSITION_MAPPING = pos_mapping
        config.ROTATION_MAPPING = rot_mapping

        from . import coordinate_transform
        importlib.reload(coordinate_transform)
        global transform_position, transform_rotation
        transform_position = coordinate_transform.transform_position
        transform_rotation = coordinate_transform.transform_rotation

        self._refresh_coord_preview()
        self._set_results(
            "Axis mapping applied (in memory). Coordinate preview updated."
        )
        unreal.log("[widget] Axis mapping applied in memory.")

    def _on_save_mapping(self):
        pos_mapping, rot_mapping = self._read_mapping_from_ui()
        try:
            save_axis_mapping(pos_mapping, rot_mapping)
            self._refresh_coord_preview()
            self._set_results("Axis mapping saved to config.py successfully.")
        except Exception as exc:  # noqa: BLE001
            self._set_results(f"Failed to save mapping: {exc}")
            unreal.log_error(f"[widget] Save mapping error: {exc}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_import_clicked(self):
        if not self._csv_path:
            self._set_results("Error: No CSV file selected. Click Browse first.")
            return

        self._set_results("Importing...")

        fps = self._fps if self._fps > 0 else 0.0
        pipeline_result = run_import(self._csv_path, fps)
        self._last_result = pipeline_result

        if pipeline_result.success:
            report_text = (
                pipeline_result.report.format_report()
                if pipeline_result.report is not None
                else "Import successful (no report generated)."
            )
            self._set_results(report_text)
            unreal.log(
                f"[widget] Import successful: {pipeline_result.package_path}"
            )
        else:
            self._set_results(
                f"Import Failed:\n{pipeline_result.error_message}"
            )
            unreal.log_error(
                f"[widget] Import failed: {pipeline_result.error_message}"
            )

    def _on_open_sequencer_clicked(self):
        if self._last_result is None or self._last_result.level_sequence is None:
            self._set_results("No LevelSequence available. Run Import first.")
            return
        open_sequencer(self._last_result.level_sequence)

    def _on_open_mrq_clicked(self):
        open_movie_render_queue()

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _set_results(self, message: str):
        if self._txt_results is None:
            return
        self._txt_results.set_text(unreal.Text(message))
