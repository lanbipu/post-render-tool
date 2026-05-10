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
    "EditorUtilityScrollBox": unreal.EditorUtilityScrollBox,
    "VerticalBox": unreal.VerticalBox,
    "HorizontalBox": unreal.HorizontalBox,
    "Border": unreal.Border,
    "SizeBox": unreal.SizeBox,
    "Button": unreal.Button,
    "ScaleBox": unreal.ScaleBox,
    "ExpandableArea": unreal.ExpandableArea,
    "Image": unreal.Image,
    "TextBlock": unreal.TextBlock,
    "Spacer": unreal.Spacer,
    "SpinBox": unreal.SpinBox,
    "ComboBoxString": unreal.ComboBoxString,
    "MultiLineEditableText": unreal.MultiLineEditableText,
}


def _srgb_channel_to_linear(value: float) -> float:
    """Convert Figma/CSS sRGB channel values to UE LinearColor channels."""
    value = float(value)
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _linear_color(rgba) -> "unreal.LinearColor":
    r, g, b, *rest = list(rgba)
    a = rest[0] if rest else 1.0
    return unreal.LinearColor(
        _srgb_channel_to_linear(r),
        _srgb_channel_to_linear(g),
        _srgb_channel_to_linear(b),
        float(a),
    )


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


def _vec4(values) -> object:
    vals = list(values)
    vals = (vals + [vals[-1] if vals else 0.0] * 4)[:4]
    cls = getattr(unreal, "Vector4", None) or getattr(unreal, "Vector4f", None)
    if cls is not None:
        try:
            return cls(*(float(v) for v in vals))
        except TypeError:
            value = cls()
            for prop, component in zip(("x", "y", "z", "w"), vals):
                value.set_editor_property(prop, float(component))
            return value
    return tuple(float(v) for v in vals)


def _brush_vec2(xy):
    # FSlateBrush.ImageSize is FDeprecateSlateVector2D in UE 5.7. It cannot be
    # constructed from positional args or nativized from Vector2D, but Python can
    # set its x/y editor properties after default construction.
    cls = getattr(unreal, "DeprecateSlateVector2D", None)
    if cls is None:
        return _vec2(xy)
    value = cls()
    value.set_editor_property("x", float(xy[0]))
    value.set_editor_property("y", float(xy[1]))
    return value


def _margin(ltrb) -> "unreal.Margin":
    values = list(ltrb) + [0.0] * (4 - len(ltrb))
    l, t, r, b = values[:4]
    return unreal.Margin(float(l), float(t), float(r), float(b))


_WHITE_TEXTURE = None


def _white_square_texture():
    """Return a real 1x1-ish white texture for tint-only Slate brushes.

    Empty ``FSlateBrush`` resources render as UE's dashed invalid-resource
    placeholder. The Figma spec uses many tint-only rectangles, so bind them to
    Engine's bundled white square texture and tint the brush instead.
    """
    global _WHITE_TEXTURE
    if _WHITE_TEXTURE is not None:
        return _WHITE_TEXTURE

    asset_library = getattr(unreal, "EditorAssetLibrary", None)
    if asset_library is None:
        return None

    for asset_path in (
        "/Engine/EngineResources/WhiteSquareTexture.WhiteSquareTexture",
        "/Engine/EngineResources/WhiteSquareTexture",
    ):
        try:
            texture = asset_library.load_asset(asset_path)
        except Exception:  # noqa: BLE001
            texture = None
        if texture is not None:
            _WHITE_TEXTURE = texture
            return _WHITE_TEXTURE
    return None


def _draw_type(value: str):
    mapping = {
        "Box": unreal.SlateBrushDrawType.BOX,
        "Image": unreal.SlateBrushDrawType.IMAGE,
        "NoDrawType": unreal.SlateBrushDrawType.NO_DRAW_TYPE,
    }
    rounded = getattr(unreal.SlateBrushDrawType, "ROUNDED_BOX", None)
    if rounded is not None:
        mapping["RoundedBox"] = rounded
    return mapping.get(value, unreal.SlateBrushDrawType.IMAGE)


