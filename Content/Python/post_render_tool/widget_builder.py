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
and everyone else receives it via source-control sync. Figure out which
scenario you are in before running any command:

Scenario A — fresh clone, you never had the asset locally
---------------------------------------------------------
You just cloned the repo / synced the workspace for the first time, and
the .uasset has never existed in your working directory.

  • git repo:  git pull   (brings down the committed .uasset as part of the
               initial checkout)
  • p4 depot:  p4 sync    (same, pulls the head revision)

Verify {WIDGET_ASSET_PATH} now exists on disk, restart the Editor, retry.

Scenario B — you had it before, but the local file is gone / corrupt
--------------------------------------------------------------------
The asset existed locally at some point but you deleted it, a merge blew
it away, or it got corrupt. The depot copy is still healthy. `git pull`
and plain `p4 sync` WILL NOT help here — git pull only fetches new commits
(it doesn't restore working-tree deletions), and p4 sync short-circuits
with "up-to-date" when the head revision is already recorded as synced.
Use the correct per-SCM recovery command:

  • git repo:  git restore Content/Blueprints/BP_PostRenderToolWidget.uasset
               (or: git checkout HEAD -- <path>)
  • p4 depot:  p4 sync -f //depot/.../BP_PostRenderToolWidget.uasset
               (the -f flag force-resyncs even if p4 thinks you're current;
               alternatively `p4 revert` if the file is open in a changelist)

Scenario C — nobody has ever bootstrapped, or depot copy is gone too
--------------------------------------------------------------------
This is a fresh project where §1.3 has never been run, or an upstream
mistake wiped the committed .uasset. Only in this case do you actually
have to build the Blueprint yourself: follow docs/deployment-guide.md
§1.3 Step 1 → Step 7, then commit the resulting .uasset so every
subsequent teammate recovers via Scenario A or B, not a re-bootstrap.
This is a one-time bootstrap, not a per-deployment task.

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


def rebuild_from_spec() -> object:
    """Re-populate BP_PostRenderToolWidget from docs/widget-tree-spec.json.

    Idempotent: existing widgets (with user tweaks) are preserved; only missing
    contract widgets + their spec'd properties are added. After C++ UPROPERTY
    changes, a full Editor restart + plugin rebuild is still required — this
    command only operates on the WidgetBlueprint asset, not the C++ reflection
    metadata.

    Re-opens the tab after rebuilding so the running Python UI picks up the
    regenerated bindings immediately.
    """
    from . import build_widget_blueprint
    bp = build_widget_blueprint.run_build()
    rebuild_widget()
    return bp
