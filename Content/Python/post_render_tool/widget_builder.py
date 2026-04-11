"""Widget Builder — VP Post-Render Tool.

Creates and opens the EditorUtilityWidget Blueprint asset.
Only usable inside UE Editor Python environment.

NOTE: The Blueprint is kept IN-MEMORY ONLY (never saved to disk).
PythonGeneratedClass cannot be serialized by UE's SavePackage2 —
calling save_asset() on a Blueprint whose parent is a @uclass Python
class triggers an assertion failure (SuperIndex mapping).
The widget is recreated each session via ``import init_post_render_tool``.
"""

from __future__ import annotations

import os

import unreal

# Asset location in Content Browser
WIDGET_PACKAGE_PATH = "/Game/PostRenderTool"
WIDGET_ASSET_NAME = "EUW_PostRenderTool"
WIDGET_FULL_PATH = f"{WIDGET_PACKAGE_PATH}/{WIDGET_ASSET_NAME}"
WIDGET_ASSET_PATH = f"{WIDGET_FULL_PATH}.{WIDGET_ASSET_NAME}"

# Disk-relative path segment derived from WIDGET_PACKAGE_PATH
_CONTENT_REL_DIR = WIDGET_PACKAGE_PATH.removeprefix("/Game/")


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


def _try_prevent_save(obj) -> None:
    """Best-effort: mark the object so UE won't try to save it on exit."""
    try:
        obj.set_flags(0x00000040)  # RF_Transient
    except Exception:
        pass
    try:
        obj.get_outermost().clear_dirty_flag()
    except Exception:
        pass


def create_widget() -> object:
    """Create the EditorUtilityWidgetBlueprint asset (in-memory only).

    If the asset already exists in memory (created earlier this session),
    returns the existing one.  The Blueprint is NEVER saved to disk because
    PythonGeneratedClass parents cannot be serialized by SavePackage2.

    Returns
    -------
    unreal.EditorUtilityWidgetBlueprint
        The created or existing widget Blueprint asset.
    """
    # Import widget class FIRST — triggers @uclass registration so that
    # any existing asset whose parent is this class can be resolved.
    from .widget import OPostRenderToolWidget

    # Reuse in-memory widget created earlier this session
    try:
        loaded = unreal.EditorAssetLibrary.load_asset(WIDGET_ASSET_PATH)
        if loaded is not None:
            unreal.log(f"[widget_builder] Reusing existing widget: {WIDGET_ASSET_PATH}")
            return loaded
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] load_asset failed, will recreate: {exc}")

    # Remove any corrupt/stale files from a previous crash
    _cleanup_disk_asset()

    unreal.EditorAssetLibrary.make_directory(WIDGET_PACKAGE_PATH)

    # Create the EditorUtilityWidgetBlueprint using factory
    factory = unreal.EditorUtilityWidgetBlueprintFactory()
    try:
        factory.set_editor_property("parent_class", OPostRenderToolWidget)
    except Exception as exc:
        unreal.log_warning(
            f"[widget_builder] Could not set parent_class via factory: {exc}"
        )

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    widget_bp = asset_tools.create_asset(
        WIDGET_ASSET_NAME,
        WIDGET_PACKAGE_PATH,
        None,  # asset_class — None lets the factory decide
        factory,
    )

    if widget_bp is None:
        raise RuntimeError(
            f"Failed to create EditorUtilityWidgetBlueprint at {WIDGET_FULL_PATH}"
        )

    # ALWAYS verify actual parent — set_editor_property may succeed without
    # exception yet the factory may still ignore the value.  Reparent if needed
    # so OPostRenderToolWidget.construct() (and _build_ui) will be called.
    try:
        current_parent = widget_bp.get_editor_property("parent_class")
        if current_parent != OPostRenderToolWidget:
            unreal.BlueprintEditorLibrary.reparent_blueprint(
                widget_bp, OPostRenderToolWidget
            )
            unreal.log("[widget_builder] Reparented to OPostRenderToolWidget.")
    except Exception as exc:
        unreal.log_error(
            f"[widget_builder] Reparent failed: {exc}. "
            "Widget will have no UI — try rebuild_widget()."
        )

    # ── DO NOT SAVE ──
    # PythonGeneratedClass can't be serialized → SavePackage2 assertion crash.
    _try_prevent_save(widget_bp)

    unreal.log(f"[widget_builder] Widget created (in-memory): {WIDGET_FULL_PATH}")

    return widget_bp


def open_widget() -> None:
    """Open the PostRenderTool widget as an editor tab.

    Creates the widget asset first if it doesn't exist.
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


def delete_widget() -> bool:
    """Delete the existing widget Blueprint asset (for rebuilding).

    Returns
    -------
    bool
        True if deleted, False if not found.
    """
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