def _rounding_type(value: str):
    enum = getattr(unreal, "SlateBrushRoundingType", None)
    if enum is None:
        return value
    mapping = {
        "FixedRadius": "FIXED_RADIUS",
        "HalfHeightRadius": "HALF_HEIGHT_RADIUS",
    }
    return getattr(enum, mapping.get(str(value), str(value)), value)


def _outline_settings(value: dict):
    outline = unreal.SlateBrushOutlineSettings()
    radius = value.get("CornerRadius", value.get("CornerRadii", 0.0))
    radii = [radius] * 4 if isinstance(radius, (int, float)) else radius
    outline.set_editor_property("corner_radii", _vec4(radii))
    if "Color" in value:
        outline.set_editor_property("color", _slate_color(value["Color"]))
    if "Width" in value:
        outline.set_editor_property("width", float(value["Width"]))
    outline.set_editor_property(
        "rounding_type",
        _rounding_type(value.get("RoundingType", "FixedRadius")),
    )
    outline.set_editor_property(
        "use_brush_transparency",
        bool(value.get("UseBrushTransparency", False)),
    )
    return outline


def _solid_brush(rgba=None, image_size=None, draw_as: str = "Box", outline=None):
    brush = unreal.SlateBrush()
    _configure_brush(
        brush,
        rgba=rgba,
        image_size=image_size,
        draw_as=draw_as,
        outline=outline,
    )
    return brush


def _configure_brush(brush, *, rgba=None, image_size=None, draw_as=None, outline=None):
    texture = _white_square_texture()
    if texture is not None:
        try:
            brush.set_editor_property("resource_object", texture)
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(
                f"[widget_properties] brush resource_object set failed: {exc}"
            )
    if rgba is not None:
        brush.set_editor_property("tint_color", _slate_color(rgba))
    if image_size is not None:
        brush.set_editor_property("image_size", _brush_vec2(image_size))
    if draw_as is not None:
        brush.set_editor_property("draw_as", _draw_type(draw_as))
    if outline is not None:
        if draw_as is None:
            brush.set_editor_property("draw_as", _draw_type("RoundedBox"))
        brush.set_editor_property("outline_settings", _outline_settings(outline))
    return brush


def _get_border_brush(w):
    for prop_name in ("background", "brush"):
        try:
            brush = w.get_editor_property(prop_name)
        except Exception:  # noqa: BLE001
            brush = None
        if brush is not None:
            return brush
    return unreal.SlateBrush()


def _set_border_brush(w, brush) -> bool:
    for prop_name in ("background", "brush"):
        try:
            w.set_editor_property(prop_name, brush)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


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


def _apply_border_brush_color(w, v):
    # UBorder multiplies BrushColor by the Background brush. Use a white texture
    # as the brush resource and put the actual color in BrushColor.
    w.set_editor_property("brush_color", _linear_color(v))
    brush = _solid_brush([1.0, 1.0, 1.0, 1.0], draw_as="Box")
    if not _set_border_brush(w, brush):
        unreal.log_warning(
            f"[widget_properties] could not set solid brush on {type(w).__name__}"
        )


def _apply_textblock_color_and_opacity(w, v):
    # UTextBlock.ColorAndOpacity is FSlateColor, not FLinearColor.
    w.set_editor_property("color_and_opacity", _slate_color(v))


def _apply_image_tint(w, v):
    # FSlateBrush.TintColor is FSlateColor.
    brush = w.get_editor_property("brush") or unreal.SlateBrush()
    _configure_brush(brush, rgba=v, draw_as="Box")
    w.set_editor_property("brush", brush)


def _apply_image_size(w, v):
    brush = w.get_editor_property("brush") or unreal.SlateBrush()
    _configure_brush(brush, image_size=v)
    w.set_editor_property("brush", brush)


def _apply_image_draw_as(w, v):
    brush = w.get_editor_property("brush") or unreal.SlateBrush()
    _configure_brush(brush, draw_as=v)
    w.set_editor_property("brush", brush)


