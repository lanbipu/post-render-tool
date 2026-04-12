# BindWidget Contract Reference

The C++ class `UPostRenderToolWidget` (in `Source/PostRenderTool/Public/PostRenderToolWidget.h`) declares widget pointers using `UPROPERTY(BlueprintReadOnly, meta=(BindWidget))`. The child Blueprint `BP_PostRenderToolWidget` (in `Content/Blueprints/`) MUST contain widgets with matching names and types, or Blueprint compilation fails with:

> `A required widget binding "<name>" of type <type> was not found.`

Python (`Content/Python/post_render_tool/widget.py`) reads the same names back via `host.get_editor_property("<name>")`. The three sides — C++, Blueprint, Python — must agree on names and types.

## Required widgets (33)

| Section | Name | Type |
|---|---|---|
| Prerequisites | `btn_recheck` | `UButton` |
| CSV File | `btn_browse` | `UButton` |
| CSV File | `txt_file_path` | `UTextBlock` |
| CSV Preview | `txt_frame_count` | `UTextBlock` |
| CSV Preview | `txt_focal_range` | `UTextBlock` |
| CSV Preview | `txt_timecode` | `UTextBlock` |
| CSV Preview | `txt_sensor_width` | `UTextBlock` |
| CSV Preview | `spn_fps` | `USpinBox` |
| CSV Preview | `txt_detected_fps` | `UTextBlock` |
| Coord Verification | `spn_frame` | `USpinBox` |
| Coord Verification | `txt_designer_pos` | `UTextBlock` |
| Coord Verification | `txt_designer_rot` | `UTextBlock` |
| Coord Verification | `txt_ue_pos` | `UTextBlock` |
| Coord Verification | `txt_ue_rot` | `UTextBlock` |
| Coord Verification | `btn_spawn_cam` | `UButton` |
| Axis Mapping — Pos | `cmb_pos_x_src` | `UComboBoxString` |
| Axis Mapping — Pos | `spn_pos_x_scale` | `USpinBox` |
| Axis Mapping — Pos | `cmb_pos_y_src` | `UComboBoxString` |
| Axis Mapping — Pos | `spn_pos_y_scale` | `USpinBox` |
| Axis Mapping — Pos | `cmb_pos_z_src` | `UComboBoxString` |
| Axis Mapping — Pos | `spn_pos_z_scale` | `USpinBox` |
| Axis Mapping — Rot | `cmb_rot_pitch_src` | `UComboBoxString` |
| Axis Mapping — Rot | `spn_rot_pitch_scale` | `USpinBox` |
| Axis Mapping — Rot | `cmb_rot_yaw_src` | `UComboBoxString` |
| Axis Mapping — Rot | `spn_rot_yaw_scale` | `USpinBox` |
| Axis Mapping — Rot | `cmb_rot_roll_src` | `UComboBoxString` |
| Axis Mapping — Rot | `spn_rot_roll_scale` | `USpinBox` |
| Axis Mapping | `btn_apply_mapping` | `UButton` |
| Axis Mapping | `btn_save_mapping` | `UButton` |
| Actions | `btn_import` | `UButton` |
| Actions | `btn_open_seq` | `UButton` |
| Actions | `btn_open_mrq` | `UButton` |
| Actions | `txt_results` | `UMultiLineEditableText` |

## Optional widgets (8)

These use `meta=(BindWidgetOptional)` — missing them does not break the Blueprint compile, but the corresponding Python feature silently degrades.

| Name | Type | Degradation if missing |
|---|---|---|
| `prereq_label_0` ~ `prereq_label_5` | `UTextBlock` | Individual prerequisite status lines not shown (summary count still works) |
| `prereq_summary` | `UTextBlock` | "N / 6 OK" header summary not shown |
| `txt_frame_hint` | `UTextBlock` | "idx / total" frame indicator not shown |

## Python-side contract

`widget.py` declares two tuples that mirror the C++ side:

- `_REQUIRED_CONTROLS` — 33 entries matching the required table above
- `_OPTIONAL_CONTROLS` — 8 entries matching the optional table above

If the Python tuples drift from the C++ declarations, `get_editor_property()` returns `None` for the missing names and the binder logs a warning. Keep all three sides in sync.

## Adding a new binding

To add a new widget to the contract:

1. Add the UPROPERTY to `Source/PostRenderTool/Public/PostRenderToolWidget.h`:
   ```cpp
   UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
   UButton* btn_new_feature;
   ```
2. Close UE Editor completely
3. Rebuild the plugin (UBT, via IDE or `xcodebuild`) — Live Coding does NOT support UPROPERTY changes
4. Re-open the host project
5. Open `BP_PostRenderToolWidget` in the Designer
6. Drag a matching widget type into the hierarchy, name it `btn_new_feature`
7. Compile the Blueprint (Ctrl+B) — must succeed
8. Save (Ctrl+S)
9. Update `Content/Python/post_render_tool/widget.py`:
   - Add `"btn_new_feature"` to `_REQUIRED_CONTROLS` (or `_OPTIONAL_CONTROLS`)
   - Add binding in `_bind_events`: `self._bind_click("btn_new_feature", self._on_new_feature)`
   - Implement `_on_new_feature(self)` method with the business logic
10. Hot-reload: `importlib.reload(widget); widget_builder.rebuild_widget()`
11. Update this document — add a row to the appropriate table above
12. Commit everything in one logical unit: C++ header + `.uasset` + `widget.py` + this doc

## Removing a binding

Reverse of the above, same order. The UMG compiler will fail if you remove a required UPROPERTY while the Blueprint still has the widget — remove from Blueprint first, then from C++.

## Type-mismatch example

If the C++ declares:
```cpp
UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
UButton* btn_import;
```
and the Blueprint's `btn_import` is a `Border` instead of a `Button`, Blueprint compile will fail with:

> `A required widget binding "btn_import" of type UButton was not found.`

The fix is always on the Blueprint side: change the widget's type to match the C++ declaration, not the other way around. The C++ contract is the source of truth.
