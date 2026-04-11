"""Widget Builder — VP Post-Render Tool.

Creates and opens the EditorUtilityWidget Blueprint asset, then injects
the Python-built UI into the spawned widget instance.

The Blueprint uses the native EditorUtilityWidget as parent (safe to save).
UI is constructed at runtime by ``PostRenderToolUI`` from ``widget.py``.
"""

from __future__ import annotations

import os

import unreal

# Asset location in Content Browser
WIDGET_PACKAGE_PATH = "/Game/PostRenderTool"
WIDGET_ASSET_NAME = "EUW_PostRenderTool"
WIDGET_FULL_PATH = f"{WIDGET_PACKAGE_PATH}/{WIDGET_ASSET_NAME}"
WIDGET_ASSET_PATH = f"{WIDGET_FULL_PATH}.{WIDGET_ASSET_NAME}"

_CONTENT_REL_DIR = WIDGET_PACKAGE_PATH.removeprefix("/Game/")

# Module-level reference — prevents GC of the UI builder and its callbacks.
_active_ui = None


def _cleanup_disk_asset() -> None:
    """Remove any .uasset/.uexp left on disk from a previous crashed save."""
    try:
        content_dir = unreal.Paths.project_content_dir()
        base = os.path.join(content_dir, _CONTENT_REL_DIR, WIDGET_ASSET_NAME)
        for ext in (".uasset", ".uexp"):
            try:
                os.remove(base + ext)
                unreal.log(f"[widget_builder] Removed stale file: {base}{ext}")
            except FileNotFoundError:
                pass
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] Disk cleanup failed: {exc}")


def create_widget() -> object:
    """Create or load the EditorUtilityWidgetBlueprint asset.

    Uses the native ``EditorUtilityWidget`` as parent (no PythonGeneratedClass),
    so the Blueprint is safe to save to disk and persist across sessions.

    Returns
    -------
    unreal.EditorUtilityWidgetBlueprint
    """
    try:
        loaded = unreal.EditorAssetLibrary.load_asset(WIDGET_ASSET_PATH)
        if loaded is not None:
            unreal.log(f"[widget_builder] Reusing existing widget: {WIDGET_ASSET_PATH}")
            return loaded
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] load_asset failed, will recreate: {exc}")

    _cleanup_disk_asset()
    unreal.EditorAssetLibrary.make_directory(WIDGET_PACKAGE_PATH)

    factory = unreal.EditorUtilityWidgetBlueprintFactory()
    # Default parent = EditorUtilityWidget (native) — safe to serialize.

    widget_bp = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        WIDGET_ASSET_NAME,
        WIDGET_PACKAGE_PATH,
        None,  # asset_class — None lets the factory decide
        factory,
    )

    if widget_bp is None:
        raise RuntimeError(
            f"Failed to create EditorUtilityWidgetBlueprint at {WIDGET_FULL_PATH}"
        )

    unreal.EditorAssetLibrary.save_asset(
        widget_bp.get_path_name(), only_if_is_dirty=False
    )
    unreal.log(f"[widget_builder] Widget Blueprint created: {WIDGET_FULL_PATH}")

    return widget_bp


def _inject_ui(widget_bp) -> None:
    """Find the spawned widget instance and build UI into it."""
    global _active_ui

    subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)

    # Try to get widget instance immediately (synchronous after spawn)
    widget = None
    try:
        widget = subsystem.find_utility_widget_from_blueprint(widget_bp)
    except (AttributeError, Exception) as exc:
        unreal.log_warning(
            f"[widget_builder] find_utility_widget_from_blueprint: {exc}"
        )

    if widget is not None:
        from .widget import PostRenderToolUI
        _active_ui = PostRenderToolUI(widget)
        unreal.log("[widget_builder] UI injected into widget.")
        return

    # Fallback: poll on next ticks until the widget is available.
    attempts = [0]
    handle_holder = [None]

    def _try_inject(delta_time):
        global _active_ui
        attempts[0] += 1
        try:
            w = subsystem.find_utility_widget_from_blueprint(widget_bp)
            if w is not None:
                from .widget import PostRenderToolUI
                _active_ui = PostRenderToolUI(w)
                unreal.log("[widget_builder] UI injected (deferred).")
                unreal.unregister_slate_post_tick_callback(handle_holder[0])
                return
        except Exception:
            pass
        if attempts[0] >= 30:
            unreal.log_error(
                "[widget_builder] Could not find widget instance after spawn. "
                "Try: from post_render_tool.widget_builder import rebuild_widget; "
                "rebuild_widget()"
            )
            unreal.unregister_slate_post_tick_callback(handle_holder[0])

    handle_holder[0] = unreal.register_slate_post_tick_callback(_try_inject)


def open_widget() -> None:
    """Open the PostRenderTool widget as an editor tab.

    Creates the widget asset first if it doesn't exist, then injects
    the Python-built UI into the spawned widget instance.
    """
    widget_bp = create_widget()

    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        subsystem.spawn_and_register_tab(widget_bp)
        unreal.log("[widget_builder] Widget tab opened.")
    except Exception as exc:
        unreal.log_error(f"[widget_builder] Failed to open widget tab: {exc}")
        try:
            unreal.EditorUtilityLibrary.run_editor_utility_widget(widget_bp)
            unreal.log("[widget_builder] Widget opened via EditorUtilityLibrary fallback.")
        except Exception as exc2:
            unreal.log_error(
                f"[widget_builder] Fallback also failed: {exc2}. "
                "Try: from post_render_tool.widget_builder import rebuild_widget; "
                "rebuild_widget()"
            )
            return

    _inject_ui(widget_bp)


def delete_widget() -> bool:
    """Delete the existing widget Blueprint asset (for rebuilding).

    Returns
    -------
    bool
        True if deleted, False if not found.
    """
    global _active_ui
    _active_ui = None
    deleted = False
    try:
        unreal.EditorAssetLibrary.delete_asset(WIDGET_ASSET_PATH)
        unreal.log(f"[widget_builder] Widget deleted: {WIDGET_ASSET_PATH}")
        deleted = True
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] delete_asset failed: {exc}")
    _cleanup_disk_asset()
    return deleted


def rebuild_widget() -> None:
    """Delete, recreate, and open the widget Blueprint asset."""
    delete_widget()
    open_widget()
