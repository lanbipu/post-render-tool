# Figma Widget V2 Notes

## Asset Boundary

- Legacy widget asset remains `/PostRenderTool/Blueprints/BP_PostRenderToolWidget`.
- Figma implementation targets `/PostRenderTool/Blueprints/BP_PostRenderToolWidget_Figma`.
- Spec file: `docs/widget-tree-spec-figma-v2.json`.

## UE UMG Workarounds

- Figma border radius is approximated with UMG `Border` / `Button` styling; generated spec does not binary-edit `.uasset` files.
- The orange section accent is represented by a 3x13 `Image` inside a `SizeBox`; UMG `Image` does not expose the Figma 1px corner radius directly.
- Figma dot SVG assets are represented by tinted `Image` widgets, avoiding short-lived remote asset URLs.
- Figma's CSS borders are approximated by darker `Border` backgrounds and inner dividers because the current JSON property applicator does not set full `FSlateBrush` border margins.
- The Figma-only Coordinate Verification controls are Blueprint variables in the new widget. They are not added to the legacy required `BindWidget` contract.
- Solid-color `Border`, `Image`, and `Button` brushes use `/Engine/EngineResources/WhiteSquareTexture` as a tint base. Empty `SlateBrush` resources render as UE's dashed invalid-resource placeholder.
- Figma color values in the JSON spec are sRGB/CSS channels. `widget_properties.py` converts RGB channels to UE `LinearColor` channels before applying them, otherwise the panel renders too gray/bright in the Editor.
- The Figma widget root uses `CanvasPanel` -> `Border` -> `ScrollBox` -> `VerticalBox`. The `CanvasPanel` child is anchored to the full Editor Utility Widget viewport, so the `ScrollBox` gets a real constrained height and the content can stretch horizontally when the tab is wider than the 400px Figma reference.
- UE `SizeBox` dimensions are applied through `set_width_override()` / `set_height_override()` and cleared through `clear_*_override()`. Directly setting `width_override` / `height_override` updates only the stored number and does not enable the layout override flag.
- `rebuild_figma_from_spec(recreate=True)` closes/unregisters the Figma Editor Utility tab before deleting the generated Blueprint asset. Otherwise UE can keep the asset loaded and the builder may silently reuse stale widget-tree branches.

## UE Build Command

```python
from post_render_tool import build_widget_blueprint
build_widget_blueprint.run_build(
    spec_path="/Users/bip.lan/AIWorkspace/vp/post_render_tool/docs/widget-tree-spec-figma-v2.json",
    create_if_missing=True,
    force_reapply=True,
)
```

Convenience path:

```python
from post_render_tool.widget_builder import rebuild_figma_from_spec
rebuild_figma_from_spec(force_reapply=True)
```

After structural spec changes, recreate only the generated Figma widget:

```python
from post_render_tool.widget_builder import rebuild_figma_from_spec
rebuild_figma_from_spec(force_reapply=True, recreate=True)
```
