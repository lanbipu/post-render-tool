"""Variant catalog for widget styling.

Maps (widget_type, variant_name) → properties dict. The build pipeline
resolves a node's `variant` field to these properties, then merges with
the node's explicit `properties` (explicit wins).

Pure-Python — no unreal import.

Variants are semantic roles, not visual primitives. Change a variant's
recipe here to restyle every widget using it (theme-level edits).
"""

from __future__ import annotations

from typing import Any, Dict


# ---------------------------------------------------------------------------
# Color palette — RGBA tuples, linear color space (0..1).
# Keep in sync with docs/figma-design-prompt.md visual style section.
# ---------------------------------------------------------------------------

COLORS = {
    "accent_orange":      [0.909, 0.439, 0.302, 1.0],   # section accent + primary button
    "card_bg":            [0.141, 0.141, 0.141, 1.0],   # section card background
    "text_title":         [0.95, 0.95, 0.95, 1.0],      # near white — section titles
    "text_primary":       [0.88, 0.88, 0.88, 1.0],      # light gray — body text
    "text_secondary":     [0.5, 0.5, 0.5, 1.0],         # medium gray — hints
    "status_ok":          [0.298, 0.686, 0.314, 1.0],   # #4CAF50 — green
    "status_err":         [0.957, 0.263, 0.212, 1.0],   # #F44336 — red
    "button_primary":     [0.909, 0.439, 0.302, 1.0],   # same as accent orange
    "button_secondary":   [0.22, 0.22, 0.22, 1.0],      # dark panel gray
    "divider":            [0.25, 0.25, 0.25, 1.0],      # subtle divider
}


# ---------------------------------------------------------------------------
# TextBlock variants — dict of property names to apply.
# "Font" is a compound spec consumed by widget_properties._apply_textblock_font.
# ---------------------------------------------------------------------------

TEXTBLOCK_VARIANTS: Dict[str, Dict[str, Any]] = {
    "section_title": {
        "ColorAndOpacity": COLORS["text_title"],
        "Font": {"size": 13, "type_face": "Bold"},
    },
    "subsection_title": {
        "ColorAndOpacity": COLORS["accent_orange"],
        "Font": {"size": 11, "type_face": "Bold"},
    },
    "body": {
        "ColorAndOpacity": COLORS["text_primary"],
        "Font": {"size": 12, "type_face": "Regular"},
    },
    "body_mono": {
        "ColorAndOpacity": COLORS["text_primary"],
        "Font": {"size": 11, "type_face": "Mono"},
    },
    "hint": {
        "ColorAndOpacity": COLORS["text_secondary"],
        "Font": {"size": 11, "type_face": "Regular"},
    },
    "status_ok": {
        "ColorAndOpacity": COLORS["status_ok"],
        "Font": {"size": 12, "type_face": "Regular"},
    },
    "button_text": {
        "ColorAndOpacity": COLORS["text_title"],
        "Font": {"size": 12, "type_face": "Regular"},
    },
    "primary_button_text": {
        "ColorAndOpacity": [1.0, 1.0, 1.0, 1.0],
        "Font": {"size": 13, "type_face": "Bold"},
    },
    "results_header": {
        "ColorAndOpacity": COLORS["text_secondary"],
        "Font": {"size": 11, "type_face": "Bold"},
    },
}


# ---------------------------------------------------------------------------
# Button variants — background color; widget_properties renders this by
# tinting FButtonStyle.Normal/Hovered/Pressed brushes.
# ---------------------------------------------------------------------------

BUTTON_VARIANTS: Dict[str, Dict[str, Any]] = {
    "primary": {
        "BackgroundColor": COLORS["button_primary"],
    },
    "secondary": {
        "BackgroundColor": COLORS["button_secondary"],
    },
}


def resolve(widget_type: str, variant: str) -> Dict[str, Any]:
    """Return the properties dict for (widget_type, variant), or empty if unknown.

    Unknown variants are silently empty — caller's explicit properties still apply.
    """
    if not variant:
        return {}
    if widget_type == "TextBlock":
        return dict(TEXTBLOCK_VARIANTS.get(variant, {}))
    if widget_type == "Button":
        return dict(BUTTON_VARIANTS.get(variant, {}))
    return {}