def _apply_button_outline_settings(w, v):
    style = w.get_editor_property("widget_style")
    if style is None:
        return
    for brush_name in ("normal", "hovered", "pressed", "disabled"):
        try:
            brush = style.get_editor_property(brush_name) or unreal.SlateBrush()
            _configure_brush(brush, draw_as="RoundedBox", outline=v)
            style.set_editor_property(brush_name, brush)
        except Exception:  # noqa: BLE001
            continue
    w.set_editor_property("widget_style", style)


def _apply_outline_settings(w, v):
    if isinstance(w, unreal.Button):
        _apply_button_outline_settings(w, v)
        return
    if isinstance(w, unreal.Border):
        brush = _get_border_brush(w)
        _configure_brush(brush, draw_as="RoundedBox", outline=v)
        if not _set_border_brush(w, brush):
            unreal.log_warning(
                f"[widget_properties] could not set outline brush on "
                f"{type(w).__name__}"
            )
        return
    brush = w.get_editor_property("brush") or unreal.SlateBrush()
    _configure_brush(brush, draw_as="RoundedBox", outline=v)
    w.set_editor_property("brush", brush)


def _apply_border_padding(w, v):
    w.set_editor_property("padding", _margin(v))


def _apply_sizebox_width(w, v):
    if hasattr(w, "set_width_override"):
        w.set_width_override(float(v))
    else:
        w.set_editor_property("width_override", float(v))


def _apply_sizebox_height(w, v):
    if hasattr(w, "set_height_override"):
        w.set_height_override(float(v))
    else:
        w.set_editor_property("height_override", float(v))


def _apply_sizebox_clear_width(w, v):
    if bool(v) and hasattr(w, "clear_width_override"):
        w.clear_width_override()


def _apply_sizebox_clear_height(w, v):
    if bool(v) and hasattr(w, "clear_height_override"):
        w.clear_height_override()


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


def _apply_multiline_auto_wrap(w, v):
    w.set_editor_property("auto_wrap_text", bool(v))


def _apply_scrollbox_orientation(w, v):
    # ScrollBox.Orientation is TEnumAsByte<EOrientation>; cannot accept a string.
    mapping = {
        "Vertical": unreal.Orientation.ORIENT_VERTICAL,
        "Horizontal": unreal.Orientation.ORIENT_HORIZONTAL,
    }
    w.set_editor_property(
        "orientation", mapping.get(v, unreal.Orientation.ORIENT_VERTICAL)
    )


def _apply_scrollbox_always_show_scrollbar(w, v):
    w.set_editor_property("always_show_scrollbar", bool(v))


def _apply_scrollbox_always_show_scrollbar_track(w, v):
    w.set_editor_property("always_show_scrollbar_track", bool(v))


def _apply_scrollbar_thickness(w, v):
    w.set_editor_property("scrollbar_thickness", _vec2(v))


def _apply_wheel_scroll_multiplier(w, v):
    w.set_editor_property("wheel_scroll_multiplier", float(v))


def _apply_visibility(w, v):
    mapping = {
        "Visible": "VISIBLE",
        "Collapsed": "COLLAPSED",
        "Hidden": "HIDDEN",
        "HitTestInvisible": "HIT_TEST_INVISIBLE",
        "SelfHitTestInvisible": "SELF_HIT_TEST_INVISIBLE",
    }
    enum_name = mapping.get(str(v), "VISIBLE")
    w.set_editor_property("visibility", getattr(unreal.SlateVisibility, enum_name))


def _apply_spacer_size(w, v):
    w.set_editor_property("size", _vec2(v))


def _apply_expandable_is_expanded(w, v):
    w.set_editor_property("is_expanded", bool(v))


def _apply_expandable_header_padding(w, v):
    w.set_editor_property("header_padding", _margin(v))


def _apply_expandable_area_padding(w, v):
    w.set_editor_property("area_padding", _margin(v))


