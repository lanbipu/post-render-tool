#!/usr/bin/env python3
"""One-shot migration: add `variant` field to every TextBlock/Button in
docs/widget-tree-spec.json based on naming conventions.

Idempotent: re-running is safe — existing variant values are overwritten by
the rules below. If you have hand-tuned variants you want to preserve, add
them to EXPLICIT_OVERRIDES.

Run:
    python3 scripts/patch_spec_variants.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parent.parent / "docs" / "widget-tree-spec.json"

# ---------------------------------------------------------------------------
# Classification rules (first match wins, ordered)
# ---------------------------------------------------------------------------

EXPLICIT_OVERRIDES = {
    # Section card titles
    "lbl_prereq_title":         "section_title",
    "lbl_csv_file_title":       "section_title",
    "lbl_csv_preview_title":    "section_title",
    "lbl_coord_title":          "section_title",
    "lbl_axis_title":           "section_title",
    "lbl_actions_title":        "section_title",

    # Orange subsection headers
    "lbl_pos_subheader":        "subsection_title",
    "lbl_rot_subheader":        "subsection_title",
    "lbl_designer_header":      "subsection_title",
    "lbl_ue_header":            "subsection_title",
    "lbl_prereq_arrow":         "subsection_title",  # ▶ icon, orange in Figma

    # Hints (muted gray)
    "txt_detected_fps":         "hint",
    "txt_frame_hint":           "hint",

    # Special — RESULTS label uses pre-set ColorAndOpacity
    "lbl_results_header":       "results_header",

    # Status summary "6 / 6 OK" — green when all pass
    "prereq_summary":           "status_ok",

    # Primary call-to-action
    "lbl_btn_import_text":      "primary_button_text",
    "btn_import":               "primary",
}

# Regex-based rules, applied only if not in EXPLICIT_OVERRIDES.
TEXTBLOCK_PATTERNS = [
    (re.compile(r"^lbl_btn_.*_text$"), "button_text"),
]
BUTTON_PATTERNS = [
    (re.compile(r"^btn_"), "secondary"),
]


def classify(node: dict) -> str | None:
    name = node.get("name", "")
    typ = node.get("type", "")
    if name in EXPLICIT_OVERRIDES:
        return EXPLICIT_OVERRIDES[name]
    patterns = TEXTBLOCK_PATTERNS if typ == "TextBlock" else (
        BUTTON_PATTERNS if typ == "Button" else []
    )
    for regex, variant in patterns:
        if regex.match(name):
            return variant
    if typ == "TextBlock":
        return "body"  # default for unclassified TextBlocks
    return None


def walk(node: dict, stats: dict) -> None:
    typ = node.get("type", "")
    if typ in ("TextBlock", "Button"):
        variant = classify(node)
        if variant:
            node["variant"] = variant
            stats[variant] = stats.get(variant, 0) + 1
        else:
            stats["_unclassified"] = stats.get("_unclassified", 0) + 1
    for child in node.get("children", []) or []:
        walk(child, stats)


def main() -> int:
    raw = SPEC_PATH.read_text(encoding="utf-8")
    spec = json.loads(raw)

    stats: dict = {}
    for node in spec.get("root_children", []):
        walk(node, stats)

    # Write back with stable 2-space indentation to match existing file style.
    out = json.dumps(spec, indent=2, ensure_ascii=False)
    SPEC_PATH.write_text(out + "\n", encoding="utf-8")

    print(f"Patched {SPEC_PATH.relative_to(SPEC_PATH.parent.parent)}")
    for v, n in sorted(stats.items()):
        print(f"  {v:25s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
