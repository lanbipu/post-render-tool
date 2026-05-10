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


def _resolve_parent_class(parent_class_path: str):
    parent_class = unreal.load_class(None, parent_class_path)
    if parent_class is not None:
        return parent_class

    # Python exposes native classes without the module prefix, e.g.
    # /Script/PostRenderTool.PostRenderToolWidget -> unreal.PostRenderToolWidget.
    class_name = parent_class_path.rsplit(".", 1)[-1]
    return getattr(unreal, class_name, None)


def _create_blueprint(asset_path: str, parent_class_path: str) -> "unreal.WidgetBlueprint":
    asset_name = asset_path.rsplit("/", 1)[-1]
    package_path = asset_path.rsplit("/", 1)[0]
    parent_class = _resolve_parent_class(parent_class_path)
    if parent_class is None:
        raise RuntimeError(f"Cannot resolve parent class '{parent_class_path}'.")

    if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
        unreal.EditorAssetLibrary.make_directory(package_path)

    factory = unreal.EditorUtilityWidgetBlueprintFactory()
    try:
        factory.set_editor_property("parent_class", parent_class)
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(
            "[build_widget_blueprint] could not set factory parent_class "
            f"for {asset_name}: {exc}; will try reparent after creation"
        )

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    bp = asset_tools.create_asset(asset_name, package_path, None, factory)
    if bp is None:
        raise RuntimeError(f"create_asset failed for '{asset_path}'.")

    try:
        current_parent = bp.get_editor_property("parent_class")
    except Exception:  # noqa: BLE001
        current_parent = None
    if current_parent != parent_class:
        try:
            unreal.BlueprintEditorLibrary.reparent_blueprint(bp, parent_class)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Created '{asset_path}', but failed to reparent to "
                f"'{parent_class_path}': {exc}"
            ) from exc

    unreal.log(f"[build_widget_blueprint] created widget blueprint {asset_path}")
    return bp


def _load_blueprint(
    asset_path: str,
    parent_class_path: str,
    *,
    create_if_missing: bool = False,
) -> "unreal.WidgetBlueprint":
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        if create_if_missing:
            return _create_blueprint(asset_path, parent_class_path)
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


def _resolve_widget_classes(widget_type: str):
    """Return (py_cls, u_cls) for a spec type string.

    - py_cls: the `unreal.<Type>` Python class (for isinstance checks).
    - u_cls:  the UE UClass object from `py_cls.static_class()` (for
              TSubclassOf<UWidget> UFUNCTION args — C++ helper expects this).

    Don't conflate them: isinstance(widget, u_cls) raises TypeError because a
    UClass is not a Python type.
    """
    py_cls = widget_properties.WIDGET_CLASS_MAP.get(widget_type)
    if py_cls is None:
        return None, None
    try:
        u_cls = py_cls.static_class()
    except AttributeError:
        u_cls = py_cls
    return py_cls, u_cls


def _resolve_widget_uclass(widget_type: str):
    """Back-compat shim returning only the UClass (used by EnsureRootPanel)."""
    _, u_cls = _resolve_widget_classes(widget_type)
    return u_cls


def _apply_spec_props(widget, slot, node, force_reapply: bool, is_newly_created: bool):
    """Shared prop/slot application used by both panel and ExpandableArea paths."""
    if not (is_newly_created or force_reapply):
        return
    widget_type = node["type"]
    variant = node.get("variant")
    variant_props = widget_variants.resolve(widget_type, variant) if variant else {}
    explicit_props = node.get("properties") or {}
    props = {**variant_props, **explicit_props}
    if props:
        widget_properties.apply_widget_properties(widget, props)
    slot_props = node.get("slot") or {}
    if slot_props and slot is not None:
        widget_properties.apply_slot_properties(slot, slot_props)


_SLOT_KIND_TO_NAME = {"header": "Header", "body": "Body"}


