"""UE-side smoke inspection for Path C custom post-process distortion.

Run inside Unreal Editor or UnrealEditor-Cmd:

    UnrealEditor-Cmd.exe <project>.uproject -nullrhi -unattended -nop4 \
        -ExecutePythonScript=C:/temp/ue-remote/ue_path_c_smoke.py

By default the script uses a transient controller object and does not spawn
level actors. UE 5.7 -nullrhi can terminate unexpectedly after editor actor
spawn in this project, so actor binding is an optional mode for non-null editor
sessions. In both modes the script binds M_PRT_OfficialSensorInverse, writes
known parameters, and emits JSON evidence. It does not save maps, packages, or
production LevelSequence assets.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import unreal


OUTPUT_JSON = "C:/temp/ue-remote/path_c_smoke.json"
MATERIAL_PATH = "/PostRenderTool/Materials/M_PRT_OfficialSensorInverse"
ACTOR_LABEL = "PathCValidation_Camera"
EXPECTED = {
    "k1": 0.5,
    "k2": 0.0,
    "k3": 0.0,
    "center_u": 0.5,
    "center_v": 0.5,
    "aspect": 16.0 / 9.0,
    "distortion_weight": 1.0,
}


def _argv_value(name: str, default: str) -> str:
    prefix = name + "="
    for arg in sys.argv:
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return default


def _argv_bool(name: str, default: bool = False) -> bool:
    value = _argv_value(name, "1" if default else "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


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
        raise RuntimeError(f"failed to add component: {fail_reason}")
    return created[0]


def _get_or_spawn_camera():
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if actor.get_actor_label() == ACTOR_LABEL:
            return actor, True

    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CineCameraActor,
        unreal.Vector(0.0, 0.0, 100.0),
        unreal.Rotator(0.0, 0.0, 0.0),
    )
    actor.set_actor_label(ACTOR_LABEL)
    return actor, False


def _ensure_controller(actor):
    py_cls = getattr(unreal, "PostRenderDistortionControllerComponent", None)
    if py_cls is None:
        raise RuntimeError("unreal.PostRenderDistortionControllerComponent is not visible")
    controller_class = py_cls.static_class()

    existing = actor.get_components_by_class(controller_class)
    if existing:
        return existing[0], True
    return _add_component_via_subobject_subsystem(actor, controller_class), False


def _new_transient_controller():
    py_cls = getattr(unreal, "PostRenderDistortionControllerComponent", None)
    if py_cls is None:
        raise RuntimeError("unreal.PostRenderDistortionControllerComponent is not visible")

    attempts = []
    outers = [None]
    get_transient_package = getattr(unreal, "get_transient_package", None)
    if get_transient_package is not None:
        try:
            outers.insert(0, get_transient_package())
        except Exception as exc:
            attempts.append(f"get_transient_package: {exc}")
    for cls in (py_cls, py_cls.static_class()):
        for outer in outers:
            try:
                controller = unreal.new_object(
                    cls,
                    outer=outer,
                    name="PathCValidation_TransientController",
                )
                if controller is not None:
                    return controller
            except Exception as exc:
                attempts.append(f"{cls} outer={outer}: {exc}")
    raise RuntimeError("could not create transient controller: " + " | ".join(attempts))


def _set_params(controller, material):
    controller.set_editor_property("base_material", material)
    for name, value in EXPECTED.items():
        controller.set_editor_property(name, value)


def _get_params(controller):
    values = {}
    for name in EXPECTED:
        values[name] = float(controller.get_editor_property(name))
    return values


def _try_get_blendable_count(actor):
    try:
        camera = actor.get_cine_camera_component()
        settings = camera.get_editor_property("post_process_settings")
        weighted = settings.get_editor_property("weighted_blendables")
        array = weighted.get_editor_property("array")
        return {"status": "READ", "count": len(array)}
    except Exception as exc:  # UE minor versions expose this differently.
        return {"status": "UNREADABLE_IN_PYTHON", "error": str(exc)}


def _material_path(material):
    return material.get_path_name() if material is not None else None


def _matches_expected(params):
    for name, expected in EXPECTED.items():
        if abs(params[name] - float(expected)) > 1e-6:
            return False
    return True


def run():
    output_json = Path(_argv_value("--output-json", OUTPUT_JSON))
    spawn_actor = _argv_bool("--spawn-actor", False)
    result = {
        "status": "FAIL",
        "script": "ue_path_c_smoke.py",
        "mode": "actor_spawn" if spawn_actor else "transient_controller",
        "actor_label": ACTOR_LABEL,
        "material_asset_path": MATERIAL_PATH,
        "generated_asset_prefix": "PathCValidation_",
        "saves_assets": False,
        "notes": [],
    }

    try:
        material = unreal.EditorAssetLibrary.load_asset(MATERIAL_PATH)
        if material is None:
            raise RuntimeError(f"material not found: {MATERIAL_PATH}")

        actor = None
        reused_actor = None
        reused_controller = None
        if spawn_actor:
            actor, reused_actor = _get_or_spawn_camera()
            controller, reused_controller = _ensure_controller(actor)
        else:
            controller = _new_transient_controller()
        _set_params(controller, material)

        if spawn_actor:
            try:
                controller.register_component()
            except Exception as exc:
                result["notes"].append(f"register_component skipped: {exc}")

            try:
                controller.activate(True)
            except Exception as exc:
                result["notes"].append(f"activate skipped: {exc}")

        params = _get_params(controller)
        base_material = controller.get_editor_property("base_material")
        if spawn_actor:
            blendables = _try_get_blendable_count(actor)
        else:
            blendables = {
                "status": "DEFERRED_NO_ACTOR_SPAWN",
                "count": None,
                "reason": "Use --spawn-actor=1 in a non-null editor session to inspect WeightedBlendables.",
            }

        result.update({
            "controller_exists": controller is not None,
            "controller_class": controller.get_class().get_name(),
            "actor_reused": reused_actor,
            "controller_reused": reused_controller,
            "base_material_path": _material_path(base_material),
            "parameter_values": params,
            "parameter_values_match_expected": _matches_expected(params),
            "blendables": blendables,
        })

        if blendables.get("count", 0) == 0:
            result["notes"].append(
                "WeightedBlendables may remain 0 in -nullrhi commandlet because BeginPlay/MRQ did not run."
            )

        ok = (
            result["controller_exists"]
            and result["base_material_path"] == material.get_path_name()
            and result["parameter_values_match_expected"]
        )
        result["status"] = "PASS" if ok else "FAIL"
    except Exception as exc:
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc()

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    run()
