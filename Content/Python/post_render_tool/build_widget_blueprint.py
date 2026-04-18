"""Populate BP_PostRenderToolWidget from docs/widget-tree-spec.json.

Usage inside the UE Editor Python console:

    from post_render_tool import build_widget_blueprint
    build_widget_blueprint.run_build()

Idempotent — safe to re-run. Existing widgets (identified by name, anywhere
in the tree) are left untouched; the script only:
  - creates the root panel if the tree is empty,
  - creates widgets that are declared in the spec but missing from the tree,
  - applies widget/slot properties ONLY on freshly-created widgets
    (preserving user tweaks on already-existing widgets).

After any C++ contract change (UPROPERTY(BindWidget) added/removed), rerun
this script to regenerate the missing bindings; old ones remain intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import unreal

from . import spec_loader, widget_properties, widget_variants


DEFAULT_SPEC_PATH = "docs/widget-tree-spec.json"


def _plugin_root() -> Path:
    """Resolve the plugin root (where PostRenderTool.uplugin lives).

    sys.path contains Content/Python; this file is .../Content/Python/post_render_tool.
    Walk up three levels: file → post_render_tool → Python → Content → <plugin root>.
    """
    here = Path(__file__).resolve().parent  # .../Content/Python/post_render_tool
    return here.parent.parent.parent        # plugin root


def _resolve_spec_path(spec_path: Optional[str]) -> str:
    if spec_path:
        return spec_path
    return str(_plugin_root() / DEFAULT_SPEC_PATH)


def _load_blueprint(asset_path: str) -> "unreal.WidgetBlueprint":
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        raise RuntimeError(
            f"Cannot load widget blueprint at '{asset_path}'. "
            "Create it first via Content Browser → Blueprint Class → "
            "PostRenderToolWidget, or see deployment-guide.md §1.3."
        )
    if not isinstance(bp, unreal.WidgetBlueprint):
        raise RuntimeError(
            f"Asset '{asset_path}' is {type(bp).__name__}, expected WidgetBlueprint."
        )
    return bp


def _resolve_widget_uclass(widget_type: str):
    """Given a JSON-spec type string, return the concrete UClass to hand to the
    C++ helper's TSubclassOf<UWidget> parameter.

    unreal.* Python classes have a static_class() method that returns the UE
    UClass object. Fall back to the class itself for any odd binding case.
    """
    py_cls = widget_properties.WIDGET_CLASS_MAP.get(widget_type)
    if py_cls is None:
        return None
    try:
        return py_cls.static_class()
    except AttributeError:
        return py_cls


def _build_node(bp, parent_widget, node: dict, *, force_reapply: bool = False) -> None:
    """Recursive builder for a single spec node + its children.

    If ``force_reapply=True``, properties + slot are re-applied on widgets that
    already exist (by name). Use this after spec-level theme changes (variant
    updates, color tweaks) so the BP reflects the latest spec even though the
    tree structure is unchanged. User tweaks inside Designer WILL be overwritten.
    """
    widget_type = node["type"]
    name = node["name"]
    role = node["role"]
    cls_obj = _resolve_widget_uclass(widget_type)
    if cls_obj is None:
        unreal.log_error(
            f"[build_widget_blueprint] unknown widget type {widget_type!r} "
            f"for {name!r}; skipped"
        )
        return

    # UFUNCTION out-params become a Python tuple (return_value, *out_params)
    # per PyGenUtil contract. See plan Architecture notes.
    result, widget, slot = unreal.PostRenderToolBuildHelper.ensure_widget_under_parent(
        bp, unreal.Name(name), cls_obj, parent_widget
    )

    if result == unreal.EnsureWidgetResult.TYPE_MISMATCH:
        raise RuntimeError(
            f"Widget '{name}' exists but type mismatches; abort. "
            f"Delete the widget in Designer then rerun, or rename the spec entry."
        )
    if result == unreal.EnsureWidgetResult.INVALID_INPUT:
        raise RuntimeError(f"Invalid input for widget '{name}' — check parent / class.")
    if result == unreal.EnsureWidgetResult.PARENT_CANNOT_HOLD_CHILDREN:
        raise RuntimeError(
            f"Parent of '{name}' cannot hold children — spec tree invalid."
        )

    is_newly_created = (result == unreal.EnsureWidgetResult.CREATED)
    should_apply = is_newly_created or force_reapply

    # Apply properties on newly-created widgets, or on existing widgets when
    # force_reapply is True (spec-level theme sync).
    # Widget.cpp:195 sets bIsVariable=true on every new widget by default — no
    # explicit call needed to make contract widgets Variable. Decorative widgets
    # inherit the same default (minor overhead; accepted trade-off).
    if should_apply:
        # Merge variant-resolved props with explicit props. Explicit wins so
        # per-widget overrides (e.g. a custom Tint) always trump the variant.
        variant = node.get("variant")
        variant_props = widget_variants.resolve(widget_type, variant) if variant else {}
        explicit_props = node.get("properties") or {}
        props = {**variant_props, **explicit_props}
        if props:
            widget_properties.apply_widget_properties(widget, props)

        slot_props = node.get("slot") or {}
        if slot_props and slot is not None:
            widget_properties.apply_slot_properties(slot, slot_props)

    # Recurse into children regardless of whether this widget was new or old.
    for child in node.get("children") or []:
        _build_node(bp, widget, child, force_reapply=force_reapply)


def run_build(
    spec_path: Optional[str] = None,
    *,
    save: bool = True,
    compile_bp: bool = True,
    force_reapply: bool = False,
) -> "unreal.WidgetBlueprint":
    """Top-level entry — load spec, walk tree, compile + save BP.

    ``force_reapply=True`` re-applies properties + slots on widgets that already
    exist, overwriting any Designer tweaks. Use it after spec theme/variant
    changes to resync the BP visually. Default False preserves user edits.
    """
    spec_path = _resolve_spec_path(spec_path)
    unreal.log(f"[build_widget_blueprint] loading spec from {spec_path}")

    spec = spec_loader.load_spec(spec_path)
    errors = spec_loader.validate_spec(spec)
    if errors:
        raise RuntimeError("Spec validation failed:\n" + "\n".join(errors))

    asset_path = spec["blueprint"]["asset_path"]
    bp = _load_blueprint(asset_path)

    # Ensure root panel.
    root_panel_spec = spec["blueprint"]["root_panel"]
    root_cls_obj = _resolve_widget_uclass(root_panel_spec["type"])
    if root_cls_obj is None:
        raise RuntimeError(
            f"Unknown root panel type {root_panel_spec['type']!r} — "
            f"check spec_loader.PANEL_TYPES."
        )
    root = unreal.PostRenderToolBuildHelper.ensure_root_panel(
        bp, unreal.Name(root_panel_spec["name"]), root_cls_obj
    )
    if root is None:
        raise RuntimeError(
            "Could not ensure root panel — see UE Output Log for the "
            "root-widget-type-mismatch warning."
        )

    # Walk root_children under the root panel.
    for child_spec in spec.get("root_children") or []:
        _build_node(bp, root, child_spec, force_reapply=force_reapply)

    if compile_bp:
        unreal.log("[build_widget_blueprint] compiling blueprint…")
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)

    if save:
        unreal.log(f"[build_widget_blueprint] saving {asset_path}")
        unreal.EditorAssetLibrary.save_asset(asset_path)

    unreal.log("[build_widget_blueprint] done.")
    return bp