def _ensure_expandable_slot(bp, expandable, node: dict, slot_kind: str, force_reapply: bool):
    """Ensure a widget sits in an ExpandableArea's Header or Body named slot.

    `UExpandableArea` implements `INamedSlotInterface`. Its `HeaderContent` /
    `BodyContent` UPROPERTYs are plain `UPROPERTY()` (no BP visibility, no
    editor-only flag), and `SetContentForSlot` is a bare C++ virtual — none of
    them are reachable from Python reflection. The C++ helper's new
    `EnsureWidgetInNamedSlot` UFUNCTION bridges this gap: it dispatches through
    `INamedSlotInterface::SetContentForSlot(FName, UWidget*)` and also handles:

      - idempotency: re-uses widgets already in the slot (preserving user tweaks)
      - migration: if a same-named widget lives elsewhere in the tree (e.g. old
        spec had `lbl_prereq_header` as a direct VerticalBox child), the helper
        detaches it from its old parent and re-parents into the named slot.
    """
    widget_type = node["type"]
    name = node["name"]
    py_cls, u_cls = _resolve_widget_classes(widget_type)
    if u_cls is None:
        unreal.log_error(
            f"[build_widget_blueprint] unknown widget type {widget_type!r} in "
            f"ExpandableArea.{slot_kind}_content slot; skipped"
        )
        return

    slot_fname = _SLOT_KIND_TO_NAME.get(slot_kind)
    if slot_fname is None:
        raise RuntimeError(f"Unknown slot_kind {slot_kind!r}; expected 'header' or 'body'")

    result, widget = unreal.PostRenderToolBuildHelper.ensure_widget_in_named_slot(
        bp, unreal.Name(name), u_cls, expandable, unreal.Name(slot_fname)
    )

    if result == unreal.EnsureWidgetResult.TYPE_MISMATCH:
        raise RuntimeError(
            f"Widget '{name}' exists but type mismatches; abort. "
            f"Delete the widget in Designer then rerun, or rename the spec entry."
        )
    if result == unreal.EnsureWidgetResult.INVALID_INPUT:
        raise RuntimeError(f"Invalid input for widget '{name}' — check expandable / slot name.")
    if result == unreal.EnsureWidgetResult.PARENT_CANNOT_HOLD_CHILDREN:
        raise RuntimeError(
            f"Parent of '{name}' does not implement INamedSlotInterface — spec tree invalid."
        )

    is_newly_created = (result == unreal.EnsureWidgetResult.CREATED)

    # ExpandableArea named slots have no UPanelSlot; slot layout is governed by
    # the ExpandableArea's own HeaderPadding / AreaPadding.
    _apply_spec_props(widget, None, node, force_reapply, is_newly_created)

    # Recurse — the content widget is typically a UPanelWidget (HorizontalBox /
    # VerticalBox); its children go through the normal C++ helper, whose
    # FindWidgetByNameRecursive now descends into named slots for idempotency.
    for child in node.get("children") or []:
        _build_node(bp, widget, child, force_reapply=force_reapply)


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

    _apply_spec_props(widget, slot, node, force_reapply, is_newly_created)

    # ExpandableArea children go into HeaderContent / BodyContent slots, NOT into
    # a UPanelWidget.AddChild list. Spec convention: children[0]=Header, [1]=Body.
    if widget_type == "ExpandableArea":
        children = node.get("children") or []
        if len(children) != 2:
            raise RuntimeError(
                f"ExpandableArea {name!r} requires exactly 2 children "
                f"([0]=Header, [1]=Body); got {len(children)}"
            )
        _ensure_expandable_slot(bp, widget, children[0], "header", force_reapply)
        _ensure_expandable_slot(bp, widget, children[1], "body", force_reapply)
        return

    # Recurse into children regardless of whether this widget was new or old.
    for child in node.get("children") or []:
        _build_node(bp, widget, child, force_reapply=force_reapply)


def run_build(
    spec_path: Optional[str] = None,
    *,
    save: bool = True,
    compile_bp: bool = True,
    force_reapply: bool = False,
    create_if_missing: bool = False,
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
    parent_class_path = spec["blueprint"]["parent_class"]
    bp = _load_blueprint(
        asset_path,
        parent_class_path,
        create_if_missing=create_if_missing,
    )

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
