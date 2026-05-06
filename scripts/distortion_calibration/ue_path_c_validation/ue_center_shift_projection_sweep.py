"""UE-side Path C centerShift projection sign sweep.

DEPRECATED 2026-05-07. The 8-config sign × Y-normalizer sweep that drove this
script existed because the centerShift formula was unknown. K=0 control frames
on 2026-05-07 directly measured the formula (`pixel = cs × image_dim /
sensor_dim_mm`, focal-independent), and `distortion_math.map_center_shift_projection`
was hardcoded to that single answer. The four config knobs this script used to
mutate (`CENTER_SHIFT_PROJECTION_X_SIGN` / `Y_SIGN` / `Y_NORMALIZER` /
`ENABLE_PROJECTION_TRACKS`) have been removed from `config.py`.

Kept in the tree as historical artefact for `git log` archaeology. Running it
will raise immediately. To validate the production formula end-to-end, run
`pipeline.run_import()` directly against a centerShift CSV and phase-correlate
the resulting render against the matching D3 frame.

Runs inside an already-open UE Editor through remote_execution. It imports the
five canonical centerShift CSVs four times, once for every
Filmback.Sensor*Offset sign pair, then dispatches one MRQ PNG frame per case.

The script intentionally writes only validation assets under
``/Game/PathCD3CenterShiftProjectionSweep`` and render outputs under
``C:/temp/ue-remote/path_c_center_shift_projection_sweep``.
"""

from __future__ import annotations

import gc
import importlib
import json
import shutil
from pathlib import Path

import unreal


REMOTE_CANONICAL_ROOT = Path("C:/temp/ue-remote/path_c_d3_exports/canonical")
REPORT_JSON = Path("C:/temp/ue-remote/center_shift_projection_sweep_dispatch.json")
OUT_ROOT = Path("C:/temp/ue-remote/path_c_center_shift_projection_sweep")

SOURCE_MAP = "/Game/Main"
ASSET_ROOT = "/Game/PathCD3CenterShiftProjectionSweep"
RENDER_MAP = f"{ASSET_ROOT}/PathCD3CenterShiftProjectionSweep_Main"
IMPORT_ROOT = f"{ASSET_ROOT}/Imports"
FPS = 24.0
RESOLUTION_X = 1920
RESOLUTION_Y = 1080

CENTER_SHIFT_CASES = (
    "path_c_center_k1_p0p5_shift_zero",
    "path_c_center_k1_p0p5_shiftx_n0p5",
    "path_c_center_k1_p0p5_shiftx_p0p5",
    "path_c_center_k1_p0p5_shifty_n0p5",
    "path_c_center_k1_p0p5_shifty_p0p5",
)

SIGN_SWEEPS = (
    # (sweep_id, x_sign, y_sign, y_normalizer)
    ("xp_yp_height",  1.0,  1.0, "sensor_height"),
    ("xp_yn_height",  1.0, -1.0, "sensor_height"),
    ("xn_yp_height", -1.0,  1.0, "sensor_height"),
    ("xn_yn_height", -1.0, -1.0, "sensor_height"),
    ("xp_yp_width",   1.0,  1.0, "sensor_width"),
    ("xp_yn_width",   1.0, -1.0, "sensor_width"),
    ("xn_yp_width",  -1.0,  1.0, "sensor_width"),
    ("xn_yn_width",  -1.0, -1.0, "sensor_width"),
)

REQUIRED_TRACK_TOKENS = {
    "distortion": {
        "k1",
        "k2",
        "k3",
        "centeru",
        "centerv",
        "aspect",
        "distortionweight",
    },
    "projection": {
        "sensorhorizontaloffset",
        "sensorverticaloffset",
    },
}


def _write_report(payload: dict[str, object]) -> None:
    REPORT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_level(level_path: str) -> None:
    for fn in (
        lambda: unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(level_path),
        lambda: unreal.EditorLevelLibrary.load_level(level_path),
    ):
        try:
            result = fn()
            if result is not False:
                return
        except Exception:
            pass
    raise RuntimeError(f"could not load level: {level_path}")


def _save_current_level() -> None:
    for fn in (
        lambda: unreal.EditorLevelLibrary.save_current_level(),
        lambda: unreal.EditorLoadingAndSavingUtils.save_current_level(),
    ):
        try:
            result = fn()
            if result is not False:
                return
        except Exception:
            pass
    raise RuntimeError("could not save current level")


