"""Widget Builder — VP Post-Render Tool.

Loads the plugin-shipped ``BP_PostRenderToolWidget`` Blueprint, spawns it
as an editor tab via ``EditorUtilitySubsystem.spawn_and_register_tab``,
and hands the live instance to ``widget.PostRenderToolUI``, which binds
Python callbacks to the widgets exposed by the BindWidget contract in
``UPostRenderToolWidget`` (C++).

The Blueprint is authored in the UMG Designer and shipped inside
``Content/Blueprints/``. Its widget tree must satisfy the BindWidget
contract declared in ``Source/PostRenderTool/Public/PostRenderToolWidget.h``;
missing required widgets fail the Blueprint compile. See
``TEMPLATE_SETUP_INSTRUCTIONS`` below for recovery steps if the asset is
missing or corrupt.
"""

from __future__ import annotations

import unreal

# Asset location inside the PostRenderTool plugin's Content folder.
# The plugin mounts Content/ at the virtual root `/PostRenderTool/`.
WIDGET_PACKAGE_PATH = "/PostRenderTool/Blueprints"
WIDGET_ASSET_NAME = "BP_PostRenderToolWidget"
WIDGET_FULL_PATH = f"{WIDGET_PACKAGE_PATH}/{WIDGET_ASSET_NAME}"
WIDGET_ASSET_PATH = f"{WIDGET_FULL_PATH}.{WIDGET_ASSET_NAME}"

TEMPLATE_SETUP_INSTRUCTIONS = f"""
Blueprint asset not found: {WIDGET_ASSET_PATH}

The BP_PostRenderToolWidget asset is shipped inside the PostRenderTool plugin.
If you are seeing this error:

  1. Confirm the plugin is installed at <UEProject>/Plugins/PostRenderTool/
  2. Confirm the plugin compiled successfully (Edit → Plugins → VP Post-Render Tool → green)
  3. Confirm Content/Blueprints/BP_PostRenderToolWidget.uasset exists on disk
  4. Confirm the plugin is enabled (Edit → Plugins → search "Post-Render")
  5. Restart UE Editor and try again

If the Blueprint was deleted, re-create it via:
  Content Browser → Plugins → VP Post-Render Tool Content → Blueprints
  → Right-click → Blueprint Class → PostRenderToolWidget → name it "BP_PostRenderToolWidget"

Then open the Designer and add widgets matching the BindWidget contract in
Source/PostRenderTool/Public/PostRenderToolWidget.h.
""".strip()

# Module-level reference — prevents GC of the UI builder and its callbacks.
_active_ui = None


def load_widget():
    """Load the plugin-shipped BP_PostRenderToolWidget Blueprint.

    Returns
    -------
    unreal.EditorUtilityWidgetBlueprint

    Raises
    ------
    RuntimeError
        If the template asset does not exist on disk.
    """
    loaded = None
    try:
        loaded = unreal.EditorAssetLibrary.load_asset(WIDGET_ASSET_PATH)
    except Exception as exc:
        raise RuntimeError(
            f"load_asset failed for {WIDGET_ASSET_PATH}: {exc}\n\n"
            + TEMPLATE_SETUP_INSTRUCTIONS
        )
    if loaded is None:
        raise RuntimeError(TEMPLATE_SETUP_INSTRUCTIONS)
    unreal.log(f"[widget_builder] Loaded template: {WIDGET_ASSET_PATH}")
    return loaded


def _inject_ui(widget_bp) -> None:
    """Find the spawned widget instance and build UI into it."""
    global _active_ui

    subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)

    widget = None
    try:
        widget = subsystem.find_utility_widget_from_blueprint(widget_bp)
    except Exception as exc:
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
                last_error[0] = exc

        if attempts[0] >= 30:
            detail = (
                f"(last error: {last_error[0]})"
                if last_error[0] is not None
                else "(widget never became available)"
            )
            unreal.log_error(
                f"[widget_builder] UI injection failed after 30 attempts {detail}. "
                "Try reopening the widget, or re-check the template setup."
            )
            unreal.unregister_slate_post_tick_callback(handle_holder[0])

    handle_holder[0] = unreal.register_slate_post_tick_callback(_try_inject)


def open_widget() -> None:
    """Load the template, spawn the editor tab, inject UI."""
    widget_bp = load_widget()

    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        subsystem.spawn_and_register_tab(widget_bp)
        unreal.log("[widget_builder] Widget tab opened.")
    except Exception as exc:
        unreal.log_error(f"[widget_builder] Failed to open widget tab: {exc}")
        try:
            unreal.EditorUtilityLibrary.run_editor_utility_widget(widget_bp)
            unreal.log("[widget_builder] Widget opened via fallback.")
        except Exception as exc2:
            unreal.log_error(f"[widget_builder] Fallback also failed: {exc2}.")
            return

    _inject_ui(widget_bp)


def delete_widget() -> bool:
    """Delete the plugin-shipped Blueprint asset from disk.

    .. warning::
       Normally you should never need to call this — the asset is part of
       the plugin and is reinstalled on every plugin sync.  If you do
       delete it (e.g. the asset is corrupt and must be recreated), the
       next ``open_widget()`` call will fail until the asset is recreated
       via the steps in ``TEMPLATE_SETUP_INSTRUCTIONS``.

    Returns
    -------
    bool
        True if an asset was deleted, False otherwise.
    """
    global _active_ui
    _active_ui = None
    try:
        deleted = unreal.EditorAssetLibrary.delete_asset(WIDGET_ASSET_PATH)
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] delete_asset failed: {exc}")
        return False
    if deleted:
        unreal.log_warning(
            f"[widget_builder] Template deleted: {WIDGET_ASSET_PATH}.  "
            f"Recreate it before next open_widget() call.\n\n"
            + TEMPLATE_SETUP_INSTRUCTIONS
        )
    return bool(deleted)


def rebuild_widget() -> None:
    """Reopen the widget — drops the cached UI and re-injects fresh UI.

    Does NOT delete the template asset.  If you need to delete the template
    (e.g. it is corrupt and must be recreated), call ``delete_widget()``
    explicitly first.
    """
    global _active_ui
    _active_ui = None
    open_widget()
