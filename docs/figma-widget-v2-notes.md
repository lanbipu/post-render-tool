# Figma Widget V2 Notes

## Asset Boundary

- The visual redesign is now the production asset:
  `/PostRenderTool/Blueprints/BP_PostRenderToolWidget`.
- The side-by-side `_Figma` asset is retired.
- Spec file: `docs/widget-tree-spec.json`.

## UE UMG Workarounds

- Figma border radius is approximated with UMG `Border` / `Button` styling; generated spec does not binary-edit `.uasset` files.
- The orange section accent is represented by a 3x13 `Image` inside a `SizeBox`; UMG `Image` does not expose the Figma 1px corner radius directly.
- Figma dot SVG assets are represented by tinted `Image` widgets, avoiding short-lived remote asset URLs.
- Figma's CSS borders are approximated by darker `Border` backgrounds and inner dividers because the current JSON property applicator does not set full `FSlateBrush` border margins.
- Coordinate Verification controls are retired and are not part of the required `BindWidget` contract.
- Solid-color `Border`, `Image`, and `Button` brushes use `/Engine/EngineResources/WhiteSquareTexture` as a tint base. Empty `SlateBrush` resources render as UE's dashed invalid-resource placeholder.
- Figma color values in the JSON spec are sRGB/CSS channels. `widget_properties.py` converts RGB channels to UE `LinearColor` channels before applying them, otherwise the panel renders too gray/bright in the Editor.
- The production widget root uses `VerticalBox` -> `Border` -> `EditorUtilityScrollBox` -> `VerticalBox`. The outer `Border` is assigned a `VerticalBoxSlot` with `size_rule=Fill`, matching the Editor Utility Widget pattern that gives the scroll panel a constrained viewport while still stretching with the tab.
- Non-interactive layout/decorative widgets use `SelfHitTestInvisible` so mouse wheel input can bubble to the root `EditorUtilityScrollBox`; interactive controls remain hit-testable.
- `UPostRenderToolWidget::NativeOnMouseWheel()` forwards unhandled wheel input to optional `lbl_root_scroll`, which requires a full plugin rebuild and Editor restart after the C++ change.
- UE `SizeBox` dimensions are applied through `set_width_override()` / `set_height_override()` and cleared through `clear_*_override()`. Directly setting `width_override` / `height_override` updates only the stored number and does not enable the layout override flag.
- Axis Mapping scale `SpinBox` controls set `EnableSlider=false` so click-release reliably enters text edit mode instead of treating small horizontal mouse motion as slider drag.
- `rebuild_from_spec(recreate=True)` deletes and regenerates the production Blueprint asset. Use this after structural spec changes so UE cannot silently reuse stale widget-tree branches.

## UE Build Command

```python
from post_render_tool import build_widget_blueprint
build_widget_blueprint.run_build(
    spec_path="/Users/bip.lan/AIWorkspace/vp/post_render_tool/docs/widget-tree-spec.json",
    create_if_missing=True,
    force_reapply=True,
)
```

Convenience path:

```python
from post_render_tool.widget_builder import rebuild_from_spec
rebuild_from_spec(force_reapply=True)
```

After structural spec changes, recreate the production widget:

```python
from post_render_tool.widget_builder import rebuild_from_spec
rebuild_from_spec(force_reapply=True, recreate=True)
```