def _reset_assets() -> None:
    if not unreal.EditorAssetLibrary.does_asset_exist(SOURCE_MAP):
        raise RuntimeError(f"missing source map: {SOURCE_MAP}")

    _load_level(SOURCE_MAP)
    if unreal.EditorAssetLibrary.does_directory_exist(ASSET_ROOT):
        unreal.EditorAssetLibrary.delete_directory(ASSET_ROOT)
    unreal.EditorAssetLibrary.make_directory(ASSET_ROOT)

    duplicated = unreal.EditorAssetLibrary.duplicate_asset(SOURCE_MAP, RENDER_MAP)
    if duplicated is None:
        raise RuntimeError(f"could not duplicate {SOURCE_MAP} to {RENDER_MAP}")
    unreal.EditorAssetLibrary.save_asset(RENDER_MAP)
    del duplicated
    gc.collect()
    try:
        unreal.SystemLibrary.collect_garbage()
    except Exception:
        pass
    _load_level(RENDER_MAP)

    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)


def _display_name(value) -> str:
    if hasattr(value, "to_string"):
        try:
            return value.to_string()
        except Exception:
            pass
    return str(value)


def _property_debug(track) -> dict[str, str]:
    debug: dict[str, str] = {}
    for prop in ("property_name", "property_path"):
        try:
            debug[prop] = str(track.get_editor_property(prop))
        except Exception:
            pass
    return debug


def _normalize(value: object) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _track_token(track) -> str:
    pieces = [_display_name(track.get_display_name())]
    pieces.extend(_property_debug(track).values())
    return _normalize(" ".join(pieces))


def _sequence_track_summary(sequence) -> dict[str, object]:
    bindings = []
    found_distortion: set[str] = set()
    found_projection: set[str] = set()
    for binding in sequence.get_bindings():
        tracks = []
        for track in binding.get_tracks():
            token = _track_token(track)
            display_name = _display_name(track.get_display_name())
            for required in REQUIRED_TRACK_TOKENS["distortion"]:
                if required in token:
                    found_distortion.add(required)
            for required in REQUIRED_TRACK_TOKENS["projection"]:
                if required in token:
                    found_projection.add(required)
            tracks.append(
                {
                    "display_name": display_name,
                    "track_class": track.get_class().get_name(),
                    "section_count": len(track.get_sections()),
                    "property_debug": _property_debug(track),
                }
            )
        bindings.append({"name": str(binding.get_name()), "track_count": len(tracks), "tracks": tracks})

    missing_distortion = sorted(REQUIRED_TRACK_TOKENS["distortion"] - found_distortion)
    missing_projection = sorted(REQUIRED_TRACK_TOKENS["projection"] - found_projection)
    return {
        "bindings": bindings,
        "distortion_tracks_found": sorted(found_distortion),
        "projection_tracks_found": sorted(found_projection),
        "missing_distortion_tracks": missing_distortion,
        "missing_projection_tracks": missing_projection,
        "track_status": "PASS" if not missing_distortion and not missing_projection else "FAIL",
    }


def _center_shift_csvs() -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    for case_id in CENTER_SHIFT_CASES:
        path = REMOTE_CANONICAL_ROOT / "center_shift" / f"{case_id}.csv"
        if not path.exists():
            raise RuntimeError(f"missing centerShift CSV: {path}")
        paths.append((case_id, path))
    return paths


def _configure_job(queue, sign_id: str, case_id: str, sequence_path: str) -> str:
    job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
    job.sequence = unreal.SoftObjectPath(sequence_path)
    job.map = unreal.SoftObjectPath(RENDER_MAP)
    job.job_name = f"PathCD3CenterShift_{sign_id}_{case_id}"

    config = job.get_configuration()
    config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    config.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)

    try:
        aa = config.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
        aa.set_editor_property("spatial_sample_count", 1)
        aa.set_editor_property("temporal_sample_count", 1)
        aa.set_editor_property("override_anti_aliasing", True)
        aa.set_editor_property("anti_aliasing_method", unreal.AntiAliasingMethod.AAM_NONE)
    except Exception:
        pass

    out_dir = OUT_ROOT / sign_id / case_id
    output = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    output.output_directory = unreal.DirectoryPath(str(out_dir).replace("\\", "/"))
    output.file_name_format = f"{case_id}.{{frame_number}}"
    output.output_resolution = unreal.IntPoint(RESOLUTION_X, RESOLUTION_Y)
    output.use_custom_playback_range = True
    output.custom_start_frame = 0
    output.custom_end_frame = 1
    return str(out_dir)


