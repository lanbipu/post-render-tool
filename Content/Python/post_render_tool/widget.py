"""Widget — VP Post-Render Tool.

Plain Python UI builder that populates an EditorUtilityWidget at runtime.
Sections: Prerequisites, CSV File, CSV Preview, Coordinate Verification,
Axis Mapping, Actions, Results.

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


# Source axis labels for ComboBox
_AXIS_OPTIONS = ["X (0)", "Y (1)", "Z (2)"]
_AXIS_INDEX_MAP = {"X (0)": 0, "Y (1)": 1, "Z (2)": 2}
_INDEX_AXIS_MAP = {0: "X (0)", 1: "Y (1)", 2: "Z (2)"}


class PostRenderToolUI:
    """VP Post-Render Tool — builds and manages the UI."""

    def __init__(self, host_widget):
        """Build the full UI into *host_widget* (an EditorUtilityWidget).

        Parameters
        ----------
        host_widget : unreal.EditorUtilityWidget
            The spawned widget instance to populate.
        """
        self._host = host_widget

        # State
        self._csv_path: str = ""
        self._fps: float = 0.0
        self._csv_result: Optional[CsvDenseResult] = None
        self._last_result: Optional[PipelineResult] = None
        self._test_camera_actor = None

        # Widget refs — populated in _build_ui
        # Prerequisites
        self._prereq_labels: list = []
        # CSV File
        self._txt_file_path: Optional[unreal.TextBlock] = None
        # CSV Preview
        self._txt_detected_fps: Optional[unreal.TextBlock] = None
        self._txt_frame_count: Optional[unreal.TextBlock] = None
        self._txt_focal_range: Optional[unreal.TextBlock] = None
        self._txt_timecode: Optional[unreal.TextBlock] = None
        self._txt_sensor_width: Optional[unreal.TextBlock] = None
        self._spn_fps: Optional[unreal.SpinBox] = None
        # Coordinate Verification
        self._spn_frame: Optional[unreal.SpinBox] = None
        self._txt_designer_pos: Optional[unreal.TextBlock] = None
        self._txt_designer_rot: Optional[unreal.TextBlock] = None
        self._txt_ue_pos: Optional[unreal.TextBlock] = None
        self._txt_ue_rot: Optional[unreal.TextBlock] = None
        self._btn_spawn_cam: Optional[unreal.Button] = None
        # Axis Mapping — position
        self._cmb_pos_x_src: Optional[unreal.ComboBoxString] = None
        self._cmb_pos_y_src: Optional[unreal.ComboBoxString] = None
        self._cmb_pos_z_src: Optional[unreal.ComboBoxString] = None
        self._spn_pos_x_scale: Optional[unreal.SpinBox] = None
        self._spn_pos_y_scale: Optional[unreal.SpinBox] = None
        self._spn_pos_z_scale: Optional[unreal.SpinBox] = None
        # Axis Mapping — rotation
        self._cmb_rot_pitch_src: Optional[unreal.ComboBoxString] = None
        self._cmb_rot_yaw_src: Optional[unreal.ComboBoxString] = None
        self._cmb_rot_roll_src: Optional[unreal.ComboBoxString] = None
        self._spn_rot_pitch_scale: Optional[unreal.SpinBox] = None
        self._spn_rot_yaw_scale: Optional[unreal.SpinBox] = None
        self._spn_rot_roll_scale: Optional[unreal.SpinBox] = None
        # Actions & Results
        self._btn_import: Optional[unreal.Button] = None
        self._btn_open_seq: Optional[unreal.Button] = None
        self._btn_open_mrq: Optional[unreal.Button] = None
        self._txt_results: Optional[unreal.MultiLineEditableText] = None

        self._build_ui()

    # ---------------------------------------------------------------
    # UI Construction
    # ---------------------------------------------------------------

    def _build_ui(self):
        """Build the entire UMG widget tree dynamically."""
        # GetRootWidget() is NOT a UFUNCTION — Python cannot call it.
        # Use EditorUtilityWidget.FindChildWidgetByName() (UFUNCTION) to
        # locate the root panel widget created by the factory.
        root = self._acquire_root_vbox()
        if root is None:
            raise RuntimeError(
                "Cannot find root panel in widget tree. "
                "Fix: from post_render_tool.widget_builder import "
                "rebuild_widget; rebuild_widget()"
            )

        # --- Title ---
        title = self._make_text("VP Post-Render Tool", size=18, is_bold=True)
        root.add_child(title)
        self._add_spacer(root, 12.0)

        # --- Prerequisites ---
        self._build_prerequisites_section(root)
        self._add_spacer(root, 12.0)

        # --- CSV File ---
        self._build_csv_file_section(root)
        self._add_spacer(root, 8.0)

        # --- CSV Preview ---
        self._build_csv_preview_section(root)
        self._add_spacer(root, 12.0)

        # --- Coordinate Verification ---
        self._build_coord_verification_section(root)
        self._add_spacer(root, 12.0)

        # --- Axis Mapping ---
        self._build_axis_mapping_section(root)
        self._add_spacer(root, 12.0)

        # --- Actions ---
        self._build_actions_section(root)
        self._add_spacer(root, 8.0)

        # --- Results ---
        lbl_results = self._make_text("── Results ──")
        root.add_child(lbl_results)

        self._txt_results = self._make_widget(unreal.MultiLineEditableText)
        self._txt_results.set_editor_property("is_read_only", True)
        self._txt_results.set_text(unreal.Text(""))
        root.add_child(self._txt_results)

        # Auto-check prerequisites on startup
        self._check_and_display_prereqs()

    # --- Section builders ---

    def _build_prerequisites_section(self, root):
        """Build the Prerequisites status section."""
        header = self._make_text("── Prerequisites ──")
        root.add_child(header)

        self._prereq_labels = []
        for _ in range(6):
            lbl = self._make_text("Checking...", color=unreal.SlateColor(
                unreal.LinearColor(0.5, 0.5, 0.5, 1.0)
            ))
            root.add_child(lbl)
            self._prereq_labels.append(lbl)

        btn_recheck = self._make_button("Recheck", self._on_recheck_prereqs)
        root.add_child(btn_recheck)

    def _build_csv_file_section(self, root):
        """Build the CSV file selection row."""
        header = self._make_text("── CSV File ──")
        root.add_child(header)

        file_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(file_row)

        btn_browse = self._make_button("Browse...", self._on_browse_clicked)
        file_row.add_child(btn_browse)

        self._txt_file_path = self._make_text(
            "No file selected",
            color=unreal.SlateColor(unreal.LinearColor(0.5, 0.5, 0.5, 1.0)),
        )
        file_row.add_child(self._txt_file_path)
        self._try_set_fill(self._txt_file_path)

    def _build_csv_preview_section(self, root):
        """Build the CSV preview info section."""
        header = self._make_text("── CSV Preview ──")
        root.add_child(header)

        self._txt_frame_count = self._make_text("Frames: --")
        root.add_child(self._txt_frame_count)

        self._txt_focal_range = self._make_text("Focal Length: --")
        root.add_child(self._txt_focal_range)

        self._txt_timecode = self._make_text("Timecode: --")
        root.add_child(self._txt_timecode)

        self._txt_sensor_width = self._make_text("Sensor Width: --")
        root.add_child(self._txt_sensor_width)

        # FPS row
        fps_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(fps_row)

        lbl_fps = self._make_text("FPS: ")
        fps_row.add_child(lbl_fps)

        self._spn_fps = self._make_widget(unreal.SpinBox)
        self._spn_fps.set_editor_property("min_value", 0.0)
        self._spn_fps.set_editor_property("max_value", 120.0)
        self._spn_fps.set_editor_property("value", 0.0)
        self._spn_fps.on_value_changed.add_callable(self._on_fps_changed)
        fps_row.add_child(self._spn_fps)

        self._txt_detected_fps = self._make_text(
            "0 = Auto-detect",
            color=unreal.SlateColor(unreal.LinearColor(0.5, 0.5, 0.5, 1.0)),
        )
        fps_row.add_child(self._txt_detected_fps)

    def _build_coord_verification_section(self, root):
        """Build the Coordinate Verification section."""
        header = self._make_text("── Coordinate Verification ──")
        root.add_child(header)

        # Frame selector
        frame_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(frame_row)

        lbl_frame = self._make_text("Frame: ")
        frame_row.add_child(lbl_frame)

        self._spn_frame = self._make_widget(unreal.SpinBox)
        self._spn_frame.set_editor_property("min_value", 0.0)
        self._spn_frame.set_editor_property("max_value", 0.0)
        self._spn_frame.set_editor_property("value", 0.0)
        self._spn_frame.on_value_changed.add_callable(self._on_frame_changed)
        frame_row.add_child(self._spn_frame)

        # Designer coordinates
        self._txt_designer_pos = self._make_text("Designer Pos: --")
        root.add_child(self._txt_designer_pos)

        self._txt_designer_rot = self._make_text("Designer Rot: --")
        root.add_child(self._txt_designer_rot)

        # UE coordinates
        self._txt_ue_pos = self._make_text("UE Pos: --")
        root.add_child(self._txt_ue_pos)

        self._txt_ue_rot = self._make_text("UE Rot: --")
        root.add_child(self._txt_ue_rot)

        # Spawn test camera button
        self._btn_spawn_cam = self._make_button(
            "Spawn Test Camera", self._on_spawn_test_camera
        )
        root.add_child(self._btn_spawn_cam)

    def _build_axis_mapping_section(self, root):
        """Build the Axis Mapping editor section."""
        header = self._make_text("── Axis Mapping ──")
        root.add_child(header)

        # Position mappings
        lbl_pos = self._make_text("Position (m -> cm):", is_bold=True)
        root.add_child(lbl_pos)

        pos_cfg = config.POSITION_MAPPING
        self._cmb_pos_x_src, self._spn_pos_x_scale = self._make_mapping_row(
            root, "UE.X <-", pos_cfg["x"][0], pos_cfg["x"][1]
        )
        self._cmb_pos_y_src, self._spn_pos_y_scale = self._make_mapping_row(
            root, "UE.Y <-", pos_cfg["y"][0], pos_cfg["y"][1]
        )
        self._cmb_pos_z_src, self._spn_pos_z_scale = self._make_mapping_row(
            root, "UE.Z <-", pos_cfg["z"][0], pos_cfg["z"][1]
        )

        self._add_spacer(root, 4.0)

        # Rotation mappings
        lbl_rot = self._make_text("Rotation (deg):", is_bold=True)
        root.add_child(lbl_rot)

        rot_cfg = config.ROTATION_MAPPING
        self._cmb_rot_pitch_src, self._spn_rot_pitch_scale = self._make_mapping_row(
            root, "Pitch <-", rot_cfg["pitch"][0], rot_cfg["pitch"][1]
        )
        self._cmb_rot_yaw_src, self._spn_rot_yaw_scale = self._make_mapping_row(
            root, "Yaw   <-", rot_cfg["yaw"][0], rot_cfg["yaw"][1]
        )
        self._cmb_rot_roll_src, self._spn_rot_roll_scale = self._make_mapping_row(
            root, "Roll  <-", rot_cfg["roll"][0], rot_cfg["roll"][1]
        )

        self._add_spacer(root, 4.0)

        # Mapping action buttons
        map_btn_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(map_btn_row)

        btn_apply = self._make_button("Apply Mapping", self._on_apply_mapping)
        map_btn_row.add_child(btn_apply)

        btn_save = self._make_button("Save to config.py", self._on_save_mapping)
        map_btn_row.add_child(btn_save)

    def _build_actions_section(self, root):
        """Build the main action buttons row."""
        header = self._make_text("── Actions ──")
        root.add_child(header)

        action_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(action_row)

        self._btn_import = self._make_button("Import", self._on_import_clicked)
        action_row.add_child(self._btn_import)

        self._btn_open_seq = self._make_button(
            "Open Sequencer", self._on_open_sequencer_clicked
        )
        action_row.add_child(self._btn_open_seq)

        self._btn_open_mrq = self._make_button(
            "Open Movie Render Queue", self._on_open_mrq_clicked
        )
        action_row.add_child(self._btn_open_mrq)

    # ---------------------------------------------------------------
    # Widget Factory Helpers
    # ---------------------------------------------------------------

    def _acquire_root_vbox(self):
        """Find the factory root widget and return a usable VerticalBox.

        Python cannot access ``UUserWidget::WidgetTree`` directly (no
        CPF_BlueprintVisible flag), and ``GetRootWidget()`` is not a
        UFUNCTION.  However, the factory's ``OnVariableAdded(Root->GetFName())``
        exports the root widget as a Blueprint variable — and at runtime
        ``InitializeWidgetStatic`` auto-binds the live widget into that
        UPROPERTY on the instance (WidgetBlueprintGeneratedClass.cpp:270).

        We look it up via ``get_editor_property`` (Blueprint variables are
        CPF_BlueprintVisible by default).  ``FindChildWidgetByName`` is used
        as a secondary fallback that searches the live WidgetTree.

        Returns a VerticalBox ready for child population, or None.
        """
        from .widget_builder import _ROOT_WIDGET_VAR_NAMES

        root_widget = None
        for name in _ROOT_WIDGET_VAR_NAMES:
            # Primary: Blueprint variable UPROPERTY (bound by
            # InitializeWidgetStatic).
            try:
                w = self._host.get_editor_property(name)
                if w is not None:
                    root_widget = w
                    unreal.log(f"[widget] Root found via UPROPERTY '{name}'.")
                    break
            except Exception:
                pass
            # Secondary: live WidgetTree search.
            try:
                w = self._host.find_child_widget_by_name(name)
                if w is not None:
                    root_widget = w
                    unreal.log(f"[widget] Root found via FindChildWidgetByName '{name}'.")
                    break
            except Exception:
                pass

        if root_widget is None:
            try:
                relevant = sorted({
                    a for a in dir(self._host)
                    if any(k in a.lower() for k in ("panel", "box", "tree", "root"))
                    and not a.startswith("_")
                })
                unreal.log_warning(
                    "[widget] No root widget found. "
                    f"Host relevant attrs: {relevant[:30]}"
                )
            except Exception:
                unreal.log_warning("[widget] No root widget found.")
            return None

        # If the root IS a VerticalBox already, use it directly.
        if isinstance(root_widget, unreal.VerticalBox):
            root_widget.clear_children()
            return root_widget

        # Otherwise (CanvasPanel, Overlay, etc.) nest a VerticalBox inside.
        root_widget.clear_children()
        vbox = self._make_widget(unreal.VerticalBox)
        root_widget.add_child(vbox)

        # CanvasPanel children default to zero-size slot — anchor to fill.
        slot = vbox.slot
        if slot is not None and isinstance(slot, unreal.CanvasPanelSlot):
            slot.set_editor_property("anchors", unreal.Anchors(
                minimum=unreal.Vector2D(0.0, 0.0),
                maximum=unreal.Vector2D(1.0, 1.0),
            ))
            slot.set_editor_property("offsets", unreal.Margin(0.0, 0.0, 0.0, 0.0))

        return vbox

    def _make_widget(self, widget_class):
        """Create a UMG widget owned by the host widget."""
        try:
            return unreal.create_widget(self._host, widget_class)
        except Exception:
            return widget_class()

    def _make_text(
        self, text: str, size: int = 0, is_bold: bool = False, color=None
    ) -> unreal.TextBlock:
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

    def _make_combo(self, default_index: int = 0) -> unreal.ComboBoxString:
        """Create a ComboBoxString with X/Y/Z axis options."""
        combo = self._make_widget(unreal.ComboBoxString)
        for opt in _AXIS_OPTIONS:
            combo.add_option(opt)
        combo.set_selected_option(_INDEX_AXIS_MAP.get(default_index, _AXIS_OPTIONS[0]))
        return combo

    def _make_scale_spinbox(self, value: float) -> unreal.SpinBox:
        """Create a SpinBox for axis scale factor."""
        spn = self._make_widget(unreal.SpinBox)
        spn.set_editor_property("min_value", -1000.0)
        spn.set_editor_property("max_value", 1000.0)
        spn.set_editor_property("value", value)
        return spn

    def _make_mapping_row(
        self, parent, label: str, src_index: int, scale: float
    ) -> tuple:
        """Create a single axis mapping row: Label + ComboBox + 'x' + SpinBox.

        Returns (combo, spinbox) tuple.
        """
        row = self._make_widget(unreal.HorizontalBox)
        parent.add_child(row)

        lbl = self._make_text(f"  {label} ")
        row.add_child(lbl)

        combo = self._make_combo(src_index)
        row.add_child(combo)

        lbl_x = self._make_text(" x ")
        row.add_child(lbl_x)

        spn = self._make_scale_spinbox(scale)
        row.add_child(spn)

        return combo, spn

    def _add_spacer(self, parent, height: float):
        """Add a Spacer widget to a panel."""
        spacer = self._make_widget(unreal.Spacer)
        parent.add_child(spacer)
        slot = spacer.slot
        if hasattr(slot, "set_editor_property"):
            try:
                slot.set_editor_property("size", unreal.Vector2D(0, height))
            except Exception:
                pass

    def _try_set_fill(self, widget):
        """Try to set a widget's slot to fill available space."""
        slot = widget.slot
        if hasattr(slot, "set_editor_property"):
            try:
                slot.set_editor_property("size", unreal.SlateChildSize(1.0))
            except Exception:
                pass

    # ---------------------------------------------------------------
    # Prerequisites
    # ---------------------------------------------------------------

    def _check_and_display_prereqs(self):
        """Check prerequisites and update status labels."""
        statuses = get_prerequisite_status()
        for i, (name, ok, hint) in enumerate(statuses):
            if i >= len(self._prereq_labels):
                break
            lbl = self._prereq_labels[i]
            if ok:
                lbl.set_text(unreal.Text(f"  OK: {name}"))
                lbl.set_editor_property(
                    "color_and_opacity",
                    unreal.SlateColor(unreal.LinearColor(0.0, 0.8, 0.0, 1.0)),
                )
            else:
                hint_text = f" -> {hint}" if hint else ""
                lbl.set_text(unreal.Text(f"  MISSING: {name}{hint_text}"))
                lbl.set_editor_property(
                    "color_and_opacity",
                    unreal.SlateColor(unreal.LinearColor(0.9, 0.1, 0.1, 1.0)),
                )

    def _on_recheck_prereqs(self):
        """Handle Recheck button."""
        self._check_and_display_prereqs()
        unreal.log("[widget] Prerequisites rechecked.")

    # ---------------------------------------------------------------
    # CSV File & Preview
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
            self._csv_result = result

            fl_min, fl_max = result.focal_length_range
            self._txt_frame_count.set_text(
                unreal.Text(f"Frames: {result.frame_count}")
            )
            self._txt_focal_range.set_text(
                unreal.Text(f"Focal Length: {fl_min:.2f} - {fl_max:.2f} mm")
            )
            self._txt_timecode.set_text(
                unreal.Text(
                    f"Timecode: {result.timecode_start} -> {result.timecode_end}"
                )
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

            # Update frame SpinBox range
            max_frame = max(0.0, float(result.frame_count - 1))
            self._spn_frame.set_editor_property("max_value", max_frame)
            self._spn_frame.set_editor_property("value", 0.0)

            # Show coordinate preview for frame 0
            self._refresh_coord_preview()

            unreal.log(f"[widget] CSV preview loaded: {csv_path}")

        except CsvParseError as exc:
            self._csv_result = None
            self._txt_results.set_text(unreal.Text(f"CSV Error: {exc}"))
            unreal.log_warning(f"[widget] CSV parse error: {exc}")
        except Exception as exc:
            self._csv_result = None
            self._txt_results.set_text(unreal.Text(f"Error: {exc}"))
            unreal.log_error(f"[widget] Preview error: {exc}")

    def _on_fps_changed(self, value: float):
        """Handle FPS SpinBox value change."""
        self._fps = value

    # ---------------------------------------------------------------
    # Coordinate Verification
    # ---------------------------------------------------------------

    def _refresh_coord_preview(self):
        """Update the coordinate preview for the currently selected frame."""
        if self._csv_result is None or not self._csv_result.frames:
            return

        idx = int(self._spn_frame.get_editor_property("value"))
        idx = max(0, min(idx, len(self._csv_result.frames) - 1))
        frame = self._csv_result.frames[idx]

        # Designer raw values
        self._txt_designer_pos.set_text(
            unreal.Text(
                f"Designer Pos: ({frame.offset_x:.4f}, "
                f"{frame.offset_y:.4f}, {frame.offset_z:.4f}) m"
            )
        )
        self._txt_designer_rot.set_text(
            unreal.Text(
                f"Designer Rot: ({frame.rotation_x:.2f}, "
                f"{frame.rotation_y:.2f}, {frame.rotation_z:.2f}) deg"
            )
        )

        # UE transformed values
        ue_pos = transform_position(frame.offset_x, frame.offset_y, frame.offset_z)
        ue_rot = transform_rotation(
            frame.rotation_x, frame.rotation_y, frame.rotation_z
        )

        self._txt_ue_pos.set_text(
            unreal.Text(
                f"UE Pos: ({ue_pos[0]:.1f}, {ue_pos[1]:.1f}, {ue_pos[2]:.1f}) cm"
            )
        )
        self._txt_ue_rot.set_text(
            unreal.Text(
                f"UE Rot: P={ue_rot[0]:.2f}  Y={ue_rot[1]:.2f}  R={ue_rot[2]:.2f} deg"
            )
        )

    def _on_frame_changed(self, value: float):
        """Handle frame SpinBox change."""
        self._refresh_coord_preview()

    def _on_spawn_test_camera(self):
        """Spawn a test CineCameraActor at the current frame's UE coordinates."""
        if self._csv_result is None or not self._csv_result.frames:
            self._txt_results.set_text(
                unreal.Text("No CSV loaded. Browse a file first.")
            )
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
            self._txt_results.set_text(
                unreal.Text(
                    f"Test camera spawned at frame {idx}.\n"
                    f"Pos: ({ue_pos[0]:.1f}, {ue_pos[1]:.1f}, {ue_pos[2]:.1f}) cm\n"
                    f"Rot: P={ue_rot[0]:.2f} Y={ue_rot[1]:.2f} R={ue_rot[2]:.2f}\n"
                    f"Viewport piloted to camera."
                )
            )
        except Exception as exc:
            self._txt_results.set_text(
                unreal.Text(f"Failed to spawn test camera: {exc}")
            )
            unreal.log_error(f"[widget] Spawn test camera error: {exc}")

    # ---------------------------------------------------------------
    # Axis Mapping
    # ---------------------------------------------------------------

    def _read_mapping_from_ui(self) -> tuple:
        """Read current axis mapping values from ComboBox/SpinBox widgets.

        Returns (pos_mapping, rot_mapping) dicts.
        """
        def _get_combo_index(combo) -> int:
            sel = combo.get_selected_option()
            return _AXIS_INDEX_MAP.get(sel, 0)

        def _get_scale(spn) -> float:
            return spn.get_editor_property("value")

        pos_mapping = {
            "x": (_get_combo_index(self._cmb_pos_x_src), _get_scale(self._spn_pos_x_scale)),
            "y": (_get_combo_index(self._cmb_pos_y_src), _get_scale(self._spn_pos_y_scale)),
            "z": (_get_combo_index(self._cmb_pos_z_src), _get_scale(self._spn_pos_z_scale)),
        }

        rot_mapping = {
            "pitch": (_get_combo_index(self._cmb_rot_pitch_src), _get_scale(self._spn_rot_pitch_scale)),
            "yaw": (_get_combo_index(self._cmb_rot_yaw_src), _get_scale(self._spn_rot_yaw_scale)),
            "roll": (_get_combo_index(self._cmb_rot_roll_src), _get_scale(self._spn_rot_roll_scale)),
        }

        return pos_mapping, rot_mapping

    def _on_apply_mapping(self):
        """Apply axis mapping changes to memory and refresh preview."""
        pos_mapping, rot_mapping = self._read_mapping_from_ui()

        # Update config module in memory
        config.POSITION_MAPPING = pos_mapping
        config.ROTATION_MAPPING = rot_mapping

        # Reload coordinate_transform so it picks up new config values
        from . import coordinate_transform
        importlib.reload(coordinate_transform)

        # Re-import the functions so this module uses the reloaded versions
        global transform_position, transform_rotation
        transform_position = coordinate_transform.transform_position
        transform_rotation = coordinate_transform.transform_rotation

        # Refresh preview
        self._refresh_coord_preview()

        self._txt_results.set_text(
            unreal.Text("Axis mapping applied (in memory). Coordinate preview updated.")
        )
        unreal.log("[widget] Axis mapping applied in memory.")

    def _on_save_mapping(self):
        """Save current axis mapping to config.py on disk."""
        pos_mapping, rot_mapping = self._read_mapping_from_ui()

        try:
            save_axis_mapping(pos_mapping, rot_mapping)
            self._refresh_coord_preview()
            self._txt_results.set_text(
                unreal.Text("Axis mapping saved to config.py successfully.")
            )
        except Exception as exc:
            self._txt_results.set_text(
                unreal.Text(f"Failed to save mapping: {exc}")
            )
            unreal.log_error(f"[widget] Save mapping error: {exc}")

    # ---------------------------------------------------------------
    # Import & Actions
    # ---------------------------------------------------------------

    def _on_import_clicked(self):
        """Handle Import button: run the full pipeline."""
        if not self._csv_path:
            self._txt_results.set_text(
                unreal.Text("Error: No CSV file selected. Click Browse first.")
            )
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
            unreal.log(
                f"[widget] Import successful: {pipeline_result.package_path}"
            )
        else:
            self._txt_results.set_text(
                unreal.Text(f"Import Failed:\n{pipeline_result.error_message}")
            )
            unreal.log_error(
                f"[widget] Import failed: {pipeline_result.error_message}"
            )

    def _on_open_sequencer_clicked(self):
        """Handle Open Sequencer button."""
        if self._last_result is None or self._last_result.level_sequence is None:
            self._txt_results.set_text(
                unreal.Text("No LevelSequence available. Run Import first.")
            )
            return
        open_sequencer(self._last_result.level_sequence)

    def _on_open_mrq_clicked(self):
        """Handle Open Movie Render Queue button."""
        open_movie_render_queue()
