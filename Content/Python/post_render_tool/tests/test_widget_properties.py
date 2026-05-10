"""Pure-Python tests for widget_properties.py using recorded-call stubs.

Injects a minimal `unreal` stub module before importing widget_properties so
the module can be exercised outside UE Editor.
"""

from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Tuple

# ----- unreal stub ---------------------------------------------------------

_unreal_stub = types.ModuleType("unreal")


@dataclass
class _Recorder:
    calls: List[Tuple[str, Tuple[Any, ...]]] = field(default_factory=list)

    def record(self, name: str, *args: Any) -> Any:
        self.calls.append((name, args))
        return None


_R = _Recorder()


class _StubText:
    def __init__(self, s: str) -> None:
        self.s = s
    def to_string(self) -> str:
        return self.s
    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"Text({self.s!r})"


class _StubLinearColor:
    def __init__(self, r: float, g: float, b: float, a: float = 1.0) -> None:
        self.rgba = (r, g, b, a)


class _StubVector2D:
    def __init__(self, x: float, y: float) -> None:
        self.xy = (x, y)


class _StubMargin:
    def __init__(self, l: float, t: float, r: float, b: float) -> None:
        self.ltrb = (l, t, r, b)


class _StubSlateBrush:
    def __init__(self) -> None:
        self.props = {}
    def set_editor_property(self, name: str, value: Any) -> None:
        self.props[name] = value
    def get_editor_property(self, name: str) -> Any:
        return self.props.get(name)


class _StubSlateColor:
    def __init__(self) -> None:
        self.props = {}
    def set_editor_property(self, name: str, value: Any) -> None:
        self.props[name] = value
    def get_editor_property(self, name: str) -> Any:
        return self.props.get(name)


class _StubFontInfo:
    def __init__(self) -> None:
        self.props = {"size": 24}
    def set_editor_property(self, name: str, value: Any) -> None:
        self.props[name] = value
    def get_editor_property(self, name: str) -> Any:
        return self.props.get(name)


class _StubButtonStyle:
    def __init__(self) -> None:
        self.props = {
            "normal": _StubSlateBrush(),
            "hovered": _StubSlateBrush(),
            "pressed": _StubSlateBrush(),
        }
    def set_editor_property(self, name: str, value: Any) -> None:
        self.props[name] = value
    def get_editor_property(self, name: str) -> Any:
        return self.props.get(name)


class _StubWidgetBase:
    widget_type = "Widget"

    def __init__(self) -> None:
        self.properties: dict = {}

    def set_editor_property(self, name: str, value: Any) -> None:
        self.properties[name] = value
        _R.record(f"{type(self).__name__}.set_editor_property", name, value)

    def get_editor_property(self, name: str) -> Any:
        return self.properties.get(name)


class _StubTextBlock(_StubWidgetBase):
    def set_text(self, t: _StubText) -> None:
        self.properties["Text"] = t
        _R.record("TextBlock.set_text", t.to_string())


class _StubComboBoxString(_StubWidgetBase):
    def add_option(self, o: str) -> None:
        self.properties.setdefault("options", []).append(o)
        _R.record("ComboBoxString.add_option", o)


class _StubSizeBox(_StubWidgetBase):
    def set_width_override(self, value: float) -> None:
        self.properties["width_override"] = value
        self.properties["width_override_enabled"] = True
        _R.record("SizeBox.set_width_override", value)

    def set_height_override(self, value: float) -> None:
        self.properties["height_override"] = value
        self.properties["height_override_enabled"] = True
        _R.record("SizeBox.set_height_override", value)

    def clear_width_override(self) -> None:
        self.properties["width_override_cleared"] = True
        _R.record("SizeBox.clear_width_override")

    def clear_height_override(self) -> None:
        self.properties["height_override_cleared"] = True
        _R.record("SizeBox.clear_height_override")


_unreal_stub.Text = _StubText
_unreal_stub.LinearColor = _StubLinearColor
_unreal_stub.Vector2D = _StubVector2D
_unreal_stub.Margin = _StubMargin
_unreal_stub.SlateBrush = _StubSlateBrush
_unreal_stub.SlateColor = _StubSlateColor
_unreal_stub.Name = lambda s: s  # FName stub — pass-through string
_unreal_stub.Anchors = lambda minimum, maximum: (minimum, maximum)

