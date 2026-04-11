"""VP Post-Render Tool — Init and launch.

Usage in UE Python console:
    import init_post_render_tool
"""
import unreal


def check_prerequisites() -> bool:
    """Verify all required plugins are loaded."""
    from post_render_tool.ui_interface import get_prerequisite_status

    statuses = get_prerequisite_status()
    all_ok = True
    for name, ok, hint in statuses:
        if ok:
            unreal.log(f"  OK: {name}")
        else:
            unreal.log_error(f"  MISSING: {name}")
            if hint:
                unreal.log_error(f"  -> {hint}")
            all_ok = False
    return all_ok


def launch_tool():
    """Check prerequisites, create widget if needed, and open the UI."""
    unreal.log("=" * 50)
    unreal.log("VP Post-Render Tool — Initializing...")
    unreal.log("=" * 50)

    all_ok = check_prerequisites()

    if all_ok:
        unreal.log("All prerequisites met.")
    else:
        unreal.log_warning(
            "Some prerequisites are missing. "
            "Check the Prerequisites section in the UI for details."
        )

    unreal.log("-" * 50)

    # The widget itself requires EditorAssetLibrary (asset creation) and
    # EditorUtilitySubsystem (tab registration).  If either is missing the
    # widget cannot be constructed — fall back to console-only diagnostics.
    widget_deps_ok = (
        hasattr(unreal, "EditorAssetLibrary")
        and hasattr(unreal, "EditorUtilitySubsystem")
    )

    if widget_deps_ok:
        from post_render_tool.widget_builder import open_widget
        unreal.log("Opening VP Post-Render Tool UI...")
        open_widget()
    else:
        unreal.log_error(
            "Cannot open UI: EditorAssetLibrary or EditorUtilitySubsystem "
            "is not available.  Enable the required plugins (see above) "
            "and restart the editor."
        )

    unreal.log("=" * 50)
    unreal.log("VP Post-Render Tool ready.")
    unreal.log("=" * 50)


# Auto-launch on import
launch_tool()
