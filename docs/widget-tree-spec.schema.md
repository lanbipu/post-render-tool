# Widget Tree Spec Schema

Authoritative schema for `docs/widget-tree-spec.json`, consumed by `Content/Python/post_render_tool/build_widget_blueprint.py`.

## Top-level structure

```json
{
  "blueprint": {
    "asset_path": "/PostRenderTool/Blueprints/BP_PostRenderToolWidget",
    "parent_class": "/Script/PostRenderTool.PostRenderToolWidget",
    "root_panel": { "type": "VerticalBox", "name": "RootPanel" }
  },
  "root_children": [ { /* WidgetNode */ } ]
}
```

- `blueprint.asset_path` — plugin-mounted `/PostRenderTool/...` path.
- `blueprint.parent_class` — must be `UPostRenderToolWidget` (Python-side hardcoded).
- `blueprint.root_panel` — if the BP's WidgetTree root is empty, the builder creates this root; if the root already exists with any `PanelWidget` type, the builder keeps it unchanged.
- `root_children` — WidgetNode array appended into the root panel.

## WidgetNode

```json
{
  "type": "<WidgetType>",
  "name": "<widget_name>",
  "role": "required" | "optional" | "decorative",
  "properties": { /* optional per-type */ },
  "slot": { /* optional per-parent-type */ },
  "children": [ /* optional, WidgetNode[] */ ]
}
```

Field rules:
- `type` — case-sensitive, must match a key in `widget_properties.WIDGET_CLASS_MAP`.
- `name` — must be unique across the whole spec. Contract widgets must use the exact name declared in `PostRenderToolWidget.h`. Decorative widgets should start with `lbl_` prefix.
- `role`:
  - `required` — `UPROPERTY(meta=(BindWidget))`; widget constructor defaults `bIsVariable=true` (satisfies BindWidget reflection).
  - `optional` — `UPROPERTY(meta=(BindWidgetOptional))`; same default.
  - `decorative` — not in contract; inherits `bIsVariable=true` default (cannot suppress from business module — `Widget.h:318` private bitfield, see plan Architecture notes). Harmless overhead on generated class.
- `children` — only allowed when `type` is a PanelWidget or ContentWidget (see supported types).

## Supported widget types

| Type | Category | Child capacity | Common props |
|---|---|---|---|
| `CanvasPanel` | Panel | many | — |
| `ScrollBox` | Panel | many | `Orientation` |
| `VerticalBox` | Panel | many | — |
| `HorizontalBox` | Panel | many | — |
| `Border` | Content | 1 | `BrushColor`, `Padding` |
| `SizeBox` | Content | 1 | `WidthOverride`, `HeightOverride` |
| `Button` | Content | 1 | `BackgroundColor` |
| `Image` | Leaf | 0 | `Tint`, `ImageSize`, `DrawAs` |
| `TextBlock` | Leaf | 0 | `Text`, `FontSize`, `ColorAndOpacity` |
| `Spacer` | Leaf | 0 | `Size` |
| `SpinBox` | Leaf | 0 | `MinValue`, `MaxValue`, `Value`, `MinFractionalDigits` |
| `ComboBoxString` | Leaf | 0 | `DefaultOptions` |
| `MultiLineEditableText` | Leaf | 0 | `Text`, `IsReadOnly`, `HintText` |

## Property value formats

| Property | JSON type | Example | Unreal type |
|---|---|---|---|
| `Text` | string | `"Browse..."` | `FText` |
| `BrushColor` / `Tint` / `ColorAndOpacity` | `[r,g,b,a]` 0.0–1.0 | `[0.909, 0.439, 0.302, 1.0]` | `FLinearColor` |
| `ImageSize` / `Size` | `[x,y]` | `[3, 13]` | `FVector2D` |
| `Padding` | `[l,t,r,b]` | `[12, 10, 12, 10]` | `FMargin` |
| `WidthOverride` / `HeightOverride` | number | `3` | `float` |
| `MinValue` / `MaxValue` / `Value` | number | `0.0` | `float` |
| `IsReadOnly` | bool | `true` | `bool` |
| `FontSize` | number | `11` | `int32` |
| `DrawAs` | string | `"Box"` | `ESlateBrushDrawType` (`"Box"` / `"Image"` / `"NoDrawType"`) |
| `DefaultOptions` | `string[]` | `["X (0)","Y (1)","Z (2)"]` | `TArray<FString>` |
| `Orientation` | string | `"Vertical"` | `"Vertical"` / `"Horizontal"` |
| `HintText` | string | `""` | `FText` |

## Slot property formats

Keyed by parent widget type. Builder looks up the parent's actual `UPanelSlot` subclass at runtime.

| Parent type | Slot props |
|---|---|
| `CanvasPanel` | `anchors_min` `[x,y]`, `anchors_max` `[x,y]`, `offsets` `[l,t,r,b]`, `alignment` `[x,y]`, `z_order` int |
| `VerticalBox` / `HorizontalBox` | `size_rule` (`"Auto"`/`"Fill"`), `fill_size` number, `padding` `[l,t,r,b]`, `h_align` (`"Left"`/`"Center"`/`"Right"`/`"Fill"`), `v_align` same |
| `ScrollBox` | `padding`, `h_align`, `size_rule`, `fill_size` |
| `Border` | `padding` (as widget prop, not slot), `h_align`, `v_align` |
| `SizeBox` | `h_align`, `v_align` |
| `Button` | `padding`, `h_align`, `v_align` |

Unknown slot keys trigger a builder warning but do not abort.

## Example — Section 2 "CSV File" fragment

```json
{
  "type": "Border", "name": "lbl_card_csv_file", "role": "decorative",
  "properties": { "BrushColor": [0.141, 0.141, 0.141, 1.0], "Padding": [12, 10, 12, 10] },
  "slot": { "padding": [0, 0, 0, 8] },
  "children": [
    {
      "type": "VerticalBox", "name": "lbl_csv_file_vbox", "role": "decorative",
      "children": [
        {
          "type": "HorizontalBox", "name": "lbl_csv_file_row", "role": "decorative",
          "slot": { "padding": [0, 8, 0, 0] },
          "children": [
            {
              "type": "Button", "name": "btn_browse", "role": "required",
              "children": [
                { "type": "TextBlock", "name": "lbl_btn_browse_text", "role": "decorative",
                  "properties": { "Text": "Browse..." },
                  "slot": { "padding": [14, 6, 14, 6] } }
              ]
            },
            {
              "type": "TextBlock", "name": "txt_file_path", "role": "required",
              "properties": { "Text": "" },
              "slot": { "padding": [10, 6, 0, 6], "fill_size": 1.0, "size_rule": "Fill" }
            }
          ]
        }
      ]
    }
  ]
}
```