_unreal_stub.TextBlock = _StubTextBlock
_unreal_stub.ComboBoxString = _StubComboBoxString
_unreal_stub.Button = type("Button", (_StubWidgetBase,), {})
_unreal_stub.Image = type("Image", (_StubWidgetBase,), {})
_unreal_stub.Border = type("Border", (_StubWidgetBase,), {})
_unreal_stub.SizeBox = _StubSizeBox
_unreal_stub.SpinBox = type("SpinBox", (_StubWidgetBase,), {})
_unreal_stub.MultiLineEditableText = type("MultiLineEditableText", (_StubWidgetBase,), {})
_unreal_stub.Spacer = type("Spacer", (_StubWidgetBase,), {})
_unreal_stub.VerticalBox = type("VerticalBox", (_StubWidgetBase,), {})
_unreal_stub.HorizontalBox = type("HorizontalBox", (_StubWidgetBase,), {})
_unreal_stub.ScrollBox = type("ScrollBox", (_StubWidgetBase,), {})
_unreal_stub.EditorUtilityScrollBox = type(
    "EditorUtilityScrollBox", (_StubWidgetBase,), {}
)
_unreal_stub.CanvasPanel = type("CanvasPanel", (_StubWidgetBase,), {})
_unreal_stub.ExpandableArea = type("ExpandableArea", (_StubWidgetBase,), {})
_unreal_stub.ScaleBox = type("ScaleBox", (_StubWidgetBase,), {})
_unreal_stub.Stretch = types.SimpleNamespace(
    NONE="None", FILL="Fill", SCALE_TO_FIT="ScaleToFit",
    SCALE_TO_FIT_X="ScaleToFitX", SCALE_TO_FIT_Y="ScaleToFitY",
    SCALE_TO_FILL="ScaleToFill",
    USER_SPECIFIED="UserSpecified",
    USER_SPECIFIED_WITH_CLIPPING="UserSpecifiedWithClipping",
)
_unreal_stub.StretchDirection = types.SimpleNamespace(
    BOTH="Both", DOWN_ONLY="DownOnly", UP_ONLY="UpOnly",
)

_unreal_stub.SlateBrushDrawType = types.SimpleNamespace(
    BOX="Box", IMAGE="Image", NO_DRAW_TYPE="NoDrawType"
)
_unreal_stub.HorizontalAlignment = types.SimpleNamespace(
    H_ALIGN_LEFT="Left", H_ALIGN_CENTER="Center",
    H_ALIGN_RIGHT="Right", H_ALIGN_FILL="Fill",
)
_unreal_stub.VerticalAlignment = types.SimpleNamespace(
    V_ALIGN_TOP="Top", V_ALIGN_CENTER="Center",
    V_ALIGN_BOTTOM="Bottom", V_ALIGN_FILL="Fill",
)
_unreal_stub.SlateSizeRule = types.SimpleNamespace(AUTOMATIC="Auto", FILL="Fill")
_unreal_stub.SlateVisibility = types.SimpleNamespace(
    VISIBLE="Visible",
    COLLAPSED="Collapsed",
    HIDDEN="Hidden",
    HIT_TEST_INVISIBLE="HitTestInvisible",
    SELF_HIT_TEST_INVISIBLE="SelfHitTestInvisible",
)
_unreal_stub.Orientation = types.SimpleNamespace(
    ORIENT_VERTICAL="Vertical", ORIENT_HORIZONTAL="Horizontal",
)


def _log(*args, **kwargs):
    _R.record("unreal.log", *args)


def _log_warning(*args, **kwargs):
    _R.record("unreal.log_warning", *args)


def _log_error(*args, **kwargs):
    _R.record("unreal.log_error", *args)


_unreal_stub.log = _log
_unreal_stub.log_warning = _log_warning
_unreal_stub.log_error = _log_error

sys.modules["unreal"] = _unreal_stub

# ----- now import the module under test -----------------------------------

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
import widget_properties  # noqa: E402
import spec_loader  # noqa: E402


