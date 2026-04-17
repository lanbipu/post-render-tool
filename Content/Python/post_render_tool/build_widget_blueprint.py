"""Populate BP_PostRenderToolWidget to satisfy the BindWidget contract.

One-shot script that adds the 33 required + 8 optional widgets declared in
``Source/PostRenderTool/Public/PostRenderToolWidget.h`` to the (usually empty)
``BP_PostRenderToolWidget`` Blueprint, so the first-time setup does not require
dragging 41 widgets by hand in the UMG Designer.

Usage inside the UE Editor Python console:

    from post_render_tool import build_widget_blueprint
    build_widget_blueprint.build()

Safe to re-run — existing widgets (matched by name) are kept untouched. Only
missing bindings are added, which is also the right behaviour after C++
UPROPERTY(BindWidget) additions.

Visual layout is intentionally minimal (flat VerticalBox). After the Blueprint
compiles green, reorganize the hierarchy, add nesting / padding / labels in
the Designer as desired; the BindWidget contract only cares about widget names
+ types, not layout.
"""

from __future__ import annotations

from typing import List, Tuple, Type

import unreal

WIDGET_BP_PATH = "/PostRenderTool/Blueprints/BP_PostRenderToolWidget"
ROOT_PANEL_NAME = "RootPanel"

# Mirror of docs/bindwidget-contract.md "Required widgets (33)" table.
_REQUIRED: List[Tuple[str, Type[unreal.Widget]]] = [
    ("btn_recheck", unreal.Button),
    ("btn_browse", unreal.Button),
    ("txt_file_path", unreal.TextBlock),
    ("txt_frame_count", unreal.TextBlock),
    ("txt_focal_range", unreal.TextBlock),
    ("txt_timecode", unreal.TextBlock),
    ("txt_sensor_width", unreal.TextBlock),
    ("spn_fps", unreal.SpinBox),
    ("txt_detected_fps", unreal.TextBlock),
    ("spn_frame", unreal.SpinBox),
    ("txt_designer_pos", unreal.TextBlock),
    ("txt_designer_rot", unreal.TextBlock),
    ("txt_ue_pos", unreal.TextBlock),
    ("txt_ue_rot", unreal.TextBlock),
    ("btn_spawn_cam", unreal.Button),
    ("cmb_pos_x_src", unreal.ComboBoxString),
    ("spn_pos_x_scale", unreal.SpinBox),
    ("cmb_pos_y_src", unreal.ComboBoxString),
    ("spn_pos_y_scale", unreal.SpinBox),
    ("cmb_pos_z_src", unreal.ComboBoxString),
    ("spn_pos_z_scale", unreal.SpinBox),
    ("cmb_rot_pitch_src", unreal.ComboBoxString),
    ("spn_rot_pitch_scale", unreal.SpinBox),
    ("cmb_rot_yaw_src", unreal.ComboBoxString),
    ("spn_rot_yaw_scale", unreal.SpinBox),
    ("cmb_rot_roll_src", unreal.ComboBoxString),
    ("spn_rot_roll_scale", unreal.SpinBox),
    ("btn_apply_mapping", unreal.Button),
    ("btn_save_mapping", unreal.Button),
    ("btn_import", unreal.Button),
    ("btn_open_seq", unreal.Button),
    ("btn_open_mrq", unreal.Button),
    ("txt_results", unreal.MultiLineEditableText),
]

# Mirror of docs/bindwidget-contract.md "Optional widgets (8)" table.
_OPTIONAL: List[Tuple[str, Type[unreal.Widget]]] = [
    ("prereq_label_0", unreal.TextBlock),
    ("prereq_label_1", unreal.TextBlock),
    ("prereq_label_2", unreal.TextBlock),
    ("prereq_label_3", unreal.TextBlock),
    ("prereq_label_4", unreal.TextBlock),
    ("prereq_label_5", unreal.TextBlock),
    ("prereq_summary", unreal.TextBlock),
    ("txt_frame_hint", unreal.TextBlock),
]


def _existing_child_names(panel: unreal.PanelWidget) -> set:
    names: set = set()
    try:
        for child in panel.get_all_children():
            names.add(child.get_name())
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(f"[build_widget_blueprint] get_all_children failed: {exc}")
    return names


def _ensure_root(widget_tree: unreal.WidgetTree) -> unreal.VerticalBox:
    root = widget_tree.root_widget
    if isinstance(root, unreal.VerticalBox) and root.get_name() == ROOT_PANEL_NAME:
        return root

    new_root = widget_tree.construct_widget(unreal.VerticalBox, ROOT_PANEL_NAME)
    widget_tree.root_widget = new_root
    unreal.log(f"[build_widget_blueprint] Created VerticalBox root '{ROOT_PANEL_NAME}'.")
    return new_root


def build(include_optional: bool = True) -> bool:
    """Populate the Blueprint. Returns True if the final compile succeeded."""
    bp = unreal.EditorAssetLibrary.load_asset(WIDGET_BP_PATH)
    if bp is None:
        unreal.log_error(
            f"[build_widget_blueprint] Asset not found: {WIDGET_BP_PATH}. "
            f"Create the empty Blueprint first (right-click Plugins / "
            f"VP Post-Render Tool Content / Blueprints → Blueprint Class → "
            f"PostRenderToolWidget → name it BP_PostRenderToolWidget)."
        )
        return False

    widget_tree = bp.get_editor_property("widget_tree")
    if widget_tree is None:
        unreal.log_error("[build_widget_blueprint] Could not access widget_tree.")
        return False

    root = _ensure_root(widget_tree)
    existing = _existing_child_names(root)

    targets = list(_REQUIRED)
    if include_optional:
        targets.extend(_OPTIONAL)

    added = 0
    for name, cls in targets:
        if name in existing:
            continue
        try:
            w = widget_tree.construct_widget(cls, name)
        except Exception as exc:  # noqa: BLE001
            unreal.log_error(
                f"[build_widget_blueprint] construct_widget failed for "
                f"{name} ({cls.__name__}): {exc}"
            )
            continue
        root.add_child(w)
        added += 1
        unreal.log(f"[build_widget_blueprint]   + {name} ({cls.__name__})")

    if added == 0:
        unreal.log("[build_widget_blueprint] No new widgets added (all bindings already present).")
    else:
        unreal.log(f"[build_widget_blueprint] Added {added} widget(s).")

    try:
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"[build_widget_blueprint] compile_blueprint failed: {exc}")
        return False

    saved = unreal.EditorAssetLibrary.save_asset(WIDGET_BP_PATH, only_if_is_dirty=False)
    if saved:
        unreal.log(f"[build_widget_blueprint] Saved {WIDGET_BP_PATH}.")
    else:
        unreal.log_warning(f"[build_widget_blueprint] save_asset returned False for {WIDGET_BP_PATH}.")

    return True
