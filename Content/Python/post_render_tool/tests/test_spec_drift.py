"""Cross-check widget names across C++ header, widget.py, and JSON spec.

Three-way drift detection — any rename / typo in one source is caught here.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from typing import Set, Tuple

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
from spec_loader import load_spec, collect_contract_names  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]


def _parse_cpp_uproperty_names() -> Tuple[Set[str], Set[str]]:
    """Extract BindWidget / BindWidgetOptional names from PostRenderToolWidget.h."""
    header = REPO_ROOT / "Source" / "PostRenderTool" / "Public" / "PostRenderToolWidget.h"
    text = header.read_text(encoding="utf-8")

    # Match:
    #   UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    #   UTextBlock* prereq_label_0;
    # and the BindWidgetOptional variant.
    pattern = re.compile(
        r"UPROPERTY\([^)]*meta\s*=\s*\(\s*(BindWidget|BindWidgetOptional)\s*\)[^)]*\)"
        r"\s*\n\s*U\w+\s*\*\s*(\w+)\s*;"
    )
    required: Set[str] = set()
    optional: Set[str] = set()
    for meta, name in pattern.findall(text):
        if meta == "BindWidget":
            required.add(name)
        else:
            optional.add(name)
    return required, optional


def _parse_widget_py_tuples() -> Tuple[Set[str], Set[str]]:
    widget_py = REPO_ROOT / "Content" / "Python" / "post_render_tool" / "widget.py"
    text = widget_py.read_text(encoding="utf-8")

    def _extract_tuple(var_name: str) -> Set[str]:
        m = re.search(rf"{var_name}\s*=\s*\(([^)]*)\)", text, re.DOTALL)
        if not m:
            return set()
        body = m.group(1)
        names = re.findall(r'"([a-zA-Z_][a-zA-Z0-9_]*)"', body)
        return set(names)

    return _extract_tuple("_REQUIRED_CONTROLS"), _extract_tuple("_OPTIONAL_CONTROLS")


def _parse_json_contract_names() -> Tuple[Set[str], Set[str]]:
    spec_path = REPO_ROOT / "docs" / "widget-tree-spec.json"
    spec = load_spec(str(spec_path))
    req, opt, _ = collect_contract_names(spec)
    return req, opt


class TestSpecDrift(unittest.TestCase):

    def test_required_names_match_across_three_sources(self):
        cpp_req, _ = _parse_cpp_uproperty_names()
        py_req, _ = _parse_widget_py_tuples()
        json_req, _ = _parse_json_contract_names()

        if not (cpp_req == py_req == json_req):
            diffs = []
            diffs.append(f"C++ - widget.py: {sorted(cpp_req - py_req)}")
            diffs.append(f"widget.py - C++: {sorted(py_req - cpp_req)}")
            diffs.append(f"C++ - JSON: {sorted(cpp_req - json_req)}")
            diffs.append(f"JSON - C++: {sorted(json_req - cpp_req)}")
            self.fail("Required name drift detected:\n" + "\n".join(diffs))

    def test_optional_names_match_across_three_sources(self):
        _, cpp_opt = _parse_cpp_uproperty_names()
        _, py_opt = _parse_widget_py_tuples()
        _, json_opt = _parse_json_contract_names()

        if not (cpp_opt == py_opt == json_opt):
            diffs = []
            diffs.append(f"C++ - widget.py: {sorted(cpp_opt - py_opt)}")
            diffs.append(f"widget.py - C++: {sorted(py_opt - cpp_opt)}")
            diffs.append(f"C++ - JSON: {sorted(cpp_opt - json_opt)}")
            diffs.append(f"JSON - C++: {sorted(json_opt - cpp_opt)}")
            self.fail("Optional name drift detected:\n" + "\n".join(diffs))

    def test_required_count_is_33(self):
        json_req, _ = _parse_json_contract_names()
        self.assertEqual(
            len(json_req), 33, f"Required count drift: {len(json_req)} != 33"
        )

    def test_optional_count_is_8(self):
        _, json_opt = _parse_json_contract_names()
        self.assertEqual(
            len(json_opt), 8, f"Optional count drift: {len(json_opt)} != 8"
        )


if __name__ == "__main__":
    unittest.main()
