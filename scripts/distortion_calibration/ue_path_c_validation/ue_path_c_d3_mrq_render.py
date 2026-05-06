"""Import canonical D3 Path C CSVs into a duplicated /Game/Main and render MRQ frames.

This script runs inside an already-open UE Editor through remote_execution.
It never edits production /Game/Main directly. Instead it duplicates /Game/Main
to /Game/PathCD3RenderValidation/PathCD3Render_Main, imports the canonical CSVs
there, and dispatches one PNG MRQ frame per controlled case.
"""

from __future__ import annotations

import json
import gc
import shutil
from pathlib import Path

import unreal


REMOTE_CANONICAL_ROOT = Path("C:/temp/ue-remote/path_c_d3_exports/canonical")
REPORT_JSON = Path("C:/temp/ue-remote/path_c_d3_mrq_render.json")
OUT_ROOT = Path("C:/temp/ue-remote/path_c_d3_render")

SOURCE_MAP = "/Game/Main"
ASSET_ROOT = "/Game/PathCD3RenderValidation"
RENDER_MAP = f"{ASSET_ROOT}/PathCD3Render_Main"
IMPORT_ROOT = f"{ASSET_ROOT}/Imports"
FPS = 24.0
RESOLUTION_X = 1920
RESOLUTION_Y = 1080

ORDERED_CONTROLLED_CASES = (
    ("focal_k_axis", "path_c_focal24_k_zero"),
    ("focal_k_axis", "path_c_focal24_k1_p0p5"),
    ("focal_k_axis", "path_c_focal30p302_k_zero"),
    ("focal_k_axis", "path_c_focal30p302_k1_p0p5"),
    ("focal_k_axis", "path_c_focal50_k_zero"),
    ("focal_k_axis", "path_c_focal50_k1_p0p5"),
    ("focal_k_axis", "path_c_focal30p302_k2_p0p5"),
    ("focal_k_axis", "path_c_focal30p302_k3_p0p5"),
    ("center_shift", "path_c_center_k1_p0p5_shift_zero"),
    ("center_shift", "path_c_center_k1_p0p5_shiftx_n0p5"),
    ("center_shift", "path_c_center_k1_p0p5_shiftx_p0p5"),
    ("center_shift", "path_c_center_k1_p0p5_shifty_n0p5"),
    ("center_shift", "path_c_center_k1_p0p5_shifty_p0p5"),
)

REQUIRED_DISTORTION_TRACKS = {
    "K1",
    "K2",
    "K3",
    "CenterU",
    "CenterV",
    "Aspect",
    "DistortionWeight",
}

REQUIRED_PROJECTION_TRACKS = {
    "SensorHorizontalOffset",
    "SensorVerticalOffset",
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


def _reset_render_assets() -> None:
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


def _sequence_track_summary(sequence) -> dict[str, object]:
    bindings = []
    distortion_tracks = set()
    projection_tracks = set()
    for binding in sequence.get_bindings():
        tracks = []
        for track in binding.get_tracks():
            display_name = _display_name(track.get_display_name())
            tracks.append(
                {
                    "display_name": display_name,
                    "track_class": track.get_class().get_name(),
                    "section_count": len(track.get_sections()),
                }
            )
            if display_name in REQUIRED_DISTORTION_TRACKS:
                distortion_tracks.add(display_name)
            if display_name in REQUIRED_PROJECTION_TRACKS:
                projection_tracks.add(display_name)
        bindings.append({"name": str(binding.get_name()), "track_count": len(tracks), "tracks": tracks})
    missing_distortion = sorted(REQUIRED_DISTORTION_TRACKS - distortion_tracks)
    missing_projection = sorted(REQUIRED_PROJECTION_TRACKS - projection_tracks)
    track_status = "PASS" if not missing_distortion and not missing_projection else "FAIL"
    return {
        "bindings": bindings,
        "distortion_tracks": sorted(distortion_tracks),
        "projection_tracks": sorted(projection_tracks),
        "missing_distortion_tracks": missing_distortion,
        "missing_projection_tracks": missing_projection,
        "distortion_track_status": "PASS" if not missing_distortion else "FAIL",
        "track_status": track_status,
    }


def _controlled_csvs() -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    for group, case_id in ORDERED_CONTROLLED_CASES:
        path = REMOTE_CANONICAL_ROOT / group / f"{case_id}.csv"
        if not path.exists():
            raise RuntimeError(f"missing ordered controlled CSV: {path}")
        paths.append((case_id, path))
    return paths


def _configure_job(queue, case_id: str, sequence_path: str) -> str:
    job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
    job.sequence = unreal.SoftObjectPath(sequence_path)
    job.map = unreal.SoftObjectPath(RENDER_MAP)
    job.job_name = f"PathCD3_{case_id}"

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

    out_dir = OUT_ROOT / case_id
    output = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    output.output_directory = unreal.DirectoryPath(str(out_dir).replace("\\", "/"))
    output.file_name_format = f"{case_id}.{{frame_number}}"
    output.output_resolution = unreal.IntPoint(RESOLUTION_X, RESOLUTION_Y)
    output.use_custom_playback_range = True
    output.custom_start_frame = 0
    output.custom_end_frame = 1
    return str(out_dir)


def run() -> dict[str, object]:
    report: dict[str, object] = {
        "status": "FAIL",
        "source_map": SOURCE_MAP,
        "render_map": RENDER_MAP,
        "asset_root": ASSET_ROOT,
        "import_root": IMPORT_ROOT,
        "output_root": str(OUT_ROOT),
        "resolution": {"x": RESOLUTION_X, "y": RESOLUTION_Y},
        "imports": [],
        "jobs": [],
    }

    try:
        if not REMOTE_CANONICAL_ROOT.exists():
            raise RuntimeError(f"missing canonical root: {REMOTE_CANONICAL_ROOT}")

        _reset_render_assets()

        # 模块缓存清理: open UE Editor 跨多次 remote_execution 调用会缓存
        # plugin 模块, SCP 推送的新代码必须强制 reload, 否则 MRQ 会用旧公式渲染.
        import importlib
        from post_render_tool import config as prt_config
        import post_render_tool.distortion_math as prt_distortion_math
        import post_render_tool.sequence_builder as prt_sequence_builder
        import post_render_tool.pipeline as prt_pipeline
        prt_config = importlib.reload(prt_config)
        importlib.reload(prt_distortion_math)
        importlib.reload(prt_sequence_builder)
        prt_pipeline = importlib.reload(prt_pipeline)
        run_import = prt_pipeline.run_import

        old_asset_root = prt_config.ASSET_BASE_PATH
        prt_config.ASSET_BASE_PATH = IMPORT_ROOT

        try:
            for case_id, csv_path in _controlled_csvs():
                result = run_import(str(csv_path), fps=FPS)
                item: dict[str, object] = {
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
            _save_current_level()

        failed_imports = [
            item
            for item in report["imports"]
            if not item.get("success") or item.get("track_status") != "PASS"
        ]
        if failed_imports:
            report["status"] = "FAIL"
            report["failed_imports"] = failed_imports
            return report

        queue_subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        queue = queue_subsystem.get_queue()
        for job in list(queue.get_jobs()):
            queue.delete_job(job)

        for item in report["imports"]:
            sequence_path = str(item["sequence_path"]).split(".", 1)[0]
            output_dir = _configure_job(queue, str(item["case"]), sequence_path)
            report["jobs"].append(
                {
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
