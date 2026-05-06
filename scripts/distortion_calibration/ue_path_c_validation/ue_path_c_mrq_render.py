"""Build and dispatch Path C MRQ validation renders in an open UE Editor.

This script is intended for the UE remote_execution bridge, not commandlet
startup. It creates only PathCValidation_* assets under /Game/PathCValidation
and queues four single-frame MRQ jobs:

  identity, k1, k2, k3

Outputs are written to C:/temp/ue-remote/path_c_validation_render/<case>/.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import unreal


ASSET_DIR = "/Game/PathCValidation"
SOURCE_PROBE = "C:/temp/ue-remote/uv_probe_3840x2160.exr"
TEXTURE_ASSET = f"{ASSET_DIR}/PathCValidation_UVProbe_3840x2160"
PLATE_MATERIAL = f"{ASSET_DIR}/PathCValidation_UVProbe_Mat"
DISTORTION_MATERIAL = "/PostRenderTool/Materials/M_PRT_OfficialSensorInverse"
OUT_ROOT = "C:/temp/ue-remote/path_c_validation_render"
REPORT_JSON = "C:/temp/ue-remote/path_c_mrq_render.json"
RUN_SUFFIX = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

CASES = {
    "identity": {"k1": 0.5, "k2": 0.0, "k3": 0.0, "distortion_weight": 0.0},
    "k1": {"k1": 0.5, "k2": 0.0, "k3": 0.0, "distortion_weight": 1.0},
    "k2": {"k1": 0.0, "k2": 0.5, "k3": 0.0, "distortion_weight": 1.0},
    "k3": {"k1": 0.0, "k2": 0.0, "k3": 0.5, "distortion_weight": 1.0},
}


def _write_report(payload):
    Path(REPORT_JSON).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


def _asset_name(path):
    return path.rsplit("/", 1)[-1]


def _ensure_dir():
    if not unreal.EditorAssetLibrary.does_directory_exist(ASSET_DIR):
        unreal.EditorAssetLibrary.make_directory(ASSET_DIR)


def _import_probe_texture():
    if not Path(SOURCE_PROBE).exists():
        raise RuntimeError(f"missing source probe on lanPC: {SOURCE_PROBE}")

    task = unreal.AssetImportTask()
    task.set_editor_property("filename", SOURCE_PROBE)
    task.set_editor_property("destination_path", ASSET_DIR)
    task.set_editor_property("destination_name", _asset_name(TEXTURE_ASSET))
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", True)

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    texture = unreal.EditorAssetLibrary.load_asset(TEXTURE_ASSET)
    if texture is None:
        raise RuntimeError(f"texture import failed: {TEXTURE_ASSET}")

    for prop, value in (
        ("srgb", False),
        ("filter", unreal.TextureFilter.TF_BILINEAR),
    ):
        try:
            texture.set_editor_property(prop, value)
        except Exception:
            pass
    unreal.EditorAssetLibrary.save_loaded_asset(texture)
    return texture


def _create_plate_material(texture):
    if unreal.EditorAssetLibrary.does_asset_exist(PLATE_MATERIAL):
        unreal.EditorAssetLibrary.delete_asset(PLATE_MATERIAL)

    material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        _asset_name(PLATE_MATERIAL),
        ASSET_DIR,
        unreal.Material,
        unreal.MaterialFactoryNew(),
    )
    if material is None:
        raise RuntimeError(f"material create failed: {PLATE_MATERIAL}")

    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_SURFACE)
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    material.set_editor_property("two_sided", True)

    mel = unreal.MaterialEditingLibrary
    sample = mel.create_material_expression(material, unreal.MaterialExpressionTextureSample, -400, 0)
    sample.set_editor_property("texture", texture)
    mel.connect_material_property(sample, "RGB", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    mel.recompile_material(material)
    unreal.EditorAssetLibrary.save_loaded_asset(material)
    return material


def _add_component_via_subobject_subsystem(actor, component_class):
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    if subsystem is None:
        raise RuntimeError("SubobjectDataSubsystem unavailable")
    handles = subsystem.k2_gather_subobject_data_for_instance(actor)
    if not handles:
        raise RuntimeError("SubobjectDataSubsystem returned no actor handles")

    params = unreal.AddNewSubobjectParams()
    params.parent_handle = handles[0]
    params.new_class = component_class
    before = set(actor.get_components_by_class(component_class))
    _new_handle, fail_reason = subsystem.add_new_subobject(params)
    after = actor.get_components_by_class(component_class)
    created = [comp for comp in after if comp not in before]
    if not created:
        raise RuntimeError(f"component add failed: {fail_reason}")
    return created[0]


def _save_current_level():
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


def _new_level(level_path):
    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        if not unreal.EditorAssetLibrary.delete_asset(level_path):
            raise RuntimeError(f"could not delete existing level: {level_path}")

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
    raise RuntimeError(f"could not create level: {level_path}")


def _set_camera_orthographic(camera_actor):
    cine = camera_actor.get_cine_camera_component()
    for prop, value in (
        ("projection_mode", unreal.CameraProjectionMode.ORTHOGRAPHIC),
        ("ortho_width", 1600.0),
        ("aspect_ratio", 16.0 / 9.0),
        ("constrain_aspect_ratio", True),
    ):
        try:
            cine.set_editor_property(prop, value)
        except Exception:
            pass
    return cine


def _spawn_case_level(case_name, params, plate_material, distortion_material):
    level_path = f"{ASSET_DIR}/PathCValidation_{case_name}_{RUN_SUFFIX}_Level"
    _new_level(level_path)

    plane_mesh = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Plane")
    if plane_mesh is None:
        raise RuntimeError("missing /Engine/BasicShapes/Plane")

    plane = unreal.EditorLevelLibrary.spawn_actor_from_object(
        plane_mesh,
        unreal.Vector(0.0, 0.0, 0.0),
        unreal.Rotator(0.0, 0.0, 0.0),
    )
    plane.set_actor_label(f"PathCValidation_{case_name}_Plate")
    plane.set_actor_scale3d(unreal.Vector(16.0, 9.0, 1.0))
    plane.set_actor_rotation(unreal.Rotator(90.0, 0.0, 0.0), False)
    static_comp = plane.get_component_by_class(unreal.StaticMeshComponent)
    static_comp.set_material(0, plate_material)

    camera = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CineCameraActor,
        unreal.Vector(0.0, -1000.0, 0.0),
        unreal.Rotator(0.0, 0.0, 0.0),
    )
    camera.set_actor_label(f"PathCValidation_{case_name}_Camera")
    camera.set_actor_rotation(
        unreal.MathLibrary.find_look_at_rotation(
            camera.get_actor_location(),
            unreal.Vector(0.0, 0.0, 0.0),
        ),
        False,
    )
    _set_camera_orthographic(camera)

    controller_cls = unreal.PostRenderDistortionControllerComponent.static_class()
    controller = _add_component_via_subobject_subsystem(camera, controller_cls)
    controller.set_editor_property("base_material", distortion_material)
    controller.set_editor_property("k1", float(params["k1"]))
    controller.set_editor_property("k2", float(params["k2"]))
    controller.set_editor_property("k3", float(params["k3"]))
    controller.set_editor_property("center_u", 0.5)
    controller.set_editor_property("center_v", 0.5)
    controller.set_editor_property("aspect", 16.0 / 9.0)
    controller.set_editor_property("distortion_weight", float(params["distortion_weight"]))

    _save_current_level()
    return level_path, camera


def _create_sequence(case_name, camera_actor):
    seq_path = f"{ASSET_DIR}/PathCValidation_{case_name}_{RUN_SUFFIX}_Seq"
    if unreal.EditorAssetLibrary.does_asset_exist(seq_path):
        unreal.EditorAssetLibrary.delete_asset(seq_path)

    seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        _asset_name(seq_path),
        ASSET_DIR,
        unreal.LevelSequence,
        unreal.LevelSequenceFactoryNew(),
    )
    if seq is None:
        raise RuntimeError(f"sequence create failed: {seq_path}")

    seq.set_display_rate(unreal.FrameRate(24, 1))
    seq.set_playback_start(0)
    seq.set_playback_end(1)
    camera_binding = seq.add_possessable(camera_actor)
    cut_track = seq.add_track(unreal.MovieSceneCameraCutTrack)
    cut_section = cut_track.add_section()
    cut_section.set_range(0, 1)
    cut_section.set_camera_binding_id(seq.get_binding_id(camera_binding))
    unreal.EditorAssetLibrary.save_loaded_asset(seq)
    return seq_path, seq


def _configure_job(queue, case_name, level_path, seq_path, seq):
    job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
    job.sequence = unreal.SoftObjectPath(seq_path)
    job.map = unreal.SoftObjectPath(level_path)
    job.job_name = f"PathCValidation_{case_name}"

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

    output = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    out_dir = f"{OUT_ROOT}/{case_name}"
    output.output_directory = unreal.DirectoryPath(out_dir)
    output.file_name_format = f"path_c_{case_name}.{{frame_number}}"
    output.output_resolution = unreal.IntPoint(3840, 2160)
    output.use_custom_playback_range = True
    output.custom_start_frame = 0
    output.custom_end_frame = 1
    return out_dir


def run():
    report = {"status": "FAIL", "jobs": [], "output_root": OUT_ROOT}
    try:
        _ensure_dir()
        out_root = Path(OUT_ROOT)
        if out_root.exists():
            shutil.rmtree(out_root)
        out_root.mkdir(parents=True, exist_ok=True)

        texture = _import_probe_texture()
        plate_material = _create_plate_material(texture)
        distortion_material = unreal.EditorAssetLibrary.load_asset(DISTORTION_MATERIAL)
        if distortion_material is None:
            raise RuntimeError(f"missing distortion material: {DISTORTION_MATERIAL}")

        queue_subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        queue = queue_subsystem.get_queue()
        for job in list(queue.get_jobs()):
            queue.delete_job(job)

        for case_name, params in CASES.items():
            level_path, camera = _spawn_case_level(case_name, params, plate_material, distortion_material)
            seq_path, seq = _create_sequence(case_name, camera)
            out_dir = _configure_job(queue, case_name, level_path, seq_path, seq)
            camera_forward = camera.get_actor_forward_vector()
            report["jobs"].append({
                "case": case_name,
                "level": level_path,
                "sequence": seq_path,
                "output_dir": out_dir,
                "params": params,
                "camera_forward": [camera_forward.x, camera_forward.y, camera_forward.z],
            })

        executor = queue_subsystem.render_queue_with_executor(unreal.MoviePipelinePIEExecutor)
        report["status"] = "DISPATCHED" if executor is not None else "FAIL"
    except Exception as exc:
        report["error"] = str(exc)

    _write_report(report)
    if report["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    run()
