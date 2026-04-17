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


_unreal_stub.Text = _StubText
_unreal_stub.LinearColor = _StubLinearColor
_unreal_stub.Vector2D = _StubVector2D
_unreal_stub.Margin = _StubMargin
_unreal_stub.SlateBrush = _StubSlateBrush

_unreal_stub.TextBlock = _StubTextBlock
_unreal_stub.ComboBoxString = _StubComboBoxString
_unreal_stub.Button = type("Button", (_StubWidgetBase,), {})
_unreal_stub.Image = type("Image", (_StubWidgetBase,), {})
_unreal_stub.Border = type("Border", (_StubWidgetBase,), {})
_unreal_stub.SizeBox = type("SizeBox", (_StubWidgetBase,), {})
_unreal_stub.SpinBox = type("SpinBox", (_StubWidgetBase,), {})
_unreal_stub.MultiLineEditableText = type("MultiLineEditableText", (_StubWidgetBase,), {})
_unreal_stub.Spacer = type("Spacer", (_StubWidgetBase,), {})
_unreal_stub.VerticalBox = type("VerticalBox", (_StubWidgetBase,), {})
_unreal_stub.HorizontalBox = type("HorizontalBox", (_StubWidgetBase,), {})
_unreal_stub.ScrollBox = type("ScrollBox", (_StubWidgetBase,), {})
_unreal_stub.CanvasPanel = type("CanvasPanel", (_StubWidgetBase,), {})

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
_unreal_stub.SlateVisibility = types.SimpleNamespace(VISIBLE="Visible")


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


class TestClassMapCompleteness(unittest.TestCase):

    def test_widget_class_map_covers_all_spec_types(self):
        """Every type in spec_loader.ALL_TYPES must resolve to a class in widget_properties."""
        for t in spec_loader.ALL_TYPES:
            cls = widget_properties.WIDGET_CLASS_MAP.get(t)
            self.assertIsNotNone(cls, f"Missing WIDGET_CLASS_MAP entry for {t!r}")


if __name__ == "__main__":
    unittest.main()
