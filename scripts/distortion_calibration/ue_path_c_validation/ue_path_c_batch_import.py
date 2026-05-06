"""Batch-import canonical Path C D3 CSV exports inside an open UE Editor.

Intended usage is via the existing lanPC remote-execution bridge:

    python.exe C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/ue_path_c_batch_import.py

The script reads canonical CSVs copied to
``C:/temp/ue-remote/path_c_d3_exports/canonical`` and imports them into an
isolated validation asset root instead of production ``/Game/PostRender``.
"""

from __future__ import annotations

import json
from pathlib import Path

import unreal


REMOTE_CANONICAL_ROOT = Path("C:/temp/ue-remote/path_c_d3_exports/canonical")
REPORT_JSON = Path("C:/temp/ue-remote/path_c_d3_batch_import.json")
ASSET_ROOT = "/Game/PathCD3Validation"
IMPORT_ROOT = f"{ASSET_ROOT}/Imports"
LEVEL_PATH = f"{ASSET_ROOT}/PathCD3Validation_ImportSmoke_Level"
FPS = 24.0


CONTROLLED_GROUPS = ("focal_k_axis", "center_shift")
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


def _asset_name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _new_level(level_path: str) -> None:
    parent = level_path.rsplit("/", 1)[0]
    if not unreal.EditorAssetLibrary.does_directory_exist(parent):
        unreal.EditorAssetLibrary.make_directory(parent)
    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        unreal.EditorAssetLibrary.delete_asset(level_path)

    for fn in (
        lambda: unreal.EditorLevelLibrary.new_level(level_path),
        lambda: unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).new_level(level_path),
    ):
        try:
            result = fn()
            if result is not False:
                return
        except Exception:
            pass
    raise RuntimeError(f"could not create validation level: {level_path}")


def _reset_validation_root() -> None:
    if unreal.EditorAssetLibrary.does_directory_exist(ASSET_ROOT):
        unreal.EditorAssetLibrary.delete_directory(ASSET_ROOT)
    unreal.EditorAssetLibrary.make_directory(ASSET_ROOT)


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
    for binding in sequence.get_bindings():
        binding_name = str(binding.get_name())
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
        bindings.append(
            {
                "name": binding_name,
                "track_count": len(tracks),
                "tracks": tracks,
            }
        )
    missing = sorted(REQUIRED_DISTORTION_TRACKS - distortion_tracks)
    return {
        "bindings": bindings,
        "distortion_tracks": sorted(distortion_tracks),
        "missing_distortion_tracks": missing,
        "distortion_track_status": "PASS" if not missing else "FAIL",
    }


def _controlled_csvs() -> list[Path]:
    paths: list[Path] = []
    for group, case_id in ORDERED_CONTROLLED_CASES:
        path = REMOTE_CANONICAL_ROOT / group / f"{case_id}.csv"
        if not path.exists():
            raise RuntimeError(f"missing ordered controlled CSV: {path}")
        paths.append(path)
    return paths


def run() -> dict[str, object]:
    if not REMOTE_CANONICAL_ROOT.exists():
        raise RuntimeError(f"missing canonical root: {REMOTE_CANONICAL_ROOT}")

    _reset_validation_root()
    _new_level(LEVEL_PATH)

    from post_render_tool import config as prt_config
    from post_render_tool.pipeline import run_import

    old_asset_root = prt_config.ASSET_BASE_PATH
    prt_config.ASSET_BASE_PATH = IMPORT_ROOT

    report: dict[str, object] = {
        "status": "PASS",
        "canonical_root": str(REMOTE_CANONICAL_ROOT),
        "asset_root": IMPORT_ROOT,
        "level": LEVEL_PATH,
        "fps": FPS,
        "imports": [],
    }

    try:
        for csv_path in _controlled_csvs():
            result = run_import(str(csv_path), fps=FPS)
            item: dict[str, object] = {
                "case": csv_path.stem,
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
                if item["distortion_track_status"] != "PASS":
                    item["success"] = False
                    report["status"] = "FAIL"
            else:
                report["status"] = "FAIL"
            report["imports"].append(item)
    finally:
        prt_config.ASSET_BASE_PATH = old_asset_root
        _save_current_level()

    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


if __name__ == "__main__":
    run()
