"""VP Post-Render Tool prerequisite check.

Usage in UE Python console: import init_post_render_tool
"""
import unreal


def _class_exists(class_name: str) -> bool:
    """Check if a UE class is available (i.e., its plugin is loaded)."""
    return hasattr(unreal, class_name)


def check_prerequisites() -> bool:
    all_ok = True

    # Python Editor Script Plugin — if we're running this, it's loaded
    unreal.log("  OK: Python Editor Script Plugin (running Python now)")

    # Editor Scripting Utilities — check for EditorAssetLibrary
    if _class_exists("EditorAssetLibrary"):
        unreal.log("  OK: Editor Scripting Utilities")
    else:
        unreal.log_error("  MISSING: Editor Scripting Utilities")
        unreal.log_error("  -> Edit > Plugins > search 'Editor Scripting' > Enable > Restart")
        all_ok = False

    # Camera Calibration — check for LensFile class
    if _class_exists("LensFile"):
        unreal.log("  OK: Camera Calibration (LensFile available)")
    else:
        unreal.log_error("  MISSING: Camera Calibration")
        unreal.log_error("  -> Edit > Plugins > search 'Camera Calibration' > Enable > Restart")
        all_ok = False

    # CineCameraActor — should always exist but verify
    if _class_exists("CineCameraActor"):
        unreal.log("  OK: CineCameraActor")
    else:
        unreal.log_error("  MISSING: CineCameraActor (unexpected)")
        all_ok = False

    # LevelSequence
    if _class_exists("LevelSequence"):
        unreal.log("  OK: LevelSequence")
    else:
        unreal.log_error("  MISSING: LevelSequence — enable 'Level Sequence Editor' plugin")
        all_ok = False

    if all_ok:
        unreal.log("All prerequisites met. VP Post-Render Tool ready.")
    else:
        unreal.log_error("Please enable missing plugins and restart the editor.")
    return all_ok


check_prerequisites()
