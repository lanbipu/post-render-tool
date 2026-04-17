"""Populate BP_PostRenderToolWidget to satisfy the BindWidget contract.

One-shot script that adds the 33 required + 8 optional widgets declared in
``Source/PostRenderTool/Public/PostRenderToolWidget.h`` to the (usually empty)
``BP_PostRenderToolWidget`` Blueprint, so the first-time setup does not require
dragging 41 widgets by hand in the UMG Designer.

Usage inside the UE Editor Python console:

    from post_render_tool import build_widget_blueprint
    build_widget_blueprint.build()

Safe to re-run after layout polish:

- Existing widgets are detected by name across the **entire** widget tree,
  including inside ``PanelWidget`` subclasses (VerticalBox, HorizontalBox,
  CanvasPanel, Overlay, ScrollBox, ...) **and** ``ContentWidget`` subclasses
  (Border, Button, SizeBox, ScaleBox, NamedSlot, ...). So the common polish
  patterns — wrapping a TextBlock in a Border for background, or a Button in
  a SizeBox for fixed width — do not trick the script into re-creating the
  inner BindWidget on rerun.
- An existing PanelWidget root is never replaced; new bindings are appended
  to whatever root the user left behind. Only a completely empty tree gets
  a fresh ``VerticalBox`` root named ``RootPanel``.
- If the existing root is NOT a PanelWidget (e.g. a bare SizeBox), the
  script aborts with a user-actionable error instead of forcing.

Known blind spots (do **not** put BindWidget targets inside these if you
plan to rerun the script):

- ``UUserWidget`` subobjects nested inside this Blueprint — the script only
  walks the top-level tree, not user-widget children.
- Exotic compound widgets like ``UExpandableArea`` (Header / Body slots),
  ``URichTextBlock`` inline decorators — rare in practice, not covered.

Rerun is the right action after:

- First bootstrap on a new machine (empty BP + nothing added)
- C++ adds a new ``UPROPERTY(BindWidget)`` — rerun appends just the new ones
- User accidentally deleted a widget in the Designer — rerun restores it

Visual layout is intentionally minimal (flat VerticalBox) on first run. After
the Blueprint compiles green, reorganize the hierarchy, add nesting / padding
/ labels in the Designer as desired; the BindWidget contract only cares about
widget names + types, not layout, and rerunning this script will not undo
your polish.
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


def _collect_all_widget_names(widget_tree: unreal.WidgetTree) -> set:
    """Walk the entire widget tree, collecting every widget's name.

    Handles the two container families commonly used during UMG layout polish:

    - ``UPanelWidget`` subclasses (``VerticalBox``, ``HorizontalBox``,
      ``CanvasPanel``, ``Overlay``, ``UniformGridPanel``, ``ScrollBox``,
      ``WrapBox``, ``StackBox``, ...) — multiple children via
      ``get_all_children()``
    - ``UContentWidget`` subclasses (``Border``, ``Button``, ``SizeBox``,
      ``ScaleBox``, ``NamedSlot``, ``BackgroundBlur``, ``InvalidationBox``,
      ``MenuAnchor``, ``CheckBox``, ...) — a single wrapped child via
      ``get_content()``. Duck-typed because ``unreal.ContentWidget`` is not
      uniformly exposed as a Python class across UE 5.x builds.

    Without ``ContentWidget`` traversal, a BindWidget moved into e.g. a
    ``Border`` for background tint would not be seen on rerun and would be
    duplicated, breaking the Blueprint compile.
    """
    names: set = set()
    root = widget_tree.root_widget
    if root is None:
        return names

    stack: list = [root]
    while stack:
        w = stack.pop()
        if w is None:
            continue
        try:
            names.add(w.get_name())
        except Exception:  # noqa: BLE001
            continue

        if isinstance(w, unreal.PanelWidget):
            try:
                for child in w.get_all_children():
                    if child is not None:
                        stack.append(child)
            except Exception:  # noqa: BLE001
                pass
            continue

        get_content = getattr(w, "get_content", None)
        if callable(get_content):
            try:
                child = get_content()
                if child is not None:
                    stack.append(child)
            except Exception:  # noqa: BLE001
                pass
    return names


def _resolve_root_panel(widget_tree: unreal.WidgetTree):
    """Return a PanelWidget to append missing bindings into.

    - Empty tree → create a ``VerticalBox`` named ``RootPanel`` and install it
      as the tree root.
    - Existing root that is a PanelWidget → return it untouched (never
      replaced, preserves the user's layout work).
    - Existing root that is NOT a PanelWidget (e.g. a bare SizeBox wrapping a
      single child) → cannot add children; return None so ``build`` aborts
      cleanly with a user-actionable message.
    """
    root = widget_tree.root_widget
    if root is None:
        new_root = widget_tree.construct_widget(unreal.VerticalBox, ROOT_PANEL_NAME)
        widget_tree.root_widget = new_root
        unreal.log(f"[build_widget_blueprint] Created VerticalBox root '{ROOT_PANEL_NAME}'.")
        return new_root

    if isinstance(root, unreal.PanelWidget):
        return root

    unreal.log_error(
        f"[build_widget_blueprint] Root widget '{root.get_name()}' is "
        f"{type(root).__name__}, which is not a PanelWidget. Open the "
        f"Blueprint and wrap it in a VerticalBox / HorizontalBox / Overlay / "
        f"CanvasPanel before re-running this script — the script will never "
        f"overwrite your existing root."
    )
    return None


def build(include_optional: bool = True) -> bool:
    """Populate the Blueprint. Returns True if the final compile succeeded.

    Safe to rerun after layout polish: existing widgets are detected by name
    anywhere in the tree (not just direct root children), and an existing
    PanelWidget root is never replaced.
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

    widget_tree = bp.get_editor_property("widget_tree")
    if widget_tree is None:
        unreal.log_error("[build_widget_blueprint] Could not access widget_tree.")
        return False

    existing = _collect_all_widget_names(widget_tree)

    root = _resolve_root_panel(widget_tree)
    if root is None:
        return False

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
        unreal.log(f"[build_widget_blueprint]   + {name} ({cls.__name__}) — appended to "
                   f"'{root.get_name()}'")

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