def run() -> dict[str, object]:
    raise RuntimeError(
        "ue_center_shift_projection_sweep is deprecated 2026-05-07; "
        "centerShift formula is hardcoded in distortion_math.map_center_shift_projection. "
        "See docs/distortion-investigation.md '2026-05-07 — K=0 直接测量'."
    )

    # Unreachable: kept so static tooling sees the original sweep loop in git log.
    report: dict[str, object] = {
        "status": "FAIL",
        "selection_status": "PENDING_RENDER_COMPARE",
        "source_map": SOURCE_MAP,
        "render_map": RENDER_MAP,
        "asset_root": ASSET_ROOT,
        "import_root": IMPORT_ROOT,
        "output_root": str(OUT_ROOT),
        "resolution": {"x": RESOLUTION_X, "y": RESOLUTION_Y},
        "sign_sweeps": [
            {"id": sid, "x_sign": xs, "y_sign": ys, "y_normalizer": yn}
            for sid, xs, ys, yn in SIGN_SWEEPS
        ],
        "imports": [],
        "jobs": [],
    }

    try:
        if not REMOTE_CANONICAL_ROOT.exists():
            raise RuntimeError(f"missing canonical root: {REMOTE_CANONICAL_ROOT}")

        _reset_assets()

        from post_render_tool import config as prt_config
        import post_render_tool.distortion_math as prt_distortion_math
        import post_render_tool.sequence_builder as prt_sequence_builder
        import post_render_tool.pipeline as prt_pipeline

        # The open Editor keeps Python modules cached across remote executions.
        # Reload the changed pure-Python modules so SCP'd plugin edits are used.
        prt_config = importlib.reload(prt_config)
        importlib.reload(prt_distortion_math)
        importlib.reload(prt_sequence_builder)
        prt_pipeline = importlib.reload(prt_pipeline)
        run_import = prt_pipeline.run_import

        old_asset_root = prt_config.ASSET_BASE_PATH
        old_enable_projection = prt_config.CENTER_SHIFT_ENABLE_PROJECTION_TRACKS
        old_x_sign = prt_config.CENTER_SHIFT_PROJECTION_X_SIGN
        old_y_sign = prt_config.CENTER_SHIFT_PROJECTION_Y_SIGN
        old_y_normalizer = prt_config.CENTER_SHIFT_PROJECTION_Y_NORMALIZER

        try:
            for sign_id, x_sign, y_sign, y_norm in SIGN_SWEEPS:
                prt_config.ASSET_BASE_PATH = f"{IMPORT_ROOT}/{sign_id}"
                prt_config.CENTER_SHIFT_ENABLE_PROJECTION_TRACKS = True
                prt_config.CENTER_SHIFT_PROJECTION_X_SIGN = x_sign
                prt_config.CENTER_SHIFT_PROJECTION_Y_SIGN = y_sign
                prt_config.CENTER_SHIFT_PROJECTION_Y_NORMALIZER = y_norm
                for case_id, csv_path in _center_shift_csvs():
                    result = run_import(str(csv_path), fps=FPS)
                    item: dict[str, object] = {
                        "sign_id": sign_id,
                        "x_sign": x_sign,
                        "y_sign": y_sign,
                        "y_normalizer": y_norm,
                        "case": case_id,
                        "csv_path": str(csv_path),
                        "success": bool(result.success),
                        "error_message": result.error_message,
                        "package_path": result.package_path,
                    }
                    if result.success:
                        sequence = result.level_sequence
                        camera = result.camera_actor
                        item.update(
                            {
                                "sequence_path": sequence.get_path_name() if sequence else "",
                                "camera_label": camera.get_actor_label() if camera else "",
                            }
                        )
                        item.update(_sequence_track_summary(sequence))
                    report["imports"].append(item)
        finally:
            prt_config.ASSET_BASE_PATH = old_asset_root
            prt_config.CENTER_SHIFT_ENABLE_PROJECTION_TRACKS = old_enable_projection
            prt_config.CENTER_SHIFT_PROJECTION_X_SIGN = old_x_sign
            prt_config.CENTER_SHIFT_PROJECTION_Y_SIGN = old_y_sign
            prt_config.CENTER_SHIFT_PROJECTION_Y_NORMALIZER = old_y_normalizer
            _save_current_level()

        failed_imports = [
            item
            for item in report["imports"]
            if not item.get("success") or item.get("track_status") != "PASS"
        ]
        if failed_imports:
            report["failed_imports"] = failed_imports
            return report

        queue_subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        queue = queue_subsystem.get_queue()
        for job in list(queue.get_jobs()):
            queue.delete_job(job)

        for item in report["imports"]:
            sequence_path = str(item["sequence_path"]).split(".", 1)[0]
            output_dir = _configure_job(
                queue,
                str(item["sign_id"]),
                str(item["case"]),
                sequence_path,
            )
            report["jobs"].append(
                {
                    "sign_id": item["sign_id"],
                    "x_sign": item["x_sign"],
                    "y_sign": item["y_sign"],
                    "y_normalizer": item["y_normalizer"],
                    "case": item["case"],
                    "map": RENDER_MAP,
                    "sequence": sequence_path,
                    "output_dir": output_dir,
                }
            )

        executor = queue_subsystem.render_queue_with_executor(unreal.MoviePipelinePIEExecutor)
        report["status"] = "DISPATCHED" if executor is not None else "FAIL"
    except Exception as exc:
        report["error"] = str(exc)

    return report


if __name__ == "__main__":
    payload = run()
    _write_report(payload)
    if payload["status"] == "FAIL":
        raise SystemExit(1)
