"""Widget Builder — VP Post-Render Tool.

Loads ``BP_PostRenderToolWidget`` from the plugin's virtual content root,
spawns it as an editor tab via ``EditorUtilitySubsystem.spawn_and_register_tab``,
and hands the live instance to ``widget.PostRenderToolUI``, which binds
Python callbacks to the widgets exposed by the BindWidget contract in
``UPostRenderToolWidget`` (C++).

**Blueprint distribution: automation-first, manual as fallback** (reverses
the bd140d7 "manual-only" stance, 2026-04-17). ``docs/widget-tree-spec.json``
is the single source of truth; ``rebuild_from_spec()`` (this module) →
``build_widget_blueprint.run_build()`` → ``UPostRenderToolBuildHelper`` C++
UFUNCTION bridge populates ``UWidgetBlueprint::WidgetTree`` idempotently
(existing user tweaks survive; ``force_reapply=True`` overrides for
theme-level edits). UE 5.7 still doesn't expose ``WidgetTree`` directly to
Python reflection — the helper UFUNCTIONs are the official escape hatch.

This module *consumes* the committed asset for normal runtime use; when
that asset is missing, prefer:

  1. ``git pull`` / ``p4 sync`` to recover the committed copy, OR
  2. ``rebuild_from_spec()`` to regenerate from JSON spec, OR
  3. ``docs/bootstrap-checklist.md`` for the manual fallback path
     (only when both spec and depot are unavailable — fresh projects
     before automation existed, or upstream wipe + spec corruption).

The Blueprint's widget tree must satisfy the BindWidget contract in
``Source/PostRenderTool/Public/PostRenderToolWidget.h``; missing required
widgets fail the Blueprint compile. See ``TEMPLATE_SETUP_INSTRUCTIONS``
below for sync/restore commands when the asset is missing or corrupt.
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

BP_PostRenderToolWidget is normally distributed via source control; the
preferred regeneration path is `rebuild_from_spec()` (JSON spec → BP).
Pick the recovery path that matches your situation:

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

Scenario C — fresh project, no .uasset committed yet, but spec is ready
-----------------------------------------------------------------------
The spec docs/widget-tree-spec.json exists, but this project has never
committed a built BP. Use the automation path:

  from post_render_tool.widget_builder import rebuild_from_spec
  rebuild_from_spec()

This calls build_widget_blueprint.run_build() which uses
unreal.PostRenderToolBuildHelper (C++ UFUNCTION bridge) to populate the
WidgetTree from the spec. Idempotent — safe to re-run. Commit the
resulting .uasset so future teammates land in Scenario A.

Scenario D — spec is also missing or corrupt (rare)
---------------------------------------------------
Manual fallback only. Follow docs/bootstrap-checklist.md to hand-author
the BP in UMG Designer per the Figma layout, then commit it. Treat this
as a one-time recovery, not a normal workflow — fix the spec afterward
so future regenerations stay automated.
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


def rebuild_from_spec(*, force_reapply: bool = False) -> object:
    """Re-populate BP_PostRenderToolWidget from docs/widget-tree-spec.json.

    Default (force_reapply=False): idempotent — existing widgets (with user
    tweaks) are preserved; only missing contract widgets are created and their
    spec'd properties applied.

    force_reapply=True: re-applies every widget's properties + slots from the
    spec, overwriting Designer tweaks. Use this after editing variants, colors,
    fonts, or any spec-level theme change to resync the BP visually.

    After C++ UPROPERTY changes, a full Editor restart + plugin rebuild is still
    required — this command only operates on the WidgetBlueprint asset, not the
    C++ reflection metadata.

    Re-opens the tab after rebuilding so the running Python UI picks up the
    regenerated bindings immediately.
    """
    from . import build_widget_blueprint
    bp = build_widget_blueprint.run_build(force_reapply=force_reapply)
    rebuild_widget()
    return bp
