"""Widget — VP Post-Render Tool (UMG BindWidget binder).

This module is loaded by widget_builder after the plugin's
BP_PostRenderToolWidget has been spawned as an editor tab. It acquires
all widget references declared on the C++ UPostRenderToolWidget class
(via meta=(BindWidget) UPROPERTYs), wires event callbacks, and drives
the existing pure-Python business logic (csv_parser, coordinate_transform,
pipeline, …).

Layout is NOT built here — it lives entirely in the Designer-authored
BP_PostRenderToolWidget asset.

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


# ComboBox options (must match the C++ declaration order in the Designer)
_AXIS_OPTIONS = ["X (0)", "Y (1)", "Z (2)"]
_AXIS_INDEX_MAP = {"X (0)": 0, "Y (1)": 1, "Z (2)": 2}
_INDEX_AXIS_MAP = {0: "X (0)", 1: "Y (1)", 2: "Z (2)"}

# Names that MUST exist on the BP (matches PostRenderToolWidget.h).
# Missing names cause a warning but not a crash — the binder degrades
# gracefully so a half-built BP still loads.
_REQUIRED_CONTROLS = (
    "btn_recheck", "btn_browse", "txt_file_path",
    "txt_frame_count", "txt_focal_range", "txt_timecode", "txt_sensor_width",
    "spn_fps", "txt_detected_fps",
    "spn_frame",
    "txt_designer_pos", "txt_designer_rot", "txt_ue_pos", "txt_ue_rot",
    "btn_spawn_cam",
    "cmb_pos_x_src", "spn_pos_x_scale",
    "cmb_pos_y_src", "spn_pos_y_scale",
    "cmb_pos_z_src", "spn_pos_z_scale",
    "cmb_rot_pitch_src", "spn_rot_pitch_scale",
    "cmb_rot_yaw_src", "spn_rot_yaw_scale",
    "cmb_rot_roll_src", "spn_rot_roll_scale",
    "btn_apply_mapping", "btn_save_mapping",
    "btn_import", "btn_open_seq", "btn_open_mrq",
    "txt_results",
)

# Optional controls — skipped silently if missing.
_OPTIONAL_CONTROLS = (
    "prereq_label_0", "prereq_label_1", "prereq_label_2",
    "prereq_label_3", "prereq_label_4", "prereq_label_5",
    "prereq_summary", "txt_frame_hint",
)


class PostRenderToolUI:
    """Binds the Designer-authored BP_PostRenderToolWidget to Python logic."""

    def __init__(self, host_widget):
        self._host = host_widget

        # State
        self._csv_path: str = ""
        self._fps: float = 0.0
        self._csv_result: Optional[CsvDenseResult] = None
        self._last_result: Optional[PipelineResult] = None
        self._test_camera_actor = None

        # Control refs
        self._controls: dict = {}
        self._prereq_labels: list = []

        self._acquire_all_controls()
        self._init_axis_combos()
        self._push_initial_mapping_values()
        self._bind_events()
        self._check_and_display_prereqs()

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------

    def _acquire(self, name: str, optional: bool = False):
        try:
            ref = self._host.get_editor_property(name)
        except Exception as exc:  # noqa: BLE001
            if not optional:
                unreal.log_warning(
                    f"[widget] '{name}' not accessible on host widget: {exc}. "
                    "Is BP_PostRenderToolWidget compiled against the current "
                    "UPostRenderToolWidget C++ class?"
                )
            return None
        if ref is None and not optional:
            unreal.log_warning(
                f"[widget] '{name}' UPROPERTY is None — widget missing in BP."
            )
        self._controls[name] = ref
        return ref

    def _acquire_all_controls(self):
        for name in _REQUIRED_CONTROLS:
            self._acquire(name, optional=False)
        for name in _OPTIONAL_CONTROLS:
            self._acquire(name, optional=True)

        self._prereq_labels = [
            self._controls.get(f"prereq_label_{i}") for i in range(6)
        ]

    def _get(self, name: str):
        return self._controls.get(name)

    # ------------------------------------------------------------------
    # Axis combo initialization
    # ------------------------------------------------------------------

    def _init_axis_combos(self):
        for key in ("cmb_pos_x_src", "cmb_pos_y_src", "cmb_pos_z_src",
                    "cmb_rot_pitch_src", "cmb_rot_yaw_src", "cmb_rot_roll_src"):
            combo = self._get(key)
            if combo is None:
                continue
            # Clear any options the Designer might have added, then repopulate.
            try:
                combo.clear_options()
            except Exception:
                pass
            for opt in _AXIS_OPTIONS:
                combo.add_option(opt)

    def _push_initial_mapping_values(self):
        pos = config.POSITION_MAPPING
        rot = config.ROTATION_MAPPING

        mapping = [
            ("cmb_pos_x_src", "spn_pos_x_scale", pos["x"]),
            ("cmb_pos_y_src", "spn_pos_y_scale", pos["y"]),
            ("cmb_pos_z_src", "spn_pos_z_scale", pos["z"]),
            ("cmb_rot_pitch_src", "spn_rot_pitch_scale", rot["pitch"]),
            ("cmb_rot_yaw_src", "spn_rot_yaw_scale", rot["yaw"]),
            ("cmb_rot_roll_src", "spn_rot_roll_scale", rot["roll"]),
        ]
        for combo_name, spn_name, (src_idx, scale) in mapping:
            combo = self._get(combo_name)
            spn = self._get(spn_name)
            if combo is not None:
                combo.set_selected_option(
                    _INDEX_AXIS_MAP.get(src_idx, _AXIS_OPTIONS[0])
                )
            if spn is not None:
                spn.set_editor_property("value", float(scale))

        spn_fps = self._get("spn_fps")
        if spn_fps is not None:
            spn_fps.set_editor_property("min_value", 0.0)
            spn_fps.set_editor_property("max_value", 120.0)
            spn_fps.set_editor_property("value", 0.0)

        spn_frame = self._get("spn_frame")
        if spn_frame is not None:
            spn_frame.set_editor_property("min_value", 0.0)
            spn_frame.set_editor_property("max_value", 0.0)
            spn_frame.set_editor_property("value", 0.0)

    # ------------------------------------------------------------------
    # Event binding
    # ------------------------------------------------------------------

    def _safe_clear(self, delegate, label: str):
        try:
            delegate.clear()
        except AttributeError:
            unreal.log_warning(
                f"[widget] {label}.clear() unavailable — callbacks may stack "
                "across reloads. Close & reopen the tab between reloads."
            )
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(f"[widget] Failed to clear {label}: {exc}")

    def _bind_click(self, name: str, handler):
        btn = self._get(name)
        if btn is None:
            return
        self._safe_clear(btn.on_clicked, f"{name}.on_clicked")
        btn.on_clicked.add_callable(handler)

    def _bind_value_changed(self, name: str, handler):
        spn = self._get(name)
        if spn is None:
            return
        self._safe_clear(spn.on_value_changed, f"{name}.on_value_changed")
        spn.on_value_changed.add_callable(handler)

    def _bind_events(self):
        self._bind_click("btn_recheck", self._on_recheck_prereqs)
        self._bind_click("btn_browse", self._on_browse_clicked)
        self._bind_value_changed("spn_fps", self._on_fps_changed)
        self._bind_value_changed("spn_frame", self._on_frame_changed)
        self._bind_click("btn_spawn_cam", self._on_spawn_test_camera)
        self._bind_click("btn_apply_mapping", self._on_apply_mapping)
        self._bind_click("btn_save_mapping", self._on_save_mapping)
        self._bind_click("btn_import", self._on_import_clicked)
        self._bind_click("btn_open_seq", self._on_open_sequencer_clicked)
        self._bind_click("btn_open_mrq", self._on_open_mrq_clicked)

    # ------------------------------------------------------------------
    # Setters
    # ------------------------------------------------------------------

    def _set_text(self, name: str, message: str):
        ctrl = self._get(name)
        if ctrl is None:
            return
        ctrl.set_text(unreal.Text(message))

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
            if lbl is None:
                if ok:
                    ok_count += 1
                continue
            if ok:
                lbl.set_text(unreal.Text(f"OK: {name}"))
                ok_count += 1
            else:
                detail = f" → {hint}" if hint else ""
                lbl.set_text(unreal.Text(f"MISSING: {name}{detail}"))

        summary = self._get("prereq_summary")
        if summary is not None:
            total = min(len(statuses), len(self._prereq_labels))
            summary.set_text(unreal.Text(f"{ok_count} / {total} OK"))

    def _on_recheck_prereqs(self):
        self._check_and_display_prereqs()
        unreal.log("[widget] Prerequisites rechecked.")

    # ------------------------------------------------------------------
    # CSV File & Preview
    # ------------------------------------------------------------------

    def _on_browse_clicked(self):
        csv_path = browse_csv_file()
        if not csv_path:
            unreal.log_warning("[widget] Browse cancelled.")
            return

        self._csv_path = csv_path
        self._set_text("txt_file_path", csv_path)

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
        self._set_text("txt_frame_count", f"Frames: {result.frame_count}")
        self._set_text(
            "txt_focal_range",
            f"Focal Length: {fl_min:.2f} – {fl_max:.2f} mm",
        )
        self._set_text(
            "txt_timecode",
            f"Timecode: {result.timecode_start} → {result.timecode_end}",
        )
        self._set_text(
            "txt_sensor_width",
            f"Sensor Width: {result.sensor_width_mm:.2f} mm",
        )
        if result.detected_fps is not None:
            self._set_text("txt_detected_fps", f"Auto: {result.detected_fps} fps")
        else:
            self._set_text("txt_detected_fps", "Auto: N/A")

        spn_frame = self._get("spn_frame")
        if spn_frame is not None:
            max_frame = max(0.0, float(result.frame_count - 1))
            spn_frame.set_editor_property("max_value", max_frame)
            spn_frame.set_editor_property("value", 0.0)

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

        spn_frame = self._get("spn_frame")
        if spn_frame is None:
            return
        idx = int(spn_frame.get_editor_property("value"))
        idx = max(0, min(idx, len(self._csv_result.frames) - 1))
        frame = self._csv_result.frames[idx]

        self._set_text(
            "txt_designer_pos",
            f"Designer Pos: ({frame.offset_x:.4f}, "
            f"{frame.offset_y:.4f}, {frame.offset_z:.4f}) m",
        )
        self._set_text(
            "txt_designer_rot",
            f"Designer Rot: ({frame.rotation_x:.2f}, "
            f"{frame.rotation_y:.2f}, {frame.rotation_z:.2f})°",
        )

        ue_pos = transform_position(frame.offset_x, frame.offset_y, frame.offset_z)
        ue_rot = transform_rotation(
            frame.rotation_x, frame.rotation_y, frame.rotation_z
        )
        self._set_text(
            "txt_ue_pos",
            f"UE Pos: ({ue_pos[0]:.1f}, {ue_pos[1]:.1f}, {ue_pos[2]:.1f}) cm",
        )
        self._set_text(
            "txt_ue_rot",
            f"UE Rot: P={ue_rot[0]:.2f}  Y={ue_rot[1]:.2f}  R={ue_rot[2]:.2f}°",
        )

        hint = self._get("txt_frame_hint")
        if hint is not None:
            total = max(0, len(self._csv_result.frames) - 1)
            hint.set_text(unreal.Text(f"{idx} / {total}"))

    def _on_frame_changed(self, value: float):
        self._refresh_coord_preview()

    def _on_spawn_test_camera(self):
        if self._csv_result is None or not self._csv_result.frames:
            self._set_results("No CSV loaded. Browse a file first.")
            return

        spn_frame = self._get("spn_frame")
        if spn_frame is None:
            return
        idx = int(spn_frame.get_editor_property("value"))
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
        def axis_index(combo_name: str) -> int:
            combo = self._get(combo_name)
            if combo is None:
                return 0
            return _AXIS_INDEX_MAP.get(combo.get_selected_option(), 0)

        def scale(spn_name: str) -> float:
            spn = self._get(spn_name)
            if spn is None:
                return 0.0
            return spn.get_editor_property("value")

        return (
            {
                "x": (axis_index("cmb_pos_x_src"), scale("spn_pos_x_scale")),
                "y": (axis_index("cmb_pos_y_src"), scale("spn_pos_y_scale")),
                "z": (axis_index("cmb_pos_z_src"), scale("spn_pos_z_scale")),
            },
            {
                "pitch": (axis_index("cmb_rot_pitch_src"), scale("spn_rot_pitch_scale")),
                "yaw": (axis_index("cmb_rot_yaw_src"), scale("spn_rot_yaw_scale")),
                "roll": (axis_index("cmb_rot_roll_src"), scale("spn_rot_roll_scale")),
            },
        )

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
    # Misc
    # ------------------------------------------------------------------

    def _set_results(self, message: str):
        ctrl = self._get("txt_results")
        if ctrl is None:
            return
        ctrl.set_text(unreal.Text(message))