class TestWidgetPropertyApplicators(unittest.TestCase):

    def setUp(self) -> None:
        _R.calls.clear()

    def test_apply_text_on_textblock(self):
        w = _StubTextBlock()
        widget_properties.apply_widget_properties(w, {"Text": "Browse..."})
        self.assertEqual(w.properties["Text"].to_string(), "Browse...")

    def test_apply_brush_color_on_border(self):
        w = _unreal_stub.Border()
        widget_properties.apply_widget_properties(
            w, {"BrushColor": [0.141, 0.141, 0.141, 1.0]}
        )
        self.assertTrue(any(
            c[0] == "Border.set_editor_property" and c[1][0] == "brush_color"
            for c in _R.calls
        ), _R.calls)

    def test_apply_brush_color_converts_srgb_to_linear(self):
        w = _unreal_stub.Border()
        widget_properties.apply_widget_properties(
            w, {"BrushColor": [0.5, 0.5, 0.5, 1.0]}
        )
        r, g, b, a = w.properties["brush_color"].rgba
        self.assertAlmostEqual(r, 0.214041, places=5)
        self.assertAlmostEqual(g, 0.214041, places=5)
        self.assertAlmostEqual(b, 0.214041, places=5)
        self.assertEqual(a, 1.0)

    def test_apply_tint_on_image(self):
        w = _unreal_stub.Image()
        widget_properties.apply_widget_properties(
            w, {"Tint": [0.909, 0.439, 0.302, 1.0]}
        )
        self.assertIn(
            "Image.set_editor_property",
            [c[0] for c in _R.calls],
            _R.calls,
        )

    def test_apply_sizebox_dims(self):
        w = _unreal_stub.SizeBox()
        widget_properties.apply_widget_properties(
            w, {"WidthOverride": 3, "HeightOverride": 13}
        )
        self.assertEqual(w.properties["width_override"], 3)
        self.assertEqual(w.properties["height_override"], 13)
        self.assertTrue(w.properties["width_override_enabled"])
        self.assertTrue(w.properties["height_override_enabled"])

    def test_apply_sizebox_clear_height_override(self):
        w = _unreal_stub.SizeBox()
        widget_properties.apply_widget_properties(w, {"ClearHeightOverride": True})
        self.assertTrue(w.properties["height_override_cleared"])

    def test_apply_spinbox_range(self):
        w = _unreal_stub.SpinBox()
        widget_properties.apply_widget_properties(
            w, {"MinValue": 0.0, "MaxValue": 120.0, "Value": 0.0}
        )
        self.assertEqual(w.properties["min_value"], 0.0)
        self.assertEqual(w.properties["max_value"], 120.0)
        self.assertEqual(w.properties["value"], 0.0)

    def test_apply_multiline_read_only(self):
        w = _unreal_stub.MultiLineEditableText()
        widget_properties.apply_widget_properties(
            w, {"IsReadOnly": True, "Text": ""}
        )
        self.assertIs(w.properties["is_read_only"], True)

    def test_apply_multiline_auto_wrap(self):
        w = _unreal_stub.MultiLineEditableText()
        widget_properties.apply_widget_properties(w, {"AutoWrapText": False})
        self.assertIs(w.properties["auto_wrap_text"], False)

    def test_apply_unknown_property_logs_but_does_not_raise(self):
        w = _StubTextBlock()
        # Must not raise:
        widget_properties.apply_widget_properties(w, {"NonsenseKey": 42})
        # A warning must have been logged:
        warnings = [c for c in _R.calls if c[0] == "unreal.log_warning"]
        self.assertTrue(warnings, "expected a log_warning call for unknown property")

    def test_apply_combo_default_options(self):
        w = _unreal_stub.ComboBoxString()
        widget_properties.apply_widget_properties(
            w, {"DefaultOptions": ["X (0)", "Y (1)", "Z (2)"]}
        )
        self.assertEqual(w.properties["options"], ["X (0)", "Y (1)", "Z (2)"])

    def test_apply_scrollbox_always_show_scrollbar(self):
        w = _unreal_stub.ScrollBox()
        widget_properties.apply_widget_properties(w, {"AlwaysShowScrollbar": True})
        self.assertIs(w.properties["always_show_scrollbar"], True)

    def test_apply_visibility(self):
        w = _unreal_stub.Border()
        widget_properties.apply_widget_properties(
            w, {"Visibility": "SelfHitTestInvisible"}
        )
        self.assertEqual(w.properties["visibility"], "SelfHitTestInvisible")

    def test_apply_scrollbar_thickness(self):
        w = _unreal_stub.EditorUtilityScrollBox()
        widget_properties.apply_widget_properties(
            w,
            {
                "AlwaysShowScrollbarTrack": True,
                "ScrollbarThickness": [12, 12],
                "WheelScrollMultiplier": 1.0,
            },
        )
        self.assertIs(w.properties["always_show_scrollbar_track"], True)
        self.assertEqual(w.properties["scrollbar_thickness"].xy, (12.0, 12.0))
        self.assertEqual(w.properties["wheel_scroll_multiplier"], 1.0)


class TestSlotPropertyApplicators(unittest.TestCase):

    def setUp(self) -> None:
        _R.calls.clear()

    def test_apply_slot_padding_calls_set_editor_property(self):
        class _Slot:
            def __init__(self):
                self.props = {}
            def set_editor_property(self, k, v):
                self.props[k] = v
                _R.record("Slot.set_editor_property", k, v)
            def get_editor_property(self, k):
                return self.props.get(k)

        slot = _Slot()
        widget_properties.apply_slot_properties(slot, {"padding": [10, 6, 0, 6]})
        self.assertIn("padding", slot.props)

    def test_apply_canvas_slot_anchor_methods(self):
        class _CanvasSlot:
            def __init__(self):
                self.props = {}

            def get_editor_property(self, k):
                raise Exception(k)

            def set_anchors(self, value):
                self.props["anchors"] = value

            def set_offsets(self, value):
                self.props["offsets"] = value

        slot = _CanvasSlot()
        widget_properties.apply_slot_properties(
            slot,
            {
                "anchors_min": [0, 0],
                "anchors_max": [1, 1],
                "offsets": [0, 0, 0, 0],
                "h_align": "Fill",
                "v_align": "Fill",
            },
        )
        self.assertEqual(slot.props["anchors"][0].xy, (0.0, 0.0))
        self.assertEqual(slot.props["anchors"][1].xy, (1.0, 1.0))
        self.assertEqual(slot.props["offsets"].ltrb, (0.0, 0.0, 0.0, 0.0))


class TestClassMapCompleteness(unittest.TestCase):

    def test_widget_class_map_covers_all_spec_types(self):
        """Every type in spec_loader.ALL_TYPES must resolve to a class in widget_properties."""
        for t in spec_loader.ALL_TYPES:
            cls = widget_properties.WIDGET_CLASS_MAP.get(t)
            self.assertIsNotNone(cls, f"Missing WIDGET_CLASS_MAP entry for {t!r}")


if __name__ == "__main__":
    unittest.main()
