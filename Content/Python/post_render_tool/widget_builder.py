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


def _ensure_root_widget(widget_bp) -> bool:
    """Ensure the Blueprint's WidgetTree has a root VerticalBox.

    The factory may create a CanvasPanel or leave the tree empty.
    widget.py expects a VerticalBox root (via ``get_root_widget()``).

    Returns True if the Blueprint was modified and needs saving.
    """
    # Step 1: Get WidgetTree from Blueprint.
    try:
        wt = widget_bp.get_editor_property("widget_tree")
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] Cannot access widget_tree: {exc}")
        return False
    if wt is None:
        unreal.log_warning("[widget_builder] WidgetTree is None on Blueprint.")
        return False

    # Step 2: Check existing root — skip if already a VerticalBox.
    try:
        existing = wt.get_editor_property("root_widget")
        if existing is not None and isinstance(existing, unreal.VerticalBox):
            return False
        if existing is not None:
            unreal.log(
                f"[widget_builder] Current root is {type(existing).__name__}, "
                "replacing with VerticalBox."
            )
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] Cannot read root_widget: {exc}")

    # Step 3: Create a VerticalBox owned by the WidgetTree.
    root = None
    # Method A — construct_widget (canonical WidgetTree API).
    if hasattr(wt, "construct_widget"):
        try:
            root = wt.construct_widget(unreal.VerticalBox, "RootVBox")
        except Exception as exc:
            unreal.log_warning(f"[widget_builder] construct_widget failed: {exc}")
    else:
        unreal.log_warning("[widget_builder] WidgetTree has no construct_widget method.")

    # Method B — manual construction with outer=WidgetTree.
    if root is None:
        try:
            root = unreal.VerticalBox(outer=wt)
        except Exception as exc:
            unreal.log_warning(f"[widget_builder] VerticalBox(outer=wt) failed: {exc}")

    # Method C — plain construction (last resort).
    if root is None:
        try:
            root = unreal.VerticalBox()
        except Exception as exc:
            unreal.log_warning(f"[widget_builder] VerticalBox() failed: {exc}")
            return False

    # Step 4: Set as root widget.
    try:
        wt.set_editor_property("root_widget", root)
        unreal.log("[widget_builder] Root VerticalBox set in Blueprint WidgetTree.")
        return True
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] set_editor_property root_widget failed: {exc}")

    # Fallback: direct attribute assignment.
    try:
        wt.root_widget = root
        unreal.log("[widget_builder] Root VerticalBox set via direct attribute.")
        return True
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] direct root_widget assignment failed: {exc}")

    return False


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
            if _ensure_root_widget(loaded):
                unreal.EditorAssetLibrary.save_asset(
                    loaded.get_path_name(), only_if_is_dirty=False
                )
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

    _ensure_root_widget(widget_bp)

    # Verify root was actually set.
    try:
        _wt = widget_bp.get_editor_property("widget_tree")
        if _wt is not None:
            _root = _wt.get_editor_property("root_widget")
            if _root is None:
                unreal.log_warning(
                    "[widget_builder] WARNING: Blueprint still has no root widget "
                    "after _ensure_root_widget. UI injection will use fallback."
                )
    except Exception:
        pass

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
        try:
            from .widget import PostRenderToolUI
            _active_ui = PostRenderToolUI(widget)
            unreal.log("[widget_builder] UI injected into widget.")
            return
        except Exception as exc:
            unreal.log_warning(
                f"[widget_builder] Sync injection failed: {exc}  — deferring..."
            )

    # Fallback: poll on next ticks until the widget is available.
    attempts = [0]
    handle_holder = [None]

    last_error = [None]

    def _try_inject(delta_time):
        global _active_ui
        attempts[0] += 1
        try:
            w = subsystem.find_utility_widget_from_blueprint(widget_bp)
        except Exception:
            w = None

        if w is not None:
            try:
                from .widget import PostRenderToolUI
                _active_ui = PostRenderToolUI(w)
                unreal.log("[widget_builder] UI injected (deferred).")
                unreal.unregister_slate_post_tick_callback(handle_holder[0])
                return
            except Exception as exc:
                # May be transient (widget tree not ready yet) — retry.
                last_error[0] = exc

        if attempts[0] >= 30:
            msg = (
                "[widget_builder] UI injection failed after 30 attempts. "
                "Try: from post_render_tool.widget_builder import rebuild_widget; "
                "rebuild_widget()"
            )
            if last_error[0] is not None:
                msg = f"[widget_builder] UI injection failed: {last_error[0]}"
            unreal.log_error(msg)
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