def _apply_expandable_max_height(w, v):
    w.set_editor_property("max_height", float(v))


# ScaleBox — fixed-design-size pattern: wrap the root panel in ScaleBox + SizeBox
# so the whole tool renders at Figma native dimensions regardless of EUW tab size.
_STRETCH_MAP = {
    "None": "NONE",
    "Fill": "FILL",
    "ScaleToFit": "SCALE_TO_FIT",
    "ScaleToFitX": "SCALE_TO_FIT_X",
    "ScaleToFitY": "SCALE_TO_FIT_Y",
    "ScaleToFill": "SCALE_TO_FILL",
    "UserSpecified": "USER_SPECIFIED",
    "UserSpecifiedWithClipping": "USER_SPECIFIED_WITH_CLIPPING",
}
_STRETCH_DIRECTION_MAP = {
    "Both": "BOTH",
    "DownOnly": "DOWN_ONLY",
    "UpOnly": "UP_ONLY",
}


def _apply_scalebox_stretch(w, v):
    attr = _STRETCH_MAP.get(v, "SCALE_TO_FIT")
    enum_val = getattr(unreal.Stretch, attr)
    w.set_editor_property("stretch", enum_val)


def _apply_scalebox_stretch_direction(w, v):
    attr = _STRETCH_DIRECTION_MAP.get(v, "BOTH")
    enum_val = getattr(unreal.StretchDirection, attr)
    w.set_editor_property("stretch_direction", enum_val)


def _apply_scalebox_user_scale(w, v):
    w.set_editor_property("user_specified_scale", float(v))


def _apply_textblock_font(w, v):
    """Mutate a widget's FSlateFontInfo in place when it exposes ``font``.

    v is {"size": int, "type_face": "Regular"|"Bold"|"Light"|"Mono"|...}.
    Unknown type_face falls through to whatever the default font provides.
    """
    try:
        font = w.get_editor_property("font")
    except Exception:  # noqa: BLE001
        font = None
    if font is None:
        return
    if "size" in v:
        font.set_editor_property("size", int(v["size"]))
    if "type_face" in v:
        font.set_editor_property(
            "typeface_font_name", unreal.Name(str(v["type_face"]))
        )
    w.set_editor_property("font", font)


def _apply_foreground_color(w, v):
    w.set_editor_property("foreground_color", _slate_color(v))


def _apply_min_desired_width(w, v):
    for prop_name in ("min_desired_width", "minimum_desired_width"):
        try:
            w.set_editor_property(prop_name, float(v))
            return
        except Exception:  # noqa: BLE001
            continue


def _apply_content_padding(w, v):
    w.set_editor_property("content_padding", _margin(v))


def _apply_has_down_arrow(w, v):
    w.set_editor_property("has_down_arrow", bool(v))


def _set_text_style(style, *, color=None, font=None):
    if color is not None:
        style.set_editor_property("color_and_opacity", _slate_color(color))
    if font:
        try:
            font_info = style.get_editor_property("font")
            if "size" in font:
                font_info.set_editor_property("size", int(font["size"]))
            if "type_face" in font:
                font_info.set_editor_property(
                    "typeface_font_name", unreal.Name(str(font["type_face"]))
                )
            style.set_editor_property("font", font_info)
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(f"[widget_properties] text style font failed: {exc}")


def _apply_text_style(w, v):
    style = w.get_editor_property("widget_style")
    if style is None:
        return
    _set_text_style(style, color=v.get("Color"), font=v.get("Font"))
    w.set_editor_property("widget_style", style)


