"""VP Post-Render Tool prerequisite check.

Usage in UE: py init_post_render_tool
"""
import unreal


def check_prerequisites() -> bool:
    required = {
        "PythonScriptPlugin": "Python Editor Script Plugin",
        "EditorScriptingUtilities": "Editor Scripting Utilities",
    }
    cam_cal_names = ["CameraCalibrationCore", "CameraCalibration"]
    all_ok = True

    for plugin_id, name in required.items():
        try:
            loaded = unreal.PluginBlueprintLibrary.is_plugin_loaded(plugin_id)
        except Exception:
            loaded = False
        if loaded:
            unreal.log(f"  OK: {name}")
        else:
            unreal.log_error(f"  MISSING: {name} ({plugin_id})")
            all_ok = False

    cam_ok = any(
        unreal.PluginBlueprintLibrary.is_plugin_loaded(n) for n in cam_cal_names
    )
    if cam_ok:
        unreal.log("  OK: Camera Calibration")
    else:
        unreal.log_error("  MISSING: Camera Calibration")
        unreal.log_error("  -> Edit > Plugins > search 'Camera Calibration' > Enable > Restart")
        all_ok = False

    if all_ok:
        unreal.log("All prerequisites met. VP Post-Render Tool ready.")
    else:
        unreal.log_error("Please enable missing plugins and restart the editor.")
    return all_ok


check_prerequisites()
