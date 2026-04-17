"""JSON spec loader + schema validator for widget-tree-spec.json.

Pure Python — no unreal import. Used both at build time (inside UE) and by
drift detection tests (outside UE).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Set, Tuple


VALID_ROLES = {"required", "optional", "decorative"}

# Widget types that can hold children. Builder walks into these.
PANEL_TYPES = {"CanvasPanel", "ScrollBox", "VerticalBox", "HorizontalBox"}
CONTENT_TYPES = {"Border", "SizeBox", "Button"}
LEAF_TYPES = {
    "Image", "TextBlock", "Spacer",
    "SpinBox", "ComboBoxString", "MultiLineEditableText",
}
ALL_TYPES = PANEL_TYPES | CONTENT_TYPES | LEAF_TYPES


class SpecValidationError(Exception):
    """Raised when validate_spec(raise_on_error=True) finds issues."""


def load_spec(path: str) -> dict:
    """Read and parse the JSON spec file.

    Raises FileNotFoundError if the path does not exist.
    Raises json.JSONDecodeError on malformed JSON.
    """
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def validate_spec(spec: dict, *, raise_on_error: bool = False) -> List[str]:
    """Return list of validation error messages (empty if spec is OK).

    If raise_on_error=True and any errors exist, raises SpecValidationError
    with all errors joined.
    """
    errors: List[str] = []

    # ---- blueprint block ----
    bp = spec.get("blueprint")
    if not isinstance(bp, dict):
        errors.append("Missing or invalid 'blueprint' block")
    else:
        if "asset_path" not in bp:
            errors.append("blueprint.asset_path is required")
        if "parent_class" not in bp:
            errors.append("blueprint.parent_class is required")
        root_panel = bp.get("root_panel")
        if not isinstance(root_panel, dict):
            errors.append("blueprint.root_panel must be an object")
        else:
            if root_panel.get("type") not in PANEL_TYPES:
                errors.append(
                    f"blueprint.root_panel.type must be one of {PANEL_TYPES}, "
                    f"got {root_panel.get('type')!r}"
                )
            if not root_panel.get("name"):
                errors.append("blueprint.root_panel.name is required")

    # ---- root_children block ----
    root_children = spec.get("root_children")
    if not isinstance(root_children, list):
        errors.append("root_children must be an array")
        if raise_on_error and errors:
            raise SpecValidationError("\n".join(errors))
        return errors

    seen_names: Set[str] = set()
    for idx, node in enumerate(root_children):
        _validate_node(node, f"root_children[{idx}]", seen_names, errors)

    if raise_on_error and errors:
        raise SpecValidationError("\n".join(errors))
    return errors


def _validate_node(
    node: dict, path: str, seen_names: Set[str], errors: List[str]
) -> None:
    if not isinstance(node, dict):
        errors.append(f"{path}: must be an object, got {type(node).__name__}")
        return

    # type
    type_name = node.get("type")
    if type_name not in ALL_TYPES:
        errors.append(f"{path}: unknown type {type_name!r}")

    # name uniqueness
    name = node.get("name")
    if not isinstance(name, str) or not name:
        errors.append(f"{path}: name must be a non-empty string")
    else:
        if name in seen_names:
            errors.append(f"{path}: duplicate name {name!r}")
        seen_names.add(name)

    # role
    role = node.get("role")
    if role not in VALID_ROLES:
        errors.append(
            f"{path}: role must be one of {VALID_ROLES}, got {role!r}"
        )

    # children vs leaf
    children = node.get("children")
    if children is not None:
        if type_name in LEAF_TYPES:
            errors.append(
                f"{path}: type {type_name!r} is a leaf and cannot have children"
            )
        elif not isinstance(children, list):
            errors.append(f"{path}.children: must be an array")
        else:
            if type_name in CONTENT_TYPES and len(children) > 1:
                errors.append(
                    f"{path}: type {type_name!r} accepts at most 1 child, "
                    f"got {len(children)}"
                )
            for ci, child in enumerate(children):
                _validate_node(child, f"{path}.children[{ci}]", seen_names, errors)


def collect_contract_names(
    spec: dict,
) -> Tuple[Set[str], Set[str], Set[str]]:
    """Return (required_names, optional_names, decorative_names) across tree."""
    required: Set[str] = set()
    optional: Set[str] = set()
    decorative: Set[str] = set()

    def walk(node: dict) -> None:
        if not isinstance(node, dict):
            return
        role = node.get("role")
        name = node.get("name", "")
        if role == "required":
            required.add(name)
        elif role == "optional":
            optional.add(name)
        elif role == "decorative":
            decorative.add(name)
        for child in node.get("children", []) or []:
            walk(child)

    for node in spec.get("root_children", []):
        walk(node)
    return required, optional, decorative
