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


def _get_widget_tree(widget_bp):
    """Discover the Blueprint's WidgetTree, trying multiple access methods.

    UE 5.7 may not expose ``widget_tree`` via ``get_editor_property`` on the
    ``EditorUtilityWidgetBlueprint`` wrapper.  We try progressively broader
    techniques until one succeeds.

    Returns the WidgetTree object, or *None*.
    """
    # 1. get_editor_property — standard path (works in UE ≤5.6).
    try:
        wt = widget_bp.get_editor_property("widget_tree")
        if wt is not None:
            return wt
    except Exception:
        pass

    # 2. Direct attribute access (may bypass property wrapper).
    for attr in ("widget_tree", "WidgetTree"):
        try:
            wt = getattr(widget_bp, attr, None)
            if wt is not None:
                return wt
        except Exception:
            pass

    # 3. Cast to WidgetBlueprint parent — Python reflection for the child
    #    class may not include parent-class UPROPERTY entries.
    if hasattr(unreal, "WidgetBlueprint"):
        try:
            wb = unreal.WidgetBlueprint.cast(widget_bp)
            if wb is not None:
                wt = wb.get_editor_property("widget_tree")
                if wt is not None:
                    unreal.log("[widget_builder] WidgetTree found via WidgetBlueprint cast.")
                    return wt
        except Exception:
            pass

    # 4. Heuristic search — look for any attribute whose type has
    #    ``construct_widget`` or ``root_widget`` (i.e. "looks like" a WidgetTree).
    try:
        for name in dir(widget_bp):
            if "tree" in name.lower():
                try:
                    obj = getattr(widget_bp, name)
                    if obj is not None and (
                        hasattr(obj, "construct_widget")
                        or hasattr(obj, "root_widget")
                        or "WidgetTree" in type(obj).__name__
                    ):
                        unreal.log(f"[widget_builder] WidgetTree found via attr '{name}'.")
                        return obj
                except Exception:
                    pass
    except Exception:
        pass

    # Nothing worked — log diagnostics.
    try:
        chain = []
        cls = widget_bp.get_class()
        while cls is not None:
            chain.append(cls.get_name())
            cls = cls.get_super_class()
        unreal.log_warning(
            f"[widget_builder] Class hierarchy: {' -> '.join(chain)}"
        )
    except Exception:
        pass
    try:
        relevant = sorted({
            a for a in dir(widget_bp)
            if any(k in a.lower() for k in ("widget", "tree", "root"))
            and not a.startswith("__")
        })
        unreal.log_warning(
            f"[widget_builder] Relevant attrs: {relevant[:30]}"
        )
    except Exception:
        pass

    return None


def _ensure_root_widget(widget_bp) -> bool:
    """Ensure the Blueprint's WidgetTree has a VerticalBox root.

    Returns True if the Blueprint was modified and needs saving.
    """
    wt = _get_widget_tree(widget_bp)
    if wt is None:
        unreal.log_warning("[widget_builder] WidgetTree not accessible — cannot set root.")
        return False

    # Already a VerticalBox — nothing to do.
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

    # Create a VerticalBox owned by the WidgetTree.
    root = None
    if hasattr(wt, "construct_widget"):
        try:
            root = wt.construct_widget(unreal.VerticalBox, "RootVBox")
        except Exception as exc:
            unreal.log_warning(f"[widget_builder] construct_widget failed: {exc}")

    if root is None:
        try:
            root = unreal.VerticalBox(outer=wt)
        except Exception as exc:
            unreal.log_warning(f"[widget_builder] VerticalBox(outer=wt) failed: {exc}")

    if root is None:
        try:
            root = unreal.VerticalBox()
        except Exception as exc:
            unreal.log_warning(f"[widget_builder] VerticalBox() failed: {exc}")
            return False

    # Set as root widget.
    for setter, label in (
        (lambda r: wt.set_editor_property("root_widget", r), "set_editor_property"),
        (lambda r: setattr(wt, "root_widget", r), "direct attribute"),
    ):
        try:
            setter(root)
            unreal.log(f"[widget_builder] Root VerticalBox set via {label}.")
            return True
        except Exception as exc:
            unreal.log_warning(f"[widget_builder] {label} root_widget failed: {exc}")

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
            # Verify the asset is usable (has a WidgetTree with a root).
            wt = _get_widget_tree(loaded)
            if wt is not None:
                try:
                    root = wt.get_editor_property("root_widget")
                    if root is not None:
                        return loaded
                except Exception:
                    pass
            # Asset exists but is damaged — delete and recreate.
            unreal.log_warning(
                "[widget_builder] Existing asset has no usable root widget, "
                "deleting and recreating..."
            )
            try:
                unreal.EditorAssetLibrary.delete_asset(WIDGET_ASSET_PATH)
            except Exception:
                pass
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

    # Compile Blueprint first — this initialises internal WidgetTree
    # structures and may create a default root widget (CanvasPanel).
    try:
        unreal.KismetEditorUtilities.compile_blueprint(widget_bp)
        unreal.log("[widget_builder] Blueprint compiled.")
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] compile_blueprint: {exc}")

    # Try to set root to VerticalBox (may fail if WidgetTree not accessible).
    _ensure_root_widget(widget_bp)

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
