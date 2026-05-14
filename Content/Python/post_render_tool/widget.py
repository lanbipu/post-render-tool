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

from typing import Optional

import unreal

from . import config
from .csv_parser import CsvParseError, parse_csv_dense
from .path_display import format_middle_ellipsis_path
from .pipeline import PipelineResult, run_import
from .ui_interface import (
    browse_csv_file,
    get_prerequisite_status,
    open_movie_render_queue,
    open_sequencer,
    save_axis_mapping,
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
    "spn_fps",
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

# Optional controls — skipped silently if missing. The three rotation offset
# SpinBoxes live here so pre-offset BP assets still load; user runs
# rebuild_from_spec() to add them, otherwise edits ROTATION_OFFSET_DEG
# directly in config.py.
_OPTIONAL_CONTROLS = (
    "lbl_root_scroll",
    "prereq_label_0", "prereq_label_1", "prereq_label_2",
    "prereq_label_3", "prereq_label_4", "prereq_label_5",
    "prereq_summary",
    "spn_rot_pitch_offset", "spn_rot_yaw_offset", "spn_rot_roll_offset",
    # P1 timecode-sync controls — task 12
    "txt_render_output_dir", "btn_patch_exr_timecode", "btn_export_otio",
)

class PostRenderToolUI:
    """Binds the Designer-authored BP_PostRenderToolWidget to Python logic."""

    def __init__(self, host_widget):
        self._host = host_widget

        # State
        self._csv_path: str = ""
        self._csv_result = None
        self._fps: float = 0.0
        self._last_result: Optional[PipelineResult] = None

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
        offset = config.ROTATION_OFFSET_DEG

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

        # Rotation offsets (degrees). Allow ±360 so users can enter any
        # conventional re-orientation (-90, 90, 180, …).
        for spn_name, key in (
            ("spn_rot_pitch_offset", "pitch"),
            ("spn_rot_yaw_offset", "yaw"),
            ("spn_rot_roll_offset", "roll"),
        ):
            spn = self._get(spn_name)
            if spn is None:
                continue
            spn.set_editor_property("min_value", -360.0)
            spn.set_editor_property("max_value", 360.0)
            spn.set_editor_property("value", float(offset[key]))

        spn_fps = self._get("spn_fps")
        if spn_fps is not None:
            spn_fps.set_editor_property("min_value", 0.0)
            spn_fps.set_editor_property("max_value", 120.0)
            spn_fps.set_editor_property("value", 0.0)

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
        self._bind_click("btn_apply_mapping", self._on_apply_mapping)
        self._bind_click("btn_save_mapping", self._on_save_mapping)
        self._bind_click("btn_import", self._on_import_clicked)
        self._bind_click("btn_open_seq", self._on_open_sequencer_clicked)
        self._bind_click("btn_open_mrq", self._on_open_mrq_clicked)
        # P1 timecode-sync (optional — bind only if BP has the buttons)
        self._bind_click("btn_patch_exr_timecode", self._on_patch_exr_timecode_clicked)
        self._bind_click("btn_export_otio", self._on_export_otio_clicked)

    # ------------------------------------------------------------------
    # Setters
    # ------------------------------------------------------------------

    def _set_text(self, name: str, message: str):
        ctrl = self._get(name)
        if ctrl is None:
            return
        ctrl.set_text(unreal.Text(message))

    def _on_csv_preview_loaded(self, _result):
        """Extension hook for alternate UI layouts."""

    def _on_mapping_applied(self):
        """Extension hook for alternate UI layouts."""

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
        self._set_text("txt_file_path", format_middle_ellipsis_path(csv_path))

        try:
            result = parse_csv_dense(csv_path)
        except CsvParseError as exc:
            self._csv_result = None
            self._on_csv_preview_loaded(None)
            self._set_results(f"CSV Error: {exc}")
            unreal.log_warning(f"[widget] CSV parse error: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            self._csv_result = None
            self._on_csv_preview_loaded(None)
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
        self._on_csv_preview_loaded(result)

        unreal.log(f"[widget] CSV preview loaded: {csv_path}")

    def _on_fps_changed(self, value: float):
        self._fps = value

    # ------------------------------------------------------------------
    # Axis Mapping
    # ------------------------------------------------------------------

    # Mandatory set — missing any of these blocks Apply/Save. Rotation offset
    # SpinBoxes are intentionally excluded; they degrade to the current
    # config value (see _read_mapping_from_ui) so legacy BPs still work.
    _MAPPING_CONTROLS = (
        "cmb_pos_x_src", "spn_pos_x_scale",
        "cmb_pos_y_src", "spn_pos_y_scale",
        "cmb_pos_z_src", "spn_pos_z_scale",
        "cmb_rot_pitch_src", "spn_rot_pitch_scale",
        "cmb_rot_yaw_src", "spn_rot_yaw_scale",
        "cmb_rot_roll_src", "spn_rot_roll_scale",
    )

    def _missing_mapping_controls(self) -> bool:
        """Return True if any axis-mapping widget reference is None.

        Guards against silent data corruption in ``_on_apply_mapping`` and
        ``_on_save_mapping`` — if a SpinBox is missing, ``_read_mapping_from_ui``
        returns ``0.0`` for that axis, which would zero out the scale factor
        and break coordinate transforms.
        """
        missing = [name for name in self._MAPPING_CONTROLS if self._get(name) is None]
        if missing:
            unreal.log_warning(
                f"[widget] Missing axis mapping controls: {', '.join(missing)}"
            )
        return bool(missing)

    def _read_mapping_from_ui(self) -> tuple:
        """Return (pos_mapping, rot_mapping, rot_offset_deg) read from widgets.

        If an offset SpinBox is absent (legacy BP before `rebuild_from_spec`
        added the widgets), that axis falls back to the current
        config.ROTATION_OFFSET_DEG value rather than zeroing it out. This
        keeps user-edited offsets intact when Apply/Save is clicked on a
        not-yet-regenerated Blueprint.
        """
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

        def offset(spn_name: str, key: str) -> float:
            spn = self._get(spn_name)
            if spn is None:
                return float(config.ROTATION_OFFSET_DEG.get(key, 0.0))
            return float(spn.get_editor_property("value"))

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
            {
                "pitch": offset("spn_rot_pitch_offset", "pitch"),
                "yaw":   offset("spn_rot_yaw_offset",   "yaw"),
                "roll":  offset("spn_rot_roll_offset",  "roll"),
            },
        )

    def _on_apply_mapping(self):
        if self._missing_mapping_controls():
            self._set_results(
                "Cannot apply mapping: one or more axis controls are missing "
                "from the Blueprint. Check the Output Log for details."
            )
            return

        pos_mapping, rot_mapping, rot_offset = self._read_mapping_from_ui()

        # coordinate_transform reads config.POSITION_MAPPING / ROTATION_MAPPING /
        # ROTATION_OFFSET_DEG on every call, so mutating the config dicts is
        # enough — no reload or global rebind needed.
        config.POSITION_MAPPING = pos_mapping
        config.ROTATION_MAPPING = rot_mapping
        config.ROTATION_OFFSET_DEG = rot_offset

        self._set_results(
            "Axis mapping + rotation offset applied (in memory)."
        )
        self._on_mapping_applied()
        unreal.log("[widget] Axis mapping + rotation offset applied in memory.")

    def _on_save_mapping(self):
        if self._missing_mapping_controls():
            self._set_results(
                "Cannot save mapping: one or more axis controls are missing "
                "from the Blueprint. Check the Output Log for details."
            )
            return

        pos_mapping, rot_mapping, rot_offset = self._read_mapping_from_ui()
        try:
            save_axis_mapping(pos_mapping, rot_mapping, rot_offset)
            self._set_results(
                "Axis mapping + rotation offset saved to config.py successfully."
            )
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

        pipeline_result = run_import(self._csv_path, self._fps)
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
        seq = self._last_result.level_sequence if self._last_result else None
        open_movie_render_queue(seq)

    # ------------------------------------------------------------------
    # P1 timecode-sync — Patch EXR timecode / Export OTIO sidecar
    # ------------------------------------------------------------------

    def _get_render_output_dir(self) -> Optional[str]:
        """Read render_output_dir text input. Returns None on empty / missing."""
        ctrl = self._get("txt_render_output_dir")
        if ctrl is None:
            self._set_results(
                "txt_render_output_dir widget 缺失 — 跑 rebuild_from_spec() "
                "把 P1 控件加进 BP, 然后重开 widget."
            )
            return None
        text = str(ctrl.get_text()).strip()
        if not text:
            self._set_results("请先在 'Render output dir' 输入框填渲染输出目录。")
            return None
        return text

    def _on_patch_exr_timecode_clicked(self):
        if self._last_result is None or self._last_result.level_sequence_path is None:
            self._set_results("还没 Import LevelSequence — 跑 Import 后再 patch EXR.")
            return
        output_dir = self._get_render_output_dir()
        if output_dir is None:
            return
        ls_path = self._last_result.level_sequence_path
        from .ui_interface import derive_mrq_filename_pattern
        from .pipeline import run_patch_exr_timecode
        pattern, _pad = derive_mrq_filename_pattern(ls_path)
        try:
            res = run_patch_exr_timecode(ls_path, output_dir, pattern)
            self._set_results(
                f"Patched {res['patched_count']} EXR file(s) with "
                f"start_timecode={res['start_timecode']} in:\n"
                f"{output_dir}\npattern: {pattern}"
            )
        except Exception as exc:  # noqa: BLE001
            self._set_results(f"Patch EXR timecode 失败: {exc}")

    def _on_export_otio_clicked(self):
        if self._last_result is None or self._last_result.level_sequence_path is None:
            self._set_results("还没 Import LevelSequence — 跑 Import 后再 export OTIO.")
            return
        output_dir = self._get_render_output_dir()
        if output_dir is None:
            return
        ls_path = self._last_result.level_sequence_path
        shot_name = ls_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        sidecar = output_dir.rstrip("/").rstrip("\\") + f"/{shot_name}.otio"
        from .ui_interface import derive_mrq_filename_pattern
        from .pipeline import run_export_otio
        pattern, _pad = derive_mrq_filename_pattern(ls_path)
        try:
            res = run_export_otio(ls_path, output_dir, sidecar, pattern)
            self._set_results(
                f"OTIO sidecar written: {res['sidecar_path']}\n"
                f"frame_count={res['frame_count']}, "
                f"start_timecode={res['start_timecode']}\n"
                f"pattern: {pattern}"
            )
        except Exception as exc:  # noqa: BLE001
            self._set_results(f"Export OTIO 失败: {exc}")

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _set_results(self, message: str):
        ctrl = self._get("txt_results")
        if ctrl is None:
            return
        ctrl.set_text(unreal.Text(message))
