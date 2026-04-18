"""Apply JSON-spec'd properties onto unreal widget / slot objects.

Requires `unreal` (runs inside UE Editor). Pure property-setter dispatch — no
widget tree mutation here; see PostRenderToolBuildHelper (C++) for that.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

import unreal


WIDGET_CLASS_MAP: Dict[str, type] = {
    "CanvasPanel": unreal.CanvasPanel,
    "ScrollBox": unreal.ScrollBox,
    "VerticalBox": unreal.VerticalBox,
    "HorizontalBox": unreal.HorizontalBox,
    "Border": unreal.Border,
    "SizeBox": unreal.SizeBox,
    "Button": unreal.Button,
    "Image": unreal.Image,
    "TextBlock": unreal.TextBlock,
    "Spacer": unreal.Spacer,
    "SpinBox": unreal.SpinBox,
    "ComboBoxString": unreal.ComboBoxString,
    "MultiLineEditableText": unreal.MultiLineEditableText,
}


def _linear_color(rgba) -> "unreal.LinearColor":
    r, g, b, *rest = list(rgba)
    a = rest[0] if rest else 1.0
    return unreal.LinearColor(r, g, b, a)


def _slate_color(rgba) -> "unreal.SlateColor":
    """Build an FSlateColor from an RGBA list/tuple.

    FSlateBrush.TintColor and UTextBlock.ColorAndOpacity are both FSlateColor,
    NOT FLinearColor. Passing a LinearColor directly triggers a Python TypeError
    at set_editor_property time. The safe construction path is:

        sc = unreal.SlateColor()
        sc.set_editor_property("specified_color", linear)

    This works even when the positional ctor `unreal.SlateColor(linear)` is
    missing from a given UE Python binding.
    """
    sc = unreal.SlateColor()
    sc.set_editor_property("specified_color", _linear_color(rgba))
    return sc


def _vec2(xy) -> "unreal.Vector2D":
    # FDeprecateSlateVector2D is exposed to Python as Vector2D (see UE 5.7
    # SlateVector2.h:123 USTRUCT(DisplayName="Vector2D"))
    return unreal.Vector2D(float(xy[0]), float(xy[1]))


def _margin(ltrb) -> "unreal.Margin":
    values = list(ltrb) + [0.0] * (4 - len(ltrb))
    l, t, r, b = values[:4]
    return unreal.Margin(float(l), float(t), float(r), float(b))


# ---------------------------------------------------------------------------
# Per-property applicators
# Key = property name in spec JSON, value = callable(widget, value).
# ---------------------------------------------------------------------------

def _apply_textblock_text(w, v):
    if hasattr(w, "set_text"):
        w.set_text(unreal.Text(str(v)))
    else:
        w.set_editor_property("text", unreal.Text(str(v)))


def _apply_color_prop(prop_name: str):
    def _apply(w, v):
        w.set_editor_property(prop_name, _linear_color(v))
    return _apply


def _apply_textblock_color_and_opacity(w, v):
    # UTextBlock.ColorAndOpacity is FSlateColor, not FLinearColor.
    w.set_editor_property("color_and_opacity", _slate_color(v))


def _apply_image_tint(w, v):
    # FSlateBrush.TintColor is FSlateColor.
    brush = w.get_editor_property("brush") or unreal.SlateBrush()
    brush.set_editor_property("tint_color", _slate_color(v))
    w.set_editor_property("brush", brush)


def _apply_image_size(w, v):
    brush = w.get_editor_property("brush") or unreal.SlateBrush()
    brush.set_editor_property("image_size", _vec2(v))
    w.set_editor_property("brush", brush)


def _apply_image_draw_as(w, v):
    brush = w.get_editor_property("brush") or unreal.SlateBrush()
    mapping = {
        "Box": unreal.SlateBrushDrawType.BOX,
        "Image": unreal.SlateBrushDrawType.IMAGE,
        "NoDrawType": unreal.SlateBrushDrawType.NO_DRAW_TYPE,
    }
    brush.set_editor_property("draw_as", mapping.get(v, unreal.SlateBrushDrawType.IMAGE))
    w.set_editor_property("brush", brush)


def _apply_border_padding(w, v):
    w.set_editor_property("padding", _margin(v))


def _apply_sizebox_width(w, v):
    w.set_editor_property("width_override", float(v))


def _apply_sizebox_height(w, v):
    w.set_editor_property("height_override", float(v))


def _apply_spinbox_min(w, v):
    w.set_editor_property("min_value", float(v))


def _apply_spinbox_max(w, v):
    w.set_editor_property("max_value", float(v))


def _apply_spinbox_value(w, v):
    w.set_editor_property("value", float(v))


def _apply_spinbox_fractional(w, v):
    w.set_editor_property("min_fractional_digits", int(v))


def _apply_combo_default_options(w, v):
    for opt in v:
        w.add_option(str(opt))


def _apply_multiline_text(w, v):
    w.set_editor_property("text", unreal.Text(str(v)))


def _apply_multiline_readonly(w, v):
    w.set_editor_property("is_read_only", bool(v))


def _apply_multiline_hint(w, v):
    w.set_editor_property("hint_text", unreal.Text(str(v)))


def _apply_scrollbox_orientation(w, v):
    # ScrollBox.Orientation is TEnumAsByte<EOrientation>; cannot accept a string.
    mapping = {
        "Vertical": unreal.Orientation.ORIENT_VERTICAL,
        "Horizontal": unreal.Orientation.ORIENT_HORIZONTAL,
    }
    w.set_editor_property(
        "orientation", mapping.get(v, unreal.Orientation.ORIENT_VERTICAL)
    )


def _apply_spacer_size(w, v):
    w.set_editor_property("size", _vec2(v))


def _apply_textblock_font(w, v):
    """Mutate the TextBlock's FSlateFontInfo in place.

    v is {"size": int, "type_face": "Regular"|"Bold"|"Light"|"Mono"|...}.
    Unknown type_face falls through to whatever the default font provides.
    """
    font = w.get_editor_property("font")
    if font is None:
        return
    if "size" in v:
        font.set_editor_property("size", int(v["size"]))
    if "type_face" in v:
        font.set_editor_property(
            "typeface_font_name", unreal.Name(str(v["type_face"]))
        )
    w.set_editor_property("font", font)


def _apply_button_background_color(w, v):
    """Tint FButtonStyle's Normal/Hovered/Pressed brushes.

    UE Button has no direct `background_color` property — its fill comes from
    `WidgetStyle: FButtonStyle` which holds three FSlateBrush states (Normal,
    Hovered, Pressed, Disabled). Tinting them all keeps the rounded-corner
    default button texture but recolors it.
    """
    slate = _slate_color(v)
    style = w.get_editor_property("widget_style")
    if style is None:
        return
    for brush_name in ("normal", "hovered", "pressed"):
        brush = style.get_editor_property(brush_name)
        if brush is None:
            continue
        brush.set_editor_property("tint_color", slate)
        style.set_editor_property(brush_name, brush)
    w.set_editor_property("widget_style", style)


def _apply_background_color(w, v):
    """Dispatch BackgroundColor — Buttons tint widget_style, others set prop directly."""
    if isinstance(w, unreal.Button):
        _apply_button_background_color(w, v)
    else:
        w.set_editor_property("background_color", _linear_color(v))


_PROPERTY_APPLICATORS: Dict[str, Callable[[Any, Any], None]] = {
    "Text": _apply_textblock_text,
    "BrushColor": _apply_color_prop("brush_color"),
    "ColorAndOpacity": _apply_textblock_color_and_opacity,
    "BackgroundColor": _apply_background_color,
    "Tint": _apply_image_tint,
    "ImageSize": _apply_image_size,
    "DrawAs": _apply_image_draw_as,
    "Padding": _apply_border_padding,
    "WidthOverride": _apply_sizebox_width,
    "HeightOverride": _apply_sizebox_height,
    "MinValue": _apply_spinbox_min,
    "MaxValue": _apply_spinbox_max,
    "Value": _apply_spinbox_value,
    "MinFractionalDigits": _apply_spinbox_fractional,
    "DefaultOptions": _apply_combo_default_options,
    "IsReadOnly": _apply_multiline_readonly,
    "HintText": _apply_multiline_hint,
    "Orientation": _apply_scrollbox_orientation,
    "Size": _apply_spacer_size,
    "Font": _apply_textblock_font,
}


def apply_widget_properties(widget, props: Dict[str, Any]) -> None:
    """Apply JSON-spec properties onto a live unreal widget instance.

    Unknown properties are logged and skipped — never raise.
    """
    # MultiLineEditableText has no set_text() — route Text via set_editor_property.
    if isinstance(widget, unreal.MultiLineEditableText) and "Text" in props:
        _apply_multiline_text(widget, props["Text"])
        props = {k: v for k, v in props.items() if k != "Text"}

    for key, value in props.items():
        applicator = _PROPERTY_APPLICATORS.get(key)
        if applicator is None:
            unreal.log_warning(
                f"[widget_properties] unknown property {key!r} on "
                f"{type(widget).__name__}; skipped"
            )
            continue
        try:
            applicator(widget, value)
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(
                f"[widget_properties] failed to apply {key}={value!r} on "
                f"{type(widget).__name__}: {exc}"
            )


# ---------------------------------------------------------------------------
# Slot applicators — any UPanelSlot subclass; reflect via set_editor_property.
# ---------------------------------------------------------------------------

_H_ALIGN_MAP = {
    "Left": "H_ALIGN_LEFT",
    "Center": "H_ALIGN_CENTER",
    "Right": "H_ALIGN_RIGHT",
    "Fill": "H_ALIGN_FILL",
}
_V_ALIGN_MAP = {
    "Top": "V_ALIGN_TOP",
    "Center": "V_ALIGN_CENTER",
    "Bottom": "V_ALIGN_BOTTOM",
    "Fill": "V_ALIGN_FILL",
}


def _resolve_h_align(key: str):
    attr = _H_ALIGN_MAP.get(key, "H_ALIGN_FILL")
    return getattr(unreal.HorizontalAlignment, attr)


def _resolve_v_align(key: str):
    attr = _V_ALIGN_MAP.get(key, "V_ALIGN_FILL")
    return getattr(unreal.VerticalAlignment, attr)


def apply_slot_properties(slot, props: Dict[str, Any]) -> None:
    """Apply slot-layout properties onto a UPanelSlot instance.

    Silently skips properties the specific slot type doesn't expose.
    """
    if slot is None:
        return

    if "padding" in props:
        _try_set(slot, "padding", _margin(props["padding"]))

    if "h_align" in props:
        _try_set(slot, "horizontal_alignment", _resolve_h_align(props["h_align"]))

    if "v_align" in props:
        _try_set(slot, "vertical_alignment", _resolve_v_align(props["v_align"]))

    if "fill_size" in props or "size_rule" in props:
        size = slot.get_editor_property("size") if _slot_has(slot, "size") else None
        if size is not None:
            if "fill_size" in props:
                try:
                    size.set_editor_property("value", float(props["fill_size"]))
                except Exception as exc:  # noqa: BLE001
                    unreal.log_warning(
                        f"[widget_properties] fill_size set failed: {exc}"
                    )
            if "size_rule" in props:
                rule_str = props["size_rule"]
                enum_value = (
                    unreal.SlateSizeRule.AUTOMATIC
                    if rule_str == "Auto"
                    else unreal.SlateSizeRule.FILL
                )
                try:
                    size.set_editor_property("size_rule", enum_value)
                except Exception as exc:  # noqa: BLE001
                    unreal.log_warning(
                        f"[widget_properties] size_rule set failed: {exc}"
                    )
            _try_set(slot, "size", size)

    # CanvasPanelSlot-specific
    if "anchors_min" in props or "anchors_max" in props:
        try:
            anchors = unreal.Anchors(
                props.get("anchors_min", [0, 0]),
                props.get("anchors_max", [1, 1]),
            )
            _try_set(slot, "anchors", anchors)
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(f"[widget_properties] anchors set failed: {exc}")

    if "offsets" in props:
        _try_set(slot, "offsets", _margin(props["offsets"]))

    if "z_order" in props:
        _try_set(slot, "z_order", int(props["z_order"]))


def _slot_has(slot, key: str) -> bool:
    try:
        slot.get_editor_property(key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _try_set(obj, key: str, value) -> None:
    try:
        obj.set_editor_property(key, value)
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(
            f"[widget_properties] set_editor_property({key!r}, ...) failed on "
            f"{type(obj).__name__}: {exc}"
        )