def _style_spinbox(w, v):
    style = w.get_editor_property("widget_style")
    if style is None:
        return
    bg = v.get("BackgroundColor", [0.102, 0.102, 0.102, 1.0])
    hover = v.get("HoverColor", bg)
    active = v.get("ActiveColor", bg)
    fill = v.get("FillColor", [0.18, 0.18, 0.18, 1.0])
    outline = v.get("OutlineSettings")
    draw_as = "RoundedBox" if outline else "Box"
    for name, color in (
        ("background_brush", bg),
        ("hovered_background_brush", hover),
        ("active_background_brush", active),
        ("inactive_fill_brush", bg),
        ("hovered_fill_brush", fill),
        ("active_fill_brush", fill),
    ):
        try:
            style.set_editor_property(
                name,
                _solid_brush(color, draw_as=draw_as, outline=outline),
            )
        except Exception:  # noqa: BLE001
            continue
    try:
        style.set_editor_property(
            "arrows_image", _solid_brush([0.0, 0.0, 0.0, 0.0], draw_as="NoDrawType")
        )
    except Exception:  # noqa: BLE001
        pass
    if "TextPadding" in v:
        try:
            style.set_editor_property("text_padding", _margin(v["TextPadding"]))
        except Exception:  # noqa: BLE001
            pass
    if "InsetPadding" in v:
        try:
            style.set_editor_property("inset_padding", _margin(v["InsetPadding"]))
        except Exception:  # noqa: BLE001
            pass
    w.set_editor_property("widget_style", style)
    if "TextColor" in v:
        _apply_foreground_color(w, v["TextColor"])


def _style_combobox(w, v):
    style = w.get_editor_property("widget_style")
    if style is None:
        return
    bg = v.get("BackgroundColor", [0.102, 0.102, 0.102, 1.0])
    hover = v.get("HoverColor", bg)
    pressed = v.get("PressedColor", bg)
    outline = v.get("OutlineSettings")
    draw_as = "RoundedBox" if outline else "Box"
    try:
        combo_button_style = style.get_editor_property("combo_button_style")
        button_style = combo_button_style.get_editor_property("button_style")
        for name, color in (
            ("normal", bg),
            ("hovered", hover),
            ("pressed", pressed),
            ("disabled", bg),
        ):
            button_style.set_editor_property(
                name, _solid_brush(color, draw_as=draw_as, outline=outline)
            )
        combo_button_style.set_editor_property("button_style", button_style)
        if "ContentPadding" in v:
            combo_button_style.set_editor_property(
                "content_padding", _margin(v["ContentPadding"])
            )
        style.set_editor_property("combo_button_style", combo_button_style)
    except Exception as exc:  # noqa: BLE001
        unreal.log_warning(f"[widget_properties] ComboBoxString style failed: {exc}")
    try:
        style.set_editor_property(
            "menu_border_brush", _solid_brush(bg, draw_as=draw_as, outline=outline)
        )
    except Exception:  # noqa: BLE001
        pass
    w.set_editor_property("widget_style", style)
    if "TextColor" in v:
        _apply_foreground_color(w, v["TextColor"])
    if "Font" in v:
        _apply_textblock_font(w, v["Font"])
    if "ContentPadding" in v:
        _apply_content_padding(w, v["ContentPadding"])
    if "HasDownArrow" in v:
        _apply_has_down_arrow(w, v["HasDownArrow"])


def _apply_figma_input_style(w, v):
    if isinstance(w, unreal.SpinBox):
        _style_spinbox(w, v)
    elif isinstance(w, unreal.ComboBoxString):
        _style_combobox(w, v)
    else:
        if "TextColor" in v:
            _apply_foreground_color(w, v["TextColor"])


def _apply_button_background_color(w, v):
    """Tint FButtonStyle's Normal/Hovered/Pressed brushes.

    UE Button has no direct `background_color` property — its fill comes from
    `WidgetStyle: FButtonStyle` which holds three FSlateBrush states (Normal,
    Hovered, Pressed, Disabled). Each state receives a real white texture
    resource so UE does not render an invalid-resource dashed placeholder.
    """
    style = w.get_editor_property("widget_style")
    if style is None:
        return
    for brush_name in ("normal", "hovered", "pressed", "disabled"):
        try:
            style.set_editor_property(brush_name, _solid_brush(v, draw_as="Box"))
        except Exception:  # noqa: BLE001
            continue
    w.set_editor_property("widget_style", style)


