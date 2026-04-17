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
    """Populate the Blueprint via the C++ helper.

    Returns True iff every target was either newly added or already existed,
    compile succeeded, and save succeeded. Any helper exception, hard-failure
    return code (InvalidInput / InvalidRoot / ConstructFailed), compile error,
    or save failure makes this return False so callers can't mistake a broken
    BP for a successful run.
    """
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

    result_enum = getattr(unreal, "PostRenderToolEnsureResult", None)
    if result_enum is None:
        unreal.log_error(
            "[build_widget_blueprint] unreal.PostRenderToolEnsureResult enum "
            "unavailable; rebuild the plugin with the latest "
            "PostRenderToolBuildHelper.h."
        )
        return False
    added_value = result_enum.ADDED
    exists_value = result_enum.ALREADY_EXISTS

    targets = list(_REQUIRED)
    if include_optional:
        targets.extend(_OPTIONAL)

    added = 0
    already = 0
    failures: list = []
    for name, cls in targets:
        try:
            outcome = helper.ensure_bind_widget(bp, name, cls)
        except Exception as exc:  # noqa: BLE001
            unreal.log_error(
                f"[build_widget_blueprint] ensure_bind_widget raised for "
                f"{name} ({cls.__name__}): {exc}"
            )
            failures.append((name, cls.__name__, f"exception: {exc}"))
            continue

        if outcome == added_value:
            added += 1
            unreal.log(f"[build_widget_blueprint]   + {name} ({cls.__name__})")
        elif outcome == exists_value:
            already += 1
        else:
            unreal.log_error(
                f"[build_widget_blueprint] ensure_bind_widget rejected "
                f"{name} ({cls.__name__}): outcome={outcome}"
            )
            failures.append((name, cls.__name__, str(outcome)))

    unreal.log(
        f"[build_widget_blueprint] Summary: added={added}, "
        f"already_present={already}, failed={len(failures)}, "
        f"total_targets={len(targets)}"
    )

    if failures:
        unreal.log_error(
            f"[build_widget_blueprint] {len(failures)} binding(s) could not be "
            f"ensured; aborting compile/save so the BP is not left half-populated."
        )
        for name, cls_name, reason in failures:
            unreal.log_error(f"[build_widget_blueprint]   - {name} ({cls_name}): {reason}")
        return False

    try:
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"[build_widget_blueprint] compile_blueprint failed: {exc}")
        return False

    saved = unreal.EditorAssetLibrary.save_asset(WIDGET_BP_PATH, only_if_is_dirty=False)
    if not saved:
        unreal.log_error(
            f"[build_widget_blueprint] save_asset returned False for "
            f"{WIDGET_BP_PATH} — check file write permissions, source control "
            f"lock state, and that the asset isn't open in another editor tab."
        )
        return False

    unreal.log(f"[build_widget_blueprint] Saved {WIDGET_BP_PATH}.")
    return True
