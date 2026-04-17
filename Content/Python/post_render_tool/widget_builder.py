"""Widget Builder — VP Post-Render Tool.

Loads ``BP_PostRenderToolWidget`` from the plugin's virtual content root,
spawns it as an editor tab via ``EditorUtilitySubsystem.spawn_and_register_tab``,
and hands the live instance to ``widget.PostRenderToolUI``, which binds
Python callbacks to the widgets exposed by the BindWidget contract in
``UPostRenderToolWidget`` (C++).

**The Blueprint is NOT shipped with the plugin source.** UE 5.7 does not
expose ``UWidgetBlueprint::WidgetTree`` to Python reflection, so this
project's convention is: the **first** bootstrapping deployment authors
the Blueprint once in the UMG Designer and commits the resulting
``.uasset`` to the project's git/p4 repo. All **subsequent** deployments
(teammates, CI, other machines) just ``git pull`` / ``p4 sync`` to
receive the same asset — they do NOT re-author it.

This module only *consumes* the committed asset. If ``load_widget()``
raises because the asset is missing, first try to sync from source
control; fall back to ``docs/deployment-guide.md`` §1.3 only when no
teammate has bootstrapped the asset yet (fresh project, or the depot
copy is gone).

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

BP_PostRenderToolWidget is NOT shipped with the plugin source. The canonical
distribution is: the first team member who sets up the project bootstraps
the Blueprint once via docs/deployment-guide.md §1.3, commits the .uasset,
and everyone else gets it via git pull / p4 sync. This error means either
(a) the committed asset hasn't reached your working copy yet, or (b) it
has never been bootstrapped for this project.

Resolve in this order:

  1. Confirm the plugin is installed at <UEProject>/Plugins/PostRenderTool/
     and enabled (Edit → Plugins → VP Post-Render Tool is green).

  2. Sync from source control. Run `git pull` / `p4 sync` and verify that
     `Content/Blueprints/BP_PostRenderToolWidget.uasset` appears under the
     plugin directory. If it does, restart the Editor and retry — you do
     NOT need to build anything yourself. In 90% of cases this is enough.

  3. Only if sync comes back empty (fresh project that has never been
     bootstrapped, or the repo copy was accidentally deleted upstream and
     nobody has it), follow docs/deployment-guide.md §1.3 Step 1 → Step 7
     to author the Blueprint yourself — then commit the .uasset so every
     subsequent teammate recovers via sync (they won't have to repeat the
     work). This is a one-time bootstrap, not a per-deployment task.

There is no Python / C++ automation for populating the widget tree —
UE 5.7 hides UWidgetBlueprint::WidgetTree from reflection, and the team
decided (commit bd140d7) that Designer hand-authoring + version-controlled
.uasset is the canonical path.
""".strip()

# Module-level reference — prevents GC of the UI builder and its callbacks.
_active_ui = None


def load_widget():
    """Load the BP_PostRenderToolWidget Blueprint from the plugin mount.

    The asset is NOT shipped with the plugin source. It is authored once by
    whoever bootstraps the project (via ``docs/deployment-guide.md`` §1.3)
    and committed to git / p4; every later deployment just syncs to obtain
    it. This function only *consumes* the committed asset.

    Returns
    -------
    unreal.EditorUtilityWidgetBlueprint

    Raises
    ------
    RuntimeError
        If the asset does not exist on disk. In that case, sync first;
        only follow §1.3 if sync does not yield the asset (meaning
        nobody has bootstrapped it for this project yet).
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
