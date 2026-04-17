"""Populate BP_PostRenderToolWidget to satisfy the BindWidget contract.

One-shot script that adds the 33 required + 8 optional widgets declared in
``Source/PostRenderTool/Public/PostRenderToolWidget.h`` to the (usually empty)
``BP_PostRenderToolWidget`` Blueprint, so the first-time setup does not require
dragging 41 widgets by hand in the UMG Designer.

UE 5.7 does NOT expose ``UWidgetBlueprint::WidgetTree`` to Python (no
``BlueprintReadOnly`` / ``EditAnywhere`` flags → invisible to the reflection
system). This script therefore delegates all tree mutation to the C++ helper
``UPostRenderToolBuildHelper::EnsureBindWidget`` (declared in
``Source/PostRenderTool/Public/PostRenderToolBuildHelper.h``), which is a
``BlueprintCallable`` UFUNCTION bridging Python to the engine API. Python
handles iteration, compile and save; C++ handles the single unexposed step.

Usage inside the UE Editor Python console:

    from post_render_tool import build_widget_blueprint
    build_widget_blueprint.build()

Safe to re-run after layout polish:

- Existing widgets are detected by name across the **entire** widget tree
  (recursive through ``PanelWidget`` children AND ``ContentWidget`` content),
  so widgets wrapped in Border / SizeBox / nested VerticalBox are recognized
  and not duplicated.
- An existing PanelWidget root is never replaced; new bindings append to
  whatever root the user left behind. Only a completely empty tree gets a
  fresh ``VerticalBox`` root named ``RootPanel``.
- If the existing root is NOT a PanelWidget, the helper returns false for
  every add and logs a warning — no forced overwrite.

Rerun is the right action after:

- First bootstrap on a new machine (empty BP + nothing added)
- C++ adds a new ``UPROPERTY(BindWidget)`` — rerun appends just the new ones
- User accidentally deleted a widget in the Designer — rerun restores it

Known blind spots (do **not** put BindWidget targets inside these if you plan
to rerun): ``UUserWidget`` nested subobjects, ``UExpandableArea`` Header/Body,
``URichTextBlock`` inline decorators.
"""

from __future__ import annotations

from typing import List, Tuple, Type

import unreal

WIDGET_BP_PATH = "/PostRenderTool/Blueprints/BP_PostRenderToolWidget"

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


def build(include_optional: bool = True) -> bool:
    """Populate the Blueprint via the C++ helper. Returns True on success."""
    bp = unreal.EditorAssetLibrary.load_asset(WIDGET_BP_PATH)
    if bp is None:
        unreal.log_error(
            f"[build_widget_blueprint] Asset not found: {WIDGET_BP_PATH}. "
            f"Create the empty Blueprint first (right-click Plugins / "
            f"VP Post-Render Tool Content / Blueprints → Blueprint Class → "
            f"PostRenderToolWidget → name it BP_PostRenderToolWidget)."
        )
        return False

    helper = getattr(unreal, "PostRenderToolBuildHelper", None)
    if helper is None:
        unreal.log_error(
            "[build_widget_blueprint] unreal.PostRenderToolBuildHelper is not "
            "available — the plugin has not been rebuilt with the C++ helper. "
            "Close the Editor, delete Plugins/post-render-tool/Binaries and "
            "Intermediate, reopen the .uproject and rebuild when prompted."
        )
        return False

    targets = list(_REQUIRED)
    if include_optional:
        targets.extend(_OPTIONAL)

    added = 0
    for name, cls in targets:
        try:
            was_added = helper.ensure_bind_widget(bp, name, cls)
        except Exception as exc:  # noqa: BLE001
            unreal.log_error(
                f"[build_widget_blueprint] ensure_bind_widget failed for "
                f"{name} ({cls.__name__}): {exc}"
            )
            continue
        if was_added:
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
        unreal.log_warning(
            f"[build_widget_blueprint] save_asset returned False for {WIDGET_BP_PATH}."
        )

    return True