def _apply_background_color(w, v):
    """Dispatch BackgroundColor — Buttons tint widget_style, others set prop directly."""
    if isinstance(w, unreal.Button):
        _apply_button_background_color(w, v)
    else:
        w.set_editor_property("background_color", _linear_color(v))


_PROPERTY_APPLICATORS: Dict[str, Callable[[Any, Any], None]] = {
    "Text": _apply_textblock_text,
    "BrushColor": _apply_border_brush_color,
    "ColorAndOpacity": _apply_textblock_color_and_opacity,
    "BackgroundColor": _apply_background_color,
    "Tint": _apply_image_tint,
    "ImageSize": _apply_image_size,
    "DrawAs": _apply_image_draw_as,
    "OutlineSettings": _apply_outline_settings,
    "Padding": _apply_border_padding,
    "WidthOverride": _apply_sizebox_width,
    "HeightOverride": _apply_sizebox_height,
    "ClearWidthOverride": _apply_sizebox_clear_width,
    "ClearHeightOverride": _apply_sizebox_clear_height,
    "MinValue": _apply_spinbox_min,
    "MaxValue": _apply_spinbox_max,
    "Value": _apply_spinbox_value,
    "MinFractionalDigits": _apply_spinbox_fractional,
    "DefaultOptions": _apply_combo_default_options,
    "IsReadOnly": _apply_multiline_readonly,
    "HintText": _apply_multiline_hint,
    "AutoWrapText": _apply_multiline_auto_wrap,
    "Orientation": _apply_scrollbox_orientation,
    "AlwaysShowScrollbar": _apply_scrollbox_always_show_scrollbar,
    "AlwaysShowScrollbarTrack": _apply_scrollbox_always_show_scrollbar_track,
    "ScrollbarThickness": _apply_scrollbar_thickness,
    "WheelScrollMultiplier": _apply_wheel_scroll_multiplier,
    "Visibility": _apply_visibility,
    "Size": _apply_spacer_size,
    "Font": _apply_textblock_font,
    "ForegroundColor": _apply_foreground_color,
    "MinDesiredWidth": _apply_min_desired_width,
    "ContentPadding": _apply_content_padding,
    "HasDownArrow": _apply_has_down_arrow,
    "TextStyle": _apply_text_style,
    "FigmaInputStyle": _apply_figma_input_style,
    "IsExpanded": _apply_expandable_is_expanded,
    "HeaderPadding": _apply_expandable_header_padding,
    "AreaPadding": _apply_expandable_area_padding,
    "MaxHeight": _apply_expandable_max_height,
    "Stretch": _apply_scalebox_stretch,
    "StretchDirection": _apply_scalebox_stretch_direction,
    "UserSpecifiedScale": _apply_scalebox_user_scale,
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

    if "h_align" in props and _slot_has(slot, "horizontal_alignment"):
        _try_set(slot, "horizontal_alignment", _resolve_h_align(props["h_align"]))

    if "v_align" in props and _slot_has(slot, "vertical_alignment"):
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
    if ("anchors_min" in props or "anchors_max" in props) and hasattr(slot, "set_anchors"):
        try:
            anchors = unreal.Anchors(
                _vec2(props.get("anchors_min", [0, 0])),
                _vec2(props.get("anchors_max", [1, 1])),
            )
            slot.set_anchors(anchors)
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(f"[widget_properties] anchors set failed: {exc}")

    if "offsets" in props:
        if hasattr(slot, "set_offsets"):
            try:
                slot.set_offsets(_margin(props["offsets"]))
            except Exception as exc:  # noqa: BLE001
                unreal.log_warning(f"[widget_properties] offsets set failed: {exc}")
        else:
            _try_set(slot, "offsets", _margin(props["offsets"]))

    if "z_order" in props:
        if hasattr(slot, "set_z_order"):
            try:
                slot.set_z_order(int(props["z_order"]))
            except Exception as exc:  # noqa: BLE001
                unreal.log_warning(f"[widget_properties] z_order set failed: {exc}")
        else:
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
