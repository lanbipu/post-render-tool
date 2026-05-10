"""Widget Builder — VP Post-Render Tool.

Loads the production Figma widget by default while keeping
``BP_PostRenderToolWidget`` available as the legacy fallback. The selected
Blueprint is spawned as an editor tab via ``EditorUtilitySubsystem``, then
handed to ``widget.PostRenderToolUI`` / ``widget.PostRenderToolFigmaUI``, which bind
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

from pathlib import Path

import unreal

# Asset location inside the PostRenderTool plugin's Content folder.
# The plugin mounts Content/ at the virtual root `/PostRenderTool/`.
WIDGET_PACKAGE_PATH = "/PostRenderTool/Blueprints"
WIDGET_ASSET_NAME = "BP_PostRenderToolWidget"
WIDGET_FULL_PATH = f"{WIDGET_PACKAGE_PATH}/{WIDGET_ASSET_NAME}"
WIDGET_ASSET_PATH = f"{WIDGET_FULL_PATH}.{WIDGET_ASSET_NAME}"

FIGMA_WIDGET_ASSET_NAME = "BP_PostRenderToolWidget_Figma"
FIGMA_WIDGET_FULL_PATH = f"{WIDGET_PACKAGE_PATH}/{FIGMA_WIDGET_ASSET_NAME}"
FIGMA_WIDGET_ASSET_PATH = f"{FIGMA_WIDGET_FULL_PATH}.{FIGMA_WIDGET_ASSET_NAME}"
FIGMA_SPEC_PATH = "docs/widget-tree-spec-figma-v2.json"


def _plugin_root() -> Path:
    here = Path(__file__).resolve().parent
    return here.parent.parent.parent

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
_active_figma_tab_id = None


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


def load_figma_widget():
    """Load the experimental Figma-authored widget Blueprint."""
    loaded = None
    try:
        loaded = unreal.EditorAssetLibrary.load_asset(FIGMA_WIDGET_ASSET_PATH)
    except Exception as exc:
        raise RuntimeError(
            f"load_asset failed for {FIGMA_WIDGET_ASSET_PATH}: {exc}\n\n"
            "Run rebuild_figma_from_spec() to generate the asset from "
            f"{FIGMA_SPEC_PATH}."
        )
    if loaded is None:
        raise RuntimeError(
            f"Blueprint asset not found: {FIGMA_WIDGET_ASSET_PATH}\n\n"
            "Run:\n"
            "  from post_render_tool.widget_builder import rebuild_figma_from_spec\n"
            "  rebuild_figma_from_spec(force_reapply=True)\n"
        )
    unreal.log(f"[widget_builder] Loaded Figma template: {FIGMA_WIDGET_ASSET_PATH}")
    return loaded


def _make_ui(widget, ui_class_name: str):
    from . import widget as widget_module

    ui_cls = getattr(widget_module, ui_class_name)
    return ui_cls(widget)


def _inject_ui(widget_bp, *, ui_class_name: str = "PostRenderToolUI") -> None:
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
            _active_ui = _make_ui(widget, ui_class_name)
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
                _active_ui = _make_ui(w, ui_class_name)
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


def open_widget() -> bool:
    """Load the legacy template, spawn the editor tab, inject UI."""
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
            return False

    _inject_ui(widget_bp)
    return True


def open_figma_widget() -> bool:
    """Open BP_PostRenderToolWidget_Figma without touching the legacy widget."""
    global _active_figma_tab_id
    widget_bp = load_figma_widget()

    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        result = subsystem.spawn_and_register_tab_and_get_id(widget_bp)
        if isinstance(result, tuple):
            _active_figma_tab_id = result[-1]
        else:
            _active_figma_tab_id = None
        unreal.log("[widget_builder] Figma widget tab opened.")
    except Exception as exc:
        unreal.log_error(f"[widget_builder] Failed to open Figma widget tab: {exc}")
        try:
            unreal.EditorUtilityLibrary.run_editor_utility_widget(widget_bp)
            _active_figma_tab_id = None
            unreal.log("[widget_builder] Figma widget opened via fallback.")
        except Exception as exc2:
            unreal.log_error(f"[widget_builder] Figma fallback also failed: {exc2}.")
            return False

    _inject_ui(widget_bp, ui_class_name="PostRenderToolFigmaUI")
    return True


def open_default_widget() -> None:
    """Open the production widget, falling back to legacy if Figma is unavailable."""
    try:
        if open_figma_widget():
            return
        unreal.log_warning(
            "[widget_builder] Figma widget failed to open; falling back to legacy widget."
        )
    except RuntimeError as exc:
        unreal.log_warning(
            "[widget_builder] Figma widget unavailable; falling back to legacy widget. "
            f"{exc}"
        )
    open_widget()


def _close_figma_tab(widget_bp) -> None:
    """Best-effort close/release before deleting the generated Figma asset."""
    global _active_figma_tab_id
    subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)

    tab_ids = []
    if _active_figma_tab_id is not None:
        tab_ids.append(_active_figma_tab_id)

    try:
        tab_ids.append(subsystem.register_tab_and_get_id(widget_bp))
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(f"[widget_builder] Figma register_tab_and_get_id failed: {exc}")

    seen = set()
    for tab_id in tab_ids:
        key = str(tab_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            subsystem.close_tab_by_id(tab_id)
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(f"[widget_builder] Figma close_tab_by_id failed: {exc}")
        try:
            subsystem.unregister_tab_by_id(tab_id)
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(
                f"[widget_builder] Figma unregister_tab_by_id failed: {exc}"
            )

    try:
        subsystem.release_instance_of_asset(widget_bp)
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(f"[widget_builder] Figma release_instance_of_asset failed: {exc}")
    _active_figma_tab_id = None


def delete_figma_widget() -> bool:
    """Delete only the generated Figma widget asset; legacy widget is untouched."""
    global _active_ui
    _active_ui = None
    widget_bp = None
    try:
        widget_bp = unreal.EditorAssetLibrary.load_asset(FIGMA_WIDGET_ASSET_PATH)
    except Exception:
        widget_bp = None
    if widget_bp is not None:
        _close_figma_tab(widget_bp)
    try:
        deleted = bool(unreal.EditorAssetLibrary.delete_asset(FIGMA_WIDGET_FULL_PATH))
    except Exception as exc:
        unreal.log_warning(f"[widget_builder] delete Figma asset failed: {exc}")
        return False
    try:
        unreal.SystemLibrary.collect_garbage()
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(f"[widget_builder] collect_garbage after delete failed: {exc}")
    try:
        still_exists = bool(
            unreal.EditorAssetLibrary.does_asset_exist(FIGMA_WIDGET_ASSET_PATH)
        )
    except Exception:  # noqa: BLE001
        still_exists = False
    if still_exists:
        unreal.log_warning(
            f"[widget_builder] delete Figma asset did not unload/remove: "
            f"{FIGMA_WIDGET_ASSET_PATH}"
        )
        return False
    if not deleted and widget_bp is not None:
        unreal.log_warning(
            f"[widget_builder] delete Figma asset returned false: {FIGMA_WIDGET_ASSET_PATH}"
        )
    return deleted or widget_bp is None


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
        deleted = unreal.EditorAssetLibrary.delete_asset(WIDGET_FULL_PATH)
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


def rebuild_figma_from_spec(
    *,
    force_reapply: bool = True,
    recreate: bool = False,
) -> object:
    """Build/open the separate Figma widget Blueprint from its own spec file.

    ``recreate=True`` deletes only ``BP_PostRenderToolWidget_Figma`` first. Use
    it after structural spec changes such as adding wrapper ``SizeBox`` widgets.
    The legacy ``BP_PostRenderToolWidget`` asset is never deleted here.
    """
    from . import build_widget_blueprint

    if recreate:
        if not delete_figma_widget():
            raise RuntimeError(
                f"Could not delete generated Figma widget asset: {FIGMA_WIDGET_ASSET_PATH}"
            )

    bp = build_widget_blueprint.run_build(
        spec_path=str(_plugin_root() / FIGMA_SPEC_PATH),
        create_if_missing=True,
        force_reapply=force_reapply,
    )
    global _active_ui
    _active_ui = None
    open_figma_widget()
    return bp
