"""Widget Builder — VP Post-Render Tool.

Loads ``BP_PostRenderToolWidget`` from the plugin's virtual content root,
spawns it as an editor tab via ``EditorUtilitySubsystem.spawn_and_register_tab``,
and hands the live instance to ``widget.PostRenderToolUI``, which binds
Python callbacks to the widgets exposed by the BindWidget contract in
``UPostRenderToolWidget`` (C++).

**The Blueprint is NOT shipped with the plugin source.** UE 5.7 does not
expose ``UWidgetBlueprint::WidgetTree`` to Python reflection, so this
project's convention is: each deployment authors the Blueprint once in
the UMG Designer, commits the resulting ``.uasset`` to git/p4, and the
team shares it via sync. A fresh clone without the committed ``.uasset``
must follow ``docs/deployment-guide.md`` §1.3 ("创建 Blueprint 资产并
手动搭建 UI") before this module can load anything.

The Blueprint's widget tree must satisfy the BindWidget contract in
``Source/PostRenderTool/Public/PostRenderToolWidget.h``; missing required
widgets fail the Blueprint compile. See ``TEMPLATE_SETUP_INSTRUCTIONS``
below for recovery steps when the asset is missing or corrupt.
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

BP_PostRenderToolWidget is NOT shipped in the plugin source. Each deployment
must author it once in the UMG Designer and commit the .uasset to git / p4.
This error means your working copy is missing that committed asset, or
it hasn't been authored for this project yet.

Recovery path — follow docs/deployment-guide.md §1.3 end to end:

  1. Confirm the plugin is installed at <UEProject>/Plugins/PostRenderTool/
     and enabled (Edit → Plugins → VP Post-Render Tool is green)
  2. p4 sync / git pull to pick up the committed BP_PostRenderToolWidget.uasset
     if another teammate has already authored it. If the asset path at
     Content/Blueprints/BP_PostRenderToolWidget.uasset now exists, restart
     the Editor and retry.
  3. If nobody has authored it yet (fresh project, new clone, asset lost),
     you are the one creating it. Open docs/deployment-guide.md §1.3 and
     walk through Step 1 → Step 7: build the Blueprint, drag 33 required
     + 8 optional BindWidgets into RootPanel per docs/bindwidget-contract.md,
     Compile until green, Save, then commit the .uasset so teammates get
     it on next sync.

There is no Python / C++ automation for populating the widget tree —
UE 5.7 hides UWidgetBlueprint::WidgetTree from reflection, and the team
decided (commit bd140d7) that Designer hand-authoring + version-controlled
.uasset is the canonical path.
""".strip()

# Module-level reference — prevents GC of the UI builder and its callbacks.
_active_ui = None


def load_widget():
    """Load the BP_PostRenderToolWidget Blueprint from the plugin mount.

    The asset is NOT shipped inside the plugin — each deployment authors it
    once in the UMG Designer and commits the ``.uasset`` to version control.
    This function only consumes the already-committed asset; if it's missing,
    you have to go through ``docs/deployment-guide.md`` §1.3 to create it.

    Returns
    -------
    unreal.EditorUtilityWidgetBlueprint

    Raises
    ------
    RuntimeError
        If the asset does not exist on disk (i.e. §1.3 has not been completed
        on this machine, or the committed asset hasn't been synced).
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
    """Delete the deployment-authored Blueprint asset from disk.

    .. warning::
       Destructive. This asset is NOT shipped with the plugin; it was
       authored in the UMG Designer per ``docs/deployment-guide.md`` §1.3
       and committed to git / p4. Deleting it locally means ``open_widget()``
       will fail until you either:

         - ``git pull`` / ``p4 sync`` the committed asset back from source
           control, or
         - Re-author from scratch following §1.3 Step 1 → Step 7 (a full
           Designer session dragging 41 widgets and compiling)

       Only call this if the local copy is genuinely corrupt and you want
       to force a clean re-sync.

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
