# Widget Blueprint Automation + Manual Bootstrap Checklist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate `BP_PostRenderToolWidget.uasset` programmatically from a JSON spec so the Figma design is reproduced 1:1 in Designer, editable afterward; also provide a manual checklist as fallback when automation is unavailable.

**Architecture:** JSON spec file is single source of truth → C++ helper (`UPostRenderToolBuildHelper`) exposes `UWidgetBlueprint::WidgetTree` mutation to Python via 3 `BlueprintCallable` UFUNCTIONs → Python builder (`build_widget_blueprint.run_build()`) walks the spec tree recursively, creates missing widgets, applies widget/slot properties, compiles + saves. Idempotent: rerun never clobbers user tweaks on existing widgets. Manual checklist (`docs/bootstrap-checklist.md`) is the fallback doc for when the plugin hasn't been rebuilt yet.

**Tech Stack:** UE 5.7 (UMG + Blutility + BlueprintEditorLibrary), C++17, Python 3 (`unreal` module), pytest for pure-Python tests.

**Prior decision reversed:** Commit `bd140d7` removed the automation on maintenance-cost grounds. This plan reinstates it because the user's use case (1:1 Figma parity + iterative tweak-in-Designer + C++ contract evolution) flips the cost-benefit. Old code at `ac8b918` / `9788e5e` is reference; new version extends API to support nested containers + slot/widget properties (old version only supported flat VerticalBox root).

**UE 5.7 source-level feasibility audit (completed before plan execution):**
- `UWidgetBlueprint::WidgetTree` (`BaseWidgetBlueprint.h:16-17`) is `UPROPERTY()` without `BlueprintVisible` → Python reflection hidden (confirmed via `PyGenUtil.cpp:1608-1611`). C++ bridge is mandatory. ✅
- `UWidgetTree::ConstructWidget<T>` (`WidgetTree.h:100-118`) — template, callable from UFUNCTION with `TSubclassOf<UWidget>` param. ✅
- `UPanelWidget::AddChild` (`PanelWidget.h:58-59`) returns `UPanelSlot*` — saves a `GetPanelSlot` UFUNCTION round-trip. ✅
- `UContentWidget::SetContent` (`ContentWidget.h:18-27`) returns `UPanelSlot*` for single-child containers (Border/SizeBox/Button). ✅
- `UWidget::Slot` (`Widget.h:263-264`) is `UPROPERTY(BlueprintReadOnly)` — Python can read it. ✅
- **`UWidget::bIsVariable` (`Widget.h:318`) is a PRIVATE bitfield with no public setter** — cannot be changed from business module. **BUT** `Widget.cpp:195` constructor initializes it to `true` by default, so every widget `ConstructWidget` creates is automatically a `Variable` (satisfies `BindWidget` reflection requirement). Trade-off: decorative widgets become variables too, wasting a minor UPROPERTY slot per decorative widget on the generated class — **functionally harmless**, accepted. ⚠️ Cannot suppress Variable flag for decorative widgets without engine source modification; scope accepts this cost.
- `MarkBlueprintAsStructurallyModified` vs `Modify`: structural widget-tree changes need `FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint)` (engine pattern) — `Modify()` alone is Undo-only, does not retrigger BP compilation dependencies.
- `UFUNCTION` out-param semantics: Python receives `(return_value, out1, out2, ...)` tuple (confirmed `PyGenUtil.cpp:1173,1229,1242`).
- `UENUM(BlueprintType)` → Python `unreal.<EnumName>` with member names `UPPER_SNAKE_CASE` (strips `E` class-name prefix per `PyGenUtil.cpp:2893,2908-2910`).

---

## File Structure

### Creates

| Path | Responsibility |
|---|---|
| `docs/widget-tree-spec.schema.md` | Human-readable schema reference (widget types, allowed props per type, slot types) |
| `docs/widget-tree-spec.json` | Authoritative widget tree — root + 41 contract + decorative widgets + nested containers |
| `Source/PostRenderTool/Public/PostRenderToolBuildHelper.h` | C++ helper UCLASS declaration (3 UFUNCTIONs) |
| `Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp` | C++ helper implementation |
| `Content/Python/post_render_tool/spec_loader.py` | JSON load + schema validation (pure Python) |
| `Content/Python/post_render_tool/widget_properties.py` | Widget/slot property applicators dispatch (requires `unreal`) |
| `Content/Python/post_render_tool/build_widget_blueprint.py` | Top-level orchestrator (`run_build()`) |
| `Content/Python/post_render_tool/tests/test_spec_loader.py` | Pure-Python tests for spec validation |
| `Content/Python/post_render_tool/tests/test_widget_properties.py` | Pure-Python tests using stub mocks for `unreal` |
| `Content/Python/post_render_tool/tests/test_spec_drift.py` | Cross-check JSON ↔ C++ header ↔ widget.py tuples |
| `docs/bootstrap-checklist.md` | Manual Designer bootstrap checklist (fallback / training) |

### Modifies

| Path | Change |
|---|---|
| `Content/Python/post_render_tool/widget_builder.py` | Add `rebuild_from_spec()` entry + toolbar menu registration |
| `docs/deployment-guide.md:34-122` | §1.3 rewritten: primary = run script, fallback = checklist |
| `CLAUDE.md` | Add build commands + note C++ rebuild required after `.h` changes |
| `docs/bindwidget-contract.md:292+` | Append §11 cross-link to spec + how automation handles contract |
| `~/.claude/projects/-Users-bip-lan-AIWorkspace-vp-post-render-tool/memory/feedback_no_python_bp_automation.md` | Invert decision with new context |
| `~/.claude/projects/-Users-bip-lan-AIWorkspace-vp-post-render-tool/memory/MEMORY.md` | Update pointer description |

---

## Tasks

### Task 1: Author JSON Schema Documentation

**Why:** Before writing the spec JSON, establish a human-readable reference describing legal widget types, per-type properties, and slot property conventions. This becomes the contract between spec author and builder.

**Files:**
- Create: `docs/widget-tree-spec.schema.md`

- [ ] **Step 1: Write schema documentation**

Create `docs/widget-tree-spec.schema.md` with this exact content:

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add docs/widget-tree-spec.schema.md
git commit -m "docs: 新增 widget-tree-spec.schema.md 描述自动生成 BP 的 JSON 契约"
```

Expected output: single-file commit with `[p4-sync] ✓ <branch> pushed to p4` on stderr.

---

### Task 2: Write Failing Spec-Validation Tests

**Why:** Before authoring the spec, lock down what "valid" means via tests. The validator will be used at build-time and by the drift detector.

**Files:**
- Create: `Content/Python/post_render_tool/tests/test_spec_loader.py`

- [ ] **Step 1: Write the failing test file**

Create `Content/Python/post_render_tool/tests/test_spec_loader.py`:

```python
"""Pure-Python tests for spec_loader.py — no UE imports."""

import json
import pytest
import sys
from pathlib import Path

# Import spec_loader without touching sibling modules that require unreal.
_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
from spec_loader import (  # noqa: E402
    load_spec,
    validate_spec,
    collect_contract_names,
    SpecValidationError,
)

REQUIRED_NAMES = {
    "btn_recheck", "btn_browse", "txt_file_path",
    "txt_frame_count", "txt_focal_range", "txt_timecode", "txt_sensor_width",
    "spn_fps", "txt_detected_fps",
    "spn_frame", "txt_designer_pos", "txt_designer_rot",
    "txt_ue_pos", "txt_ue_rot", "btn_spawn_cam",
    "cmb_pos_x_src", "spn_pos_x_scale",
    "cmb_pos_y_src", "spn_pos_y_scale",
    "cmb_pos_z_src", "spn_pos_z_scale",
    "cmb_rot_pitch_src", "spn_rot_pitch_scale",
    "cmb_rot_yaw_src", "spn_rot_yaw_scale",
    "cmb_rot_roll_src", "spn_rot_roll_scale",
    "btn_apply_mapping", "btn_save_mapping",
    "btn_import", "btn_open_seq", "btn_open_mrq", "txt_results",
}
OPTIONAL_NAMES = {
    "prereq_label_0", "prereq_label_1", "prereq_label_2",
    "prereq_label_3", "prereq_label_4", "prereq_label_5",
    "prereq_summary", "txt_frame_hint",
}


def _minimal_spec() -> dict:
    return {
        "blueprint": {
            "asset_path": "/PostRenderTool/Blueprints/BP_PostRenderToolWidget",
            "parent_class": "/Script/PostRenderTool.PostRenderToolWidget",
            "root_panel": {"type": "VerticalBox", "name": "RootPanel"},
        },
        "root_children": [
            {
                "type": "TextBlock", "name": "txt_file_path", "role": "required",
                "properties": {"Text": ""},
            },
        ],
    }


def test_load_spec_reads_json(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_minimal_spec()))
    assert load_spec(str(p))["blueprint"]["asset_path"].endswith("BP_PostRenderToolWidget")


def test_load_spec_fails_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_spec(str(tmp_path / "does-not-exist.json"))


def test_validate_accepts_minimal_spec():
    assert validate_spec(_minimal_spec()) == []


def test_validate_rejects_missing_blueprint_key():
    spec = _minimal_spec()
    del spec["blueprint"]
    errs = validate_spec(spec)
    assert any("blueprint" in e for e in errs)


def test_validate_rejects_missing_asset_path():
    spec = _minimal_spec()
    del spec["blueprint"]["asset_path"]
    errs = validate_spec(spec)
    assert any("asset_path" in e for e in errs)


def test_validate_rejects_invalid_role():
    spec = _minimal_spec()
    spec["root_children"][0]["role"] = "mandatory"  # typo
    errs = validate_spec(spec)
    assert any("role" in e for e in errs)


def test_validate_rejects_duplicate_names():
    spec = _minimal_spec()
    spec["root_children"].append(spec["root_children"][0].copy())
    errs = validate_spec(spec)
    assert any("duplicate" in e.lower() for e in errs)


def test_validate_rejects_children_on_leaf_type():
    spec = _minimal_spec()
    spec["root_children"][0]["children"] = [
        {"type": "TextBlock", "name": "inner", "role": "decorative"}
    ]
    errs = validate_spec(spec)
    assert any("cannot have children" in e.lower() for e in errs)


def test_collect_contract_names_partitions_correctly():
    spec = _minimal_spec()
    spec["root_children"].append(
        {"type": "TextBlock", "name": "prereq_label_0", "role": "optional"}
    )
    spec["root_children"].append(
        {"type": "TextBlock", "name": "lbl_section_csv", "role": "decorative",
         "properties": {"Text": "CSV File"}}
    )
    req, opt, dec = collect_contract_names(spec)
    assert req == {"txt_file_path"}
    assert opt == {"prereq_label_0"}
    assert dec == {"lbl_section_csv"}


def test_spec_validation_error_is_raised_when_requested():
    spec = _minimal_spec()
    del spec["blueprint"]
    with pytest.raises(SpecValidationError):
        validate_spec(spec, raise_on_error=True)


def test_real_spec_file_is_valid():
    """Catches regressions in docs/widget-tree-spec.json itself."""
    repo_root = Path(__file__).resolve().parents[4]
    spec_path = repo_root / "docs" / "widget-tree-spec.json"
    if not spec_path.exists():
        pytest.skip("widget-tree-spec.json not yet authored")
    spec = load_spec(str(spec_path))
    errs = validate_spec(spec)
    assert errs == [], f"Spec has errors:\n" + "\n".join(errs)


def test_real_spec_contract_names_match_hardcoded_sets():
    repo_root = Path(__file__).resolve().parents[4]
    spec_path = repo_root / "docs" / "widget-tree-spec.json"
    if not spec_path.exists():
        pytest.skip("widget-tree-spec.json not yet authored")
    spec = load_spec(str(spec_path))
    req, opt, _ = collect_contract_names(spec)
    assert req == REQUIRED_NAMES, f"Required mismatch: {req ^ REQUIRED_NAMES}"
    assert opt == OPTIONAL_NAMES, f"Optional mismatch: {opt ^ OPTIONAL_NAMES}"
```

- [ ] **Step 2: Run tests to verify they all fail (no spec_loader module yet)**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python -m pytest post_render_tool/tests/test_spec_loader.py -v
```

Expected: ImportError — `No module named 'spec_loader'`. All tests collection-error.

- [ ] **Step 3: Commit failing tests**

```bash
git add Content/Python/post_render_tool/tests/test_spec_loader.py
git commit -m "test: 新增 spec_loader 契约测试（尚未实现，预期失败）"
```

---

### Task 3: Implement Spec Loader

**Files:**
- Create: `Content/Python/post_render_tool/spec_loader.py`

- [ ] **Step 1: Implement the loader**

Create `Content/Python/post_render_tool/spec_loader.py`:

```python
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
        if raise_on_error:
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
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python -m pytest post_render_tool/tests/test_spec_loader.py -v
```

Expected: 10 passed, 2 skipped (the two `test_real_spec_file_*` tests skip because the spec JSON hasn't been authored yet).

- [ ] **Step 3: Commit**

```bash
git add Content/Python/post_render_tool/spec_loader.py
git commit -m "feat(python): 实现 spec_loader JSON 解析与契约校验"
```

---

### Task 4: Author Widget Tree Spec (41 widgets + decorative structure)

**Why:** The spec is the single source of truth for the build. It mirrors `bindwidget-contract.md` §5.3–5.9 exactly, but in machine-parseable form.

**Files:**
- Create: `docs/widget-tree-spec.json`

- [ ] **Step 1: Author the full JSON spec**

Create `docs/widget-tree-spec.json` with this structure (full content — six Section nodes as children of root). Because of length, here is the complete file:

```json
{
  "blueprint": {
    "asset_path": "/PostRenderTool/Blueprints/BP_PostRenderToolWidget",
    "parent_class": "/Script/PostRenderTool.PostRenderToolWidget",
    "root_panel": { "type": "VerticalBox", "name": "RootPanel" }
  },
  "root_children": [
    {
      "type": "ScrollBox", "name": "lbl_root_scroll", "role": "decorative",
      "properties": { "Orientation": "Vertical" },
      "slot": { "fill_size": 1.0, "size_rule": "Fill", "padding": [0, 0, 0, 0] },
      "children": [
        {
          "type": "VerticalBox", "name": "lbl_sections", "role": "decorative",
          "slot": { "padding": [12, 12, 12, 12] },
          "children": [
            { "$ref": "SECTION_1" },
            { "$ref": "SECTION_2" },
            { "$ref": "SECTION_3" },
            { "$ref": "SECTION_4" },
            { "$ref": "SECTION_5" },
            { "$ref": "SECTION_6" }
          ]
        }
      ]
    }
  ],
  "_note": "Replace each $ref placeholder with the corresponding SECTION_N body from the inline fragments below. $ref is NOT resolved by the loader — it exists here only as an authoring hint. Paste the full SECTION_N object in place."
}
```

**IMPORTANT:** The `$ref` pattern above is an authoring guide, not a real loader feature — the implementation does NOT resolve `$ref`. Inline the full section objects. The 6 section fragments follow; replace the `{ "$ref": "SECTION_N" }` lines with the corresponding full objects.

**SECTION_1 fragment:**

```json
{
  "type": "Border", "name": "lbl_card_prereq", "role": "decorative",
  "properties": {
    "BrushColor": [0.141, 0.141, 0.141, 1.0],
    "Padding": [12, 10, 12, 10]
  },
  "slot": { "padding": [0, 0, 0, 8] },
  "children": [
    {
      "type": "VerticalBox", "name": "lbl_prereq_vbox", "role": "decorative",
      "children": [
        {
          "type": "HorizontalBox", "name": "lbl_prereq_header", "role": "decorative",
          "children": [
            { "type": "TextBlock", "name": "lbl_prereq_arrow", "role": "decorative",
              "properties": { "Text": "▶" },
              "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" } },
            { "type": "SizeBox", "name": "lbl_prereq_accent", "role": "decorative",
              "properties": { "WidthOverride": 3, "HeightOverride": 13 },
              "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
              "children": [
                { "type": "Image", "name": "lbl_prereq_accent_img", "role": "decorative",
                  "properties": { "Tint": [0.909, 0.439, 0.302, 1.0],
                                  "ImageSize": [3, 13], "DrawAs": "Box" } }
              ]
            },
            { "type": "TextBlock", "name": "lbl_prereq_title", "role": "decorative",
              "properties": { "Text": "Prerequisites" },
              "slot": { "v_align": "Center" } },
            { "type": "Spacer", "name": "lbl_prereq_header_spacer", "role": "decorative",
              "slot": { "fill_size": 1.0, "size_rule": "Fill" } },
            { "type": "TextBlock", "name": "prereq_summary", "role": "optional",
              "properties": { "Text": "" },
              "slot": { "v_align": "Center" } }
          ]
        },
        {
          "type": "VerticalBox", "name": "lbl_prereq_body", "role": "decorative",
          "slot": { "padding": [0, 8, 0, 0] },
          "children": [
            {
              "type": "HorizontalBox", "name": "lbl_prereq_row_0", "role": "decorative",
              "children": [
                { "type": "SizeBox", "name": "lbl_prereq_dot_0", "role": "decorative",
                  "properties": { "WidthOverride": 8, "HeightOverride": 8 },
                  "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
                  "children": [
                    { "type": "Image", "name": "lbl_prereq_dot_0_img", "role": "decorative",
                      "properties": { "Tint": [0.8, 0.8, 0.8, 1.0], "ImageSize": [8, 8] } }
                  ]
                },
                { "type": "TextBlock", "name": "prereq_label_0", "role": "optional",
                  "properties": { "Text": "" } }
              ]
            },
            {
              "type": "HorizontalBox", "name": "lbl_prereq_row_1", "role": "decorative",
              "children": [
                { "type": "SizeBox", "name": "lbl_prereq_dot_1", "role": "decorative",
                  "properties": { "WidthOverride": 8, "HeightOverride": 8 },
                  "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
                  "children": [
                    { "type": "Image", "name": "lbl_prereq_dot_1_img", "role": "decorative",
                      "properties": { "Tint": [0.8, 0.8, 0.8, 1.0], "ImageSize": [8, 8] } }
                  ]
                },
                { "type": "TextBlock", "name": "prereq_label_1", "role": "optional",
                  "properties": { "Text": "" } }
              ]
            },
            {
              "type": "HorizontalBox", "name": "lbl_prereq_row_2", "role": "decorative",
              "children": [
                { "type": "SizeBox", "name": "lbl_prereq_dot_2", "role": "decorative",
                  "properties": { "WidthOverride": 8, "HeightOverride": 8 },
                  "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
                  "children": [
                    { "type": "Image", "name": "lbl_prereq_dot_2_img", "role": "decorative",
                      "properties": { "Tint": [0.8, 0.8, 0.8, 1.0], "ImageSize": [8, 8] } }
                  ]
                },
                { "type": "TextBlock", "name": "prereq_label_2", "role": "optional",
                  "properties": { "Text": "" } }
              ]
            },
            {
              "type": "HorizontalBox", "name": "lbl_prereq_row_3", "role": "decorative",
              "children": [
                { "type": "SizeBox", "name": "lbl_prereq_dot_3", "role": "decorative",
                  "properties": { "WidthOverride": 8, "HeightOverride": 8 },
                  "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
                  "children": [
                    { "type": "Image", "name": "lbl_prereq_dot_3_img", "role": "decorative",
                      "properties": { "Tint": [0.8, 0.8, 0.8, 1.0], "ImageSize": [8, 8] } }
                  ]
                },
                { "type": "TextBlock", "name": "prereq_label_3", "role": "optional",
                  "properties": { "Text": "" } }
              ]
            },
            {
              "type": "HorizontalBox", "name": "lbl_prereq_row_4", "role": "decorative",
              "children": [
                { "type": "SizeBox", "name": "lbl_prereq_dot_4", "role": "decorative",
                  "properties": { "WidthOverride": 8, "HeightOverride": 8 },
                  "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
                  "children": [
                    { "type": "Image", "name": "lbl_prereq_dot_4_img", "role": "decorative",
                      "properties": { "Tint": [0.8, 0.8, 0.8, 1.0], "ImageSize": [8, 8] } }
                  ]
                },
                { "type": "TextBlock", "name": "prereq_label_4", "role": "optional",
                  "properties": { "Text": "" } }
              ]
            },
            {
              "type": "HorizontalBox", "name": "lbl_prereq_row_5", "role": "decorative",
              "children": [
                { "type": "SizeBox", "name": "lbl_prereq_dot_5", "role": "decorative",
                  "properties": { "WidthOverride": 8, "HeightOverride": 8 },
                  "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
                  "children": [
                    { "type": "Image", "name": "lbl_prereq_dot_5_img", "role": "decorative",
                      "properties": { "Tint": [0.8, 0.8, 0.8, 1.0], "ImageSize": [8, 8] } }
                  ]
                },
                { "type": "TextBlock", "name": "prereq_label_5", "role": "optional",
                  "properties": { "Text": "" } }
              ]
            },
            {
              "type": "HorizontalBox", "name": "lbl_prereq_bottom_row", "role": "decorative",
              "slot": { "padding": [0, 8, 0, 0] },
              "children": [
                { "type": "Button", "name": "btn_recheck", "role": "required",
                  "children": [
                    { "type": "TextBlock", "name": "lbl_btn_recheck_text",
                      "role": "decorative",
                      "properties": { "Text": "Recheck" },
                      "slot": { "padding": [14, 6, 14, 6] } }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

**SECTION_2 fragment:**

```json
{
  "type": "Border", "name": "lbl_card_csv_file", "role": "decorative",
  "properties": {
    "BrushColor": [0.141, 0.141, 0.141, 1.0],
    "Padding": [12, 10, 12, 10]
  },
  "slot": { "padding": [0, 0, 0, 8] },
  "children": [
    {
      "type": "VerticalBox", "name": "lbl_csv_file_vbox", "role": "decorative",
      "children": [
        {
          "type": "HorizontalBox", "name": "lbl_csv_file_header", "role": "decorative",
          "children": [
            { "type": "SizeBox", "name": "lbl_csv_file_accent", "role": "decorative",
              "properties": { "WidthOverride": 3, "HeightOverride": 13 },
              "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
              "children": [
                { "type": "Image", "name": "lbl_csv_file_accent_img", "role": "decorative",
                  "properties": { "Tint": [0.909, 0.439, 0.302, 1.0],
                                  "ImageSize": [3, 13], "DrawAs": "Box" } }
              ]
            },
            { "type": "TextBlock", "name": "lbl_csv_file_title", "role": "decorative",
              "properties": { "Text": "CSV File" },
              "slot": { "v_align": "Center" } }
          ]
        },
        {
          "type": "HorizontalBox", "name": "lbl_csv_file_row", "role": "decorative",
          "slot": { "padding": [0, 8, 0, 0] },
          "children": [
            { "type": "Button", "name": "btn_browse", "role": "required",
              "children": [
                { "type": "TextBlock", "name": "lbl_btn_browse_text",
                  "role": "decorative",
                  "properties": { "Text": "Browse..." },
                  "slot": { "padding": [14, 6, 14, 6] } }
              ]
            },
            { "type": "TextBlock", "name": "txt_file_path", "role": "required",
              "properties": { "Text": "" },
              "slot": { "padding": [10, 6, 0, 6], "fill_size": 1.0, "size_rule": "Fill",
                        "v_align": "Center" } }
          ]
        }
      ]
    }
  ]
}
```

**SECTION_3 fragment:**

```json
{
  "type": "Border", "name": "lbl_card_csv_preview", "role": "decorative",
  "properties": {
    "BrushColor": [0.141, 0.141, 0.141, 1.0],
    "Padding": [12, 10, 12, 10]
  },
  "slot": { "padding": [0, 0, 0, 8] },
  "children": [
    {
      "type": "VerticalBox", "name": "lbl_csv_preview_vbox", "role": "decorative",
      "children": [
        {
          "type": "HorizontalBox", "name": "lbl_csv_preview_header", "role": "decorative",
          "children": [
            { "type": "SizeBox", "name": "lbl_csv_preview_accent", "role": "decorative",
              "properties": { "WidthOverride": 3, "HeightOverride": 13 },
              "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
              "children": [
                { "type": "Image", "name": "lbl_csv_preview_accent_img", "role": "decorative",
                  "properties": { "Tint": [0.909, 0.439, 0.302, 1.0],
                                  "ImageSize": [3, 13], "DrawAs": "Box" } }
              ]
            },
            { "type": "TextBlock", "name": "lbl_csv_preview_title", "role": "decorative",
              "properties": { "Text": "CSV Preview" },
              "slot": { "v_align": "Center" } }
          ]
        },
        {
          "type": "VerticalBox", "name": "lbl_csv_preview_stat", "role": "decorative",
          "slot": { "padding": [0, 8, 0, 0] },
          "children": [
            { "type": "TextBlock", "name": "txt_frame_count", "role": "required",
              "properties": { "Text": "" } },
            { "type": "TextBlock", "name": "txt_focal_range", "role": "required",
              "properties": { "Text": "" } },
            { "type": "TextBlock", "name": "txt_timecode", "role": "required",
              "properties": { "Text": "" } },
            { "type": "TextBlock", "name": "txt_sensor_width", "role": "required",
              "properties": { "Text": "" } }
          ]
        },
        {
          "type": "HorizontalBox", "name": "lbl_csv_preview_fps_row", "role": "decorative",
          "slot": { "padding": [0, 8, 0, 0] },
          "children": [
            { "type": "TextBlock", "name": "lbl_fps", "role": "decorative",
              "properties": { "Text": "FPS" },
              "slot": { "padding": [0, 6, 10, 6], "v_align": "Center" } },
            { "type": "SpinBox", "name": "spn_fps", "role": "required",
              "properties": { "MinValue": 0.0, "MaxValue": 120.0, "Value": 0.0,
                              "MinFractionalDigits": 1 } },
            { "type": "TextBlock", "name": "txt_detected_fps", "role": "required",
              "properties": { "Text": "" },
              "slot": { "padding": [10, 6, 0, 6], "v_align": "Center" } }
          ]
        }
      ]
    }
  ]
}
```

**SECTION_4 fragment:**

```json
{
  "type": "Border", "name": "lbl_card_coord", "role": "decorative",
  "properties": {
    "BrushColor": [0.141, 0.141, 0.141, 1.0],
    "Padding": [12, 10, 12, 10]
  },
  "slot": { "padding": [0, 0, 0, 8] },
  "children": [
    {
      "type": "VerticalBox", "name": "lbl_coord_vbox", "role": "decorative",
      "children": [
        {
          "type": "HorizontalBox", "name": "lbl_coord_header", "role": "decorative",
          "children": [
            { "type": "SizeBox", "name": "lbl_coord_accent", "role": "decorative",
              "properties": { "WidthOverride": 3, "HeightOverride": 13 },
              "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
              "children": [
                { "type": "Image", "name": "lbl_coord_accent_img", "role": "decorative",
                  "properties": { "Tint": [0.909, 0.439, 0.302, 1.0],
                                  "ImageSize": [3, 13], "DrawAs": "Box" } }
              ]
            },
            { "type": "TextBlock", "name": "lbl_coord_title", "role": "decorative",
              "properties": { "Text": "Coordinate Verification" },
              "slot": { "v_align": "Center" } }
          ]
        },
        {
          "type": "HorizontalBox", "name": "lbl_coord_frame_row", "role": "decorative",
          "slot": { "padding": [0, 8, 0, 0] },
          "children": [
            { "type": "TextBlock", "name": "lbl_frame", "role": "decorative",
              "properties": { "Text": "Frame" },
              "slot": { "padding": [0, 6, 10, 6], "v_align": "Center" } },
            { "type": "SpinBox", "name": "spn_frame", "role": "required",
              "properties": { "MinValue": 0.0, "MaxValue": 0.0, "Value": 0.0 } },
            { "type": "TextBlock", "name": "txt_frame_hint", "role": "optional",
              "properties": { "Text": "" },
              "slot": { "padding": [10, 6, 0, 6], "v_align": "Center" } }
          ]
        },
        {
          "type": "VerticalBox", "name": "lbl_coord_pair", "role": "decorative",
          "slot": { "padding": [0, 8, 0, 0] },
          "children": [
            { "type": "TextBlock", "name": "lbl_designer_header", "role": "decorative",
              "properties": { "Text": "DESIGNER (source)",
                              "ColorAndOpacity": [0.7, 0.7, 0.7, 1.0] } },
            { "type": "TextBlock", "name": "txt_designer_pos", "role": "required",
              "properties": { "Text": "" } },
            { "type": "TextBlock", "name": "txt_designer_rot", "role": "required",
              "properties": { "Text": "" } },
            { "type": "Border", "name": "lbl_coord_separator", "role": "decorative",
              "properties": { "BrushColor": [0.227, 0.227, 0.227, 1.0],
                              "Padding": [0, 0, 0, 0] },
              "slot": { "padding": [0, 6, 0, 6] } },
            { "type": "TextBlock", "name": "lbl_ue_header", "role": "decorative",
              "properties": { "Text": "→ UE (result)",
                              "ColorAndOpacity": [0.7, 0.7, 0.7, 1.0] } },
            { "type": "TextBlock", "name": "txt_ue_pos", "role": "required",
              "properties": { "Text": "" } },
            { "type": "TextBlock", "name": "txt_ue_rot", "role": "required",
              "properties": { "Text": "" } }
          ]
        },
        {
          "type": "Button", "name": "btn_spawn_cam", "role": "required",
          "slot": { "padding": [0, 8, 0, 0], "h_align": "Left" },
          "children": [
            { "type": "TextBlock", "name": "lbl_btn_spawn_cam_text", "role": "decorative",
              "properties": { "Text": "Spawn Test Camera" },
              "slot": { "padding": [14, 6, 14, 6] } }
          ]
        }
      ]
    }
  ]
}
```

**SECTION_5 fragment:** (Axis Mapping — mirrors bindwidget-contract.md §5.8; 6 axis rows share the same structure — use the pattern below for each, substituting names):

```json
{
  "type": "Border", "name": "lbl_card_axis", "role": "decorative",
  "properties": {
    "BrushColor": [0.141, 0.141, 0.141, 1.0],
    "Padding": [12, 10, 12, 10]
  },
  "slot": { "padding": [0, 0, 0, 8] },
  "children": [
    {
      "type": "VerticalBox", "name": "lbl_axis_vbox", "role": "decorative",
      "children": [
        {
          "type": "HorizontalBox", "name": "lbl_axis_header", "role": "decorative",
          "children": [
            { "type": "SizeBox", "name": "lbl_axis_accent", "role": "decorative",
              "properties": { "WidthOverride": 3, "HeightOverride": 13 },
              "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
              "children": [
                { "type": "Image", "name": "lbl_axis_accent_img", "role": "decorative",
                  "properties": { "Tint": [0.909, 0.439, 0.302, 1.0],
                                  "ImageSize": [3, 13], "DrawAs": "Box" } }
              ]
            },
            { "type": "TextBlock", "name": "lbl_axis_title", "role": "decorative",
              "properties": { "Text": "Axis Mapping" },
              "slot": { "v_align": "Center" } }
          ]
        },
        { "type": "TextBlock", "name": "lbl_pos_subheader", "role": "decorative",
          "properties": { "Text": "POSITION (m → cm)",
                          "ColorAndOpacity": [0.7, 0.7, 0.7, 1.0] },
          "slot": { "padding": [0, 8, 0, 4] } },
        {
          "type": "VerticalBox", "name": "lbl_pos_rows", "role": "decorative",
          "children": [
            { "$ref": "AXIS_ROW", "$args": {
                "row_name": "lbl_row_ue_x", "label_name": "lbl_ue_x", "label_text": "UE.X",
                "arrow_name": "lbl_ue_x_arrow", "cmb_name": "cmb_pos_x_src",
                "mul_name": "lbl_ue_x_mul", "spn_name": "spn_pos_x_scale"
            }},
            { "$ref": "AXIS_ROW", "$args": {
                "row_name": "lbl_row_ue_y", "label_name": "lbl_ue_y", "label_text": "UE.Y",
                "arrow_name": "lbl_ue_y_arrow", "cmb_name": "cmb_pos_y_src",
                "mul_name": "lbl_ue_y_mul", "spn_name": "spn_pos_y_scale"
            }},
            { "$ref": "AXIS_ROW", "$args": {
                "row_name": "lbl_row_ue_z", "label_name": "lbl_ue_z", "label_text": "UE.Z",
                "arrow_name": "lbl_ue_z_arrow", "cmb_name": "cmb_pos_z_src",
                "mul_name": "lbl_ue_z_mul", "spn_name": "spn_pos_z_scale"
            }}
          ]
        },
        { "type": "TextBlock", "name": "lbl_rot_subheader", "role": "decorative",
          "properties": { "Text": "ROTATION (deg)",
                          "ColorAndOpacity": [0.7, 0.7, 0.7, 1.0] },
          "slot": { "padding": [0, 12, 0, 4] } },
        {
          "type": "VerticalBox", "name": "lbl_rot_rows", "role": "decorative",
          "children": [
            { "$ref": "AXIS_ROW", "$args": {
                "row_name": "lbl_row_pitch", "label_name": "lbl_pitch", "label_text": "Pitch",
                "arrow_name": "lbl_pitch_arrow", "cmb_name": "cmb_rot_pitch_src",
                "mul_name": "lbl_pitch_mul", "spn_name": "spn_rot_pitch_scale"
            }},
            { "$ref": "AXIS_ROW", "$args": {
                "row_name": "lbl_row_yaw", "label_name": "lbl_yaw", "label_text": "Yaw",
                "arrow_name": "lbl_yaw_arrow", "cmb_name": "cmb_rot_yaw_src",
                "mul_name": "lbl_yaw_mul", "spn_name": "spn_rot_yaw_scale"
            }},
            { "$ref": "AXIS_ROW", "$args": {
                "row_name": "lbl_row_roll", "label_name": "lbl_roll", "label_text": "Roll",
                "arrow_name": "lbl_roll_arrow", "cmb_name": "cmb_rot_roll_src",
                "mul_name": "lbl_roll_mul", "spn_name": "spn_rot_roll_scale"
            }}
          ]
        },
        {
          "type": "HorizontalBox", "name": "lbl_axis_btn_row", "role": "decorative",
          "slot": { "padding": [0, 8, 0, 0] },
          "children": [
            { "type": "Button", "name": "btn_apply_mapping", "role": "required",
              "slot": { "padding": [0, 0, 8, 0] },
              "children": [
                { "type": "TextBlock", "name": "lbl_btn_apply_mapping_text",
                  "role": "decorative",
                  "properties": { "Text": "Apply Mapping" },
                  "slot": { "padding": [14, 6, 14, 6] } }
              ]
            },
            { "type": "Button", "name": "btn_save_mapping", "role": "required",
              "children": [
                { "type": "TextBlock", "name": "lbl_btn_save_mapping_text",
                  "role": "decorative",
                  "properties": { "Text": "Save to config.py" },
                  "slot": { "padding": [14, 6, 14, 6] } }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

**AXIS_ROW template** (inline each of the 6 occurrences — substitute `$args` placeholders with concrete values):

```json
{
  "type": "HorizontalBox", "name": "<row_name>", "role": "decorative",
  "children": [
    { "type": "TextBlock", "name": "<label_name>", "role": "decorative",
      "properties": { "Text": "<label_text>" },
      "slot": { "padding": [0, 6, 8, 6], "v_align": "Center" } },
    { "type": "TextBlock", "name": "<arrow_name>", "role": "decorative",
      "properties": { "Text": "←" },
      "slot": { "padding": [0, 6, 8, 6], "v_align": "Center" } },
    { "type": "ComboBoxString", "name": "<cmb_name>", "role": "required",
      "properties": { "DefaultOptions": [] } },
    { "type": "TextBlock", "name": "<mul_name>", "role": "decorative",
      "properties": { "Text": "×" },
      "slot": { "padding": [8, 6, 8, 6], "v_align": "Center" } },
    { "type": "SpinBox", "name": "<spn_name>", "role": "required",
      "properties": { "Value": 0.0 } }
  ]
}
```

**SECTION_6 fragment:**

```json
{
  "type": "Border", "name": "lbl_card_actions", "role": "decorative",
  "properties": {
    "BrushColor": [0.141, 0.141, 0.141, 1.0],
    "Padding": [12, 10, 12, 10]
  },
  "slot": { "padding": [0, 0, 0, 8] },
  "children": [
    {
      "type": "VerticalBox", "name": "lbl_actions_vbox", "role": "decorative",
      "children": [
        {
          "type": "HorizontalBox", "name": "lbl_actions_header", "role": "decorative",
          "children": [
            { "type": "SizeBox", "name": "lbl_actions_accent", "role": "decorative",
              "properties": { "WidthOverride": 3, "HeightOverride": 13 },
              "slot": { "padding": [0, 0, 8, 0], "v_align": "Center" },
              "children": [
                { "type": "Image", "name": "lbl_actions_accent_img", "role": "decorative",
                  "properties": { "Tint": [0.909, 0.439, 0.302, 1.0],
                                  "ImageSize": [3, 13], "DrawAs": "Box" } }
              ]
            },
            { "type": "TextBlock", "name": "lbl_actions_title", "role": "decorative",
              "properties": { "Text": "Actions" },
              "slot": { "v_align": "Center" } }
          ]
        },
        {
          "type": "Button", "name": "btn_import", "role": "required",
          "slot": { "padding": [0, 8, 0, 0], "h_align": "Fill" },
          "children": [
            { "type": "TextBlock", "name": "lbl_btn_import_text", "role": "decorative",
              "properties": { "Text": "Import" },
              "slot": { "padding": [14, 10, 14, 10], "h_align": "Center" } }
          ]
        },
        {
          "type": "HorizontalBox", "name": "lbl_actions_btn_row", "role": "decorative",
          "slot": { "padding": [0, 8, 0, 0] },
          "children": [
            { "type": "Button", "name": "btn_open_seq", "role": "required",
              "slot": { "fill_size": 1.0, "size_rule": "Fill", "padding": [0, 0, 4, 0] },
              "children": [
                { "type": "TextBlock", "name": "lbl_btn_open_seq_text", "role": "decorative",
                  "properties": { "Text": "Open Sequencer" },
                  "slot": { "padding": [14, 6, 14, 6], "h_align": "Center" } }
              ]
            },
            { "type": "Button", "name": "btn_open_mrq", "role": "required",
              "slot": { "fill_size": 1.0, "size_rule": "Fill", "padding": [4, 0, 0, 0] },
              "children": [
                { "type": "TextBlock", "name": "lbl_btn_open_mrq_text", "role": "decorative",
                  "properties": { "Text": "Open MRQ" },
                  "slot": { "padding": [14, 6, 14, 6], "h_align": "Center" } }
              ]
            }
          ]
        },
        { "type": "TextBlock", "name": "lbl_results_header", "role": "decorative",
          "properties": { "Text": "RESULTS",
                          "ColorAndOpacity": [0.7, 0.7, 0.7, 1.0] },
          "slot": { "padding": [0, 12, 0, 4] } },
        { "type": "MultiLineEditableText", "name": "txt_results", "role": "required",
          "properties": { "Text": "", "IsReadOnly": true } }
      ]
    }
  ]
}
```

Manually assemble the full `docs/widget-tree-spec.json` by:
1. Starting from the top-level skeleton shown first
2. Replacing each `{ "$ref": "SECTION_N" }` with the inline Section N fragment above
3. In the SECTION_5 body, replacing each `{ "$ref": "AXIS_ROW", "$args": {...} }` with the AXIS_ROW template, substituting the `<row_name>`, `<label_name>`, `<label_text>`, `<arrow_name>`, `<cmb_name>`, `<mul_name>`, `<spn_name>` placeholders with the values from the `$args` object (strip all `$ref` and `$args` keys from the final JSON — they must not appear in the output)

- [ ] **Step 2: Validate the authored JSON parses**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
python3 -m json.tool docs/widget-tree-spec.json > /dev/null
echo "Exit: $?"
```

Expected: `Exit: 0` (no JSON syntax errors).

- [ ] **Step 3: Run spec validation tests — real-spec tests should now pass**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python -m pytest post_render_tool/tests/test_spec_loader.py -v
```

Expected: all 12 tests pass (including `test_real_spec_file_is_valid` and `test_real_spec_contract_names_match_hardcoded_sets`).

If a name mismatch is reported, cross-check against `Source/PostRenderTool/Public/PostRenderToolWidget.h` UPROPERTY names — the header is the source of truth.

- [ ] **Step 4: Commit**

```bash
git add docs/widget-tree-spec.json
git commit -m "feat(docs): 新增 widget-tree-spec.json 描述 Figma 1:1 的完整 UMG 层级"
```

---

### Task 5: Write Failing Widget-Property Applicator Tests

**Why:** The Python-side property applicators are the bridge between JSON values and `unreal` API calls. Since `unreal` cannot be imported outside the UE process, tests use stub classes that record property setter calls.

**Files:**
- Create: `Content/Python/post_render_tool/tests/test_widget_properties.py`

- [ ] **Step 1: Write the failing test file**

Create `Content/Python/post_render_tool/tests/test_widget_properties.py`:

```python
"""Pure-Python tests for widget_properties.py using recorded-call stubs."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Any

# Provide a minimal unreal stub module so widget_properties can import unreal
_unreal_stub = types.ModuleType("unreal")


@dataclass
class _Recorder:
    """Records every method call / property set the stubbed unreal performs."""
    calls: List[Tuple[str, Tuple[Any, ...]]] = field(default_factory=list)

    def record(self, name: str, *args: Any) -> Any:
        self.calls.append((name, args))
        return None


_R = _Recorder()


class _StubText:
    def __init__(self, s: str) -> None:
        self.s = s
    def to_string(self) -> str:  # for readability in test assertions
        return self.s


class _StubLinearColor:
    def __init__(self, r: float, g: float, b: float, a: float = 1.0) -> None:
        self.rgba = (r, g, b, a)


class _StubVector2D:
    def __init__(self, x: float, y: float) -> None:
        self.xy = (x, y)


class _StubMargin:
    def __init__(self, l: float, t: float, r: float, b: float) -> None:
        self.ltrb = (l, t, r, b)


class _StubWidget:
    def __init__(self, widget_type: str) -> None:
        self.widget_type = widget_type
        self.properties = {}

    def set_editor_property(self, name: str, value: Any) -> None:
        self.properties[name] = value
        _R.record(f"{self.widget_type}.set_editor_property", name, value)

    def get_editor_property(self, name: str) -> Any:
        return self.properties.get(name)


class _StubTextBlock(_StubWidget):
    def __init__(self) -> None:
        super().__init__("TextBlock")
    def set_text(self, t: _StubText) -> None:
        self.properties["Text"] = t
        _R.record("TextBlock.set_text", t.to_string())


_unreal_stub.Text = _StubText
_unreal_stub.LinearColor = _StubLinearColor
_unreal_stub.Vector2D = _StubVector2D
_unreal_stub.Margin = _StubMargin
_unreal_stub.TextBlock = _StubTextBlock
_unreal_stub.Button = type("Button", (_StubWidget,), {})
_unreal_stub.Image = type("Image", (_StubWidget,), {})
_unreal_stub.Border = type("Border", (_StubWidget,), {})
_unreal_stub.SizeBox = type("SizeBox", (_StubWidget,), {})
_unreal_stub.SpinBox = type("SpinBox", (_StubWidget,), {})
_unreal_stub.ComboBoxString = type("ComboBoxString", (_StubWidget,), {"add_option": lambda self, o: _R.record("ComboBoxString.add_option", o)})
_unreal_stub.MultiLineEditableText = type("MultiLineEditableText", (_StubWidget,), {})
_unreal_stub.Spacer = type("Spacer", (_StubWidget,), {})
_unreal_stub.VerticalBox = type("VerticalBox", (_StubWidget,), {})
_unreal_stub.HorizontalBox = type("HorizontalBox", (_StubWidget,), {})
_unreal_stub.ScrollBox = type("ScrollBox", (_StubWidget,), {})
_unreal_stub.CanvasPanel = type("CanvasPanel", (_StubWidget,), {})


class _StubSlateBrush:
    def __init__(self) -> None:
        self.tint_color = None
        self.image_size = None
        self.draw_as = None


_unreal_stub.SlateBrush = _StubSlateBrush

# Enum value placeholders.
_unreal_stub.SlateBrushDrawType = types.SimpleNamespace(BOX="Box", IMAGE="Image", NO_DRAW_TYPE="NoDrawType")
_unreal_stub.HorizontalAlignment = types.SimpleNamespace(
    H_ALIGN_LEFT="Left", H_ALIGN_CENTER="Center", H_ALIGN_RIGHT="Right", H_ALIGN_FILL="Fill"
)
_unreal_stub.VerticalAlignment = types.SimpleNamespace(
    V_ALIGN_TOP="Top", V_ALIGN_CENTER="Center", V_ALIGN_BOTTOM="Bottom", V_ALIGN_FILL="Fill"
)
_unreal_stub.SlateVisibility = types.SimpleNamespace(VISIBLE="Visible")

sys.modules["unreal"] = _unreal_stub

# Now import the module under test.
_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
import widget_properties  # noqa: E402


def setup_function(_fn):
    _R.calls.clear()


def test_apply_text_on_textblock():
    w = _StubTextBlock()
    widget_properties.apply_widget_properties(w, {"Text": "Browse..."})
    assert w.properties["Text"].to_string() == "Browse..."


def test_apply_brush_color_on_border():
    w = _unreal_stub.Border()
    widget_properties.apply_widget_properties(w, {"BrushColor": [0.141, 0.141, 0.141, 1.0]})
    assert any(c[0] == "Border.set_editor_property" and c[1][0] == "brush_color"
               for c in _R.calls)


def test_apply_tint_on_image():
    w = _unreal_stub.Image()
    widget_properties.apply_widget_properties(w, {"Tint": [0.909, 0.439, 0.302, 1.0]})
    call_names = [c[0] for c in _R.calls]
    assert "Image.set_editor_property" in call_names


def test_apply_sizebox_dims():
    w = _unreal_stub.SizeBox()
    widget_properties.apply_widget_properties(w, {"WidthOverride": 3, "HeightOverride": 13})
    assert w.properties["width_override"] == 3
    assert w.properties["height_override"] == 13


def test_apply_spinbox_range():
    w = _unreal_stub.SpinBox()
    widget_properties.apply_widget_properties(
        w, {"MinValue": 0.0, "MaxValue": 120.0, "Value": 0.0}
    )
    assert w.properties["min_value"] == 0.0
    assert w.properties["max_value"] == 120.0
    assert w.properties["value"] == 0.0


def test_apply_multiline_read_only():
    w = _unreal_stub.MultiLineEditableText()
    widget_properties.apply_widget_properties(w, {"IsReadOnly": True, "Text": ""})
    assert w.properties["is_read_only"] is True


def test_apply_unknown_property_logs_but_does_not_raise():
    w = _StubTextBlock()
    widget_properties.apply_widget_properties(w, {"NonsenseKey": 42})
    # Should not raise; the property is silently ignored + logged


def test_apply_slot_padding_calls_set_editor_property():
    class _Slot:
        def __init__(self):
            self.props = {}
        def set_editor_property(self, k, v):
            self.props[k] = v
            _R.record("Slot.set_editor_property", k, v)

    slot = _Slot()
    widget_properties.apply_slot_properties(slot, {"padding": [10, 6, 0, 6]})
    assert "padding" in slot.props


def test_widget_class_map_covers_all_spec_types():
    """Every type listed in spec_loader.ALL_TYPES must resolve to a class."""
    sys.path.insert(0, str(_HERE))
    import spec_loader  # noqa: E402
    for t in spec_loader.ALL_TYPES:
        cls = widget_properties.WIDGET_CLASS_MAP.get(t)
        assert cls is not None, f"Missing WIDGET_CLASS_MAP entry for {t!r}"
```

- [ ] **Step 2: Run tests to verify they fail (no widget_properties module yet)**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python -m pytest post_render_tool/tests/test_widget_properties.py -v
```

Expected: all tests fail on `ImportError: No module named 'widget_properties'`.

- [ ] **Step 3: Commit failing tests**

```bash
git add Content/Python/post_render_tool/tests/test_widget_properties.py
git commit -m "test: 新增 widget_properties 契约测试（尚未实现，预期失败）"
```

---

### Task 6: Implement Widget Property Applicators

**Files:**
- Create: `Content/Python/post_render_tool/widget_properties.py`

- [ ] **Step 1: Implement the module**

Create `Content/Python/post_render_tool/widget_properties.py`:

```python
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
    r, g, b, a = list(rgba) + [1.0] * (4 - len(rgba))
    return unreal.LinearColor(r, g, b, a)


def _vec2(xy) -> "unreal.Vector2D":
    return unreal.Vector2D(float(xy[0]), float(xy[1]))


def _margin(ltrb) -> "unreal.Margin":
    l, t, r, b = list(ltrb) + [0.0] * (4 - len(ltrb))
    return unreal.Margin(float(l), float(t), float(r), float(b))


# ---------------------------------------------------------------------------
# Per-type property applicators
# Key = property name in spec JSON.
# Value = callable(widget, value) -> None.
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


def _apply_image_tint(w, v):
    brush = w.get_editor_property("brush") or unreal.SlateBrush()
    brush.set_editor_property("tint_color", _linear_color(v))
    w.set_editor_property("brush", brush)


def _apply_image_size(w, v):
    brush = w.get_editor_property("brush") or unreal.SlateBrush()
    brush.set_editor_property("image_size", _vec2(v))
    w.set_editor_property("brush", brush)


def _apply_image_draw_as(w, v):
    brush = w.get_editor_property("brush") or unreal.SlateBrush()
    mapping = {"Box": unreal.SlateBrushDrawType.BOX,
               "Image": unreal.SlateBrushDrawType.IMAGE,
               "NoDrawType": unreal.SlateBrushDrawType.NO_DRAW_TYPE}
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
    mapping = {"Vertical": "Vertical", "Horizontal": "Horizontal"}
    w.set_editor_property("orientation", mapping.get(v, "Vertical"))


def _apply_spacer_size(w, v):
    w.set_editor_property("size", _vec2(v))


_PROPERTY_APPLICATORS: Dict[str, Callable[[Any, Any], None]] = {
    "Text": _apply_textblock_text,
    "BrushColor": _apply_color_prop("brush_color"),
    "ColorAndOpacity": _apply_color_prop("color_and_opacity"),
    "BackgroundColor": _apply_color_prop("background_color"),
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
}


def apply_widget_properties(widget, props: Dict[str, Any]) -> None:
    """Apply JSON-spec properties onto a live unreal widget instance.

    Unknown properties are logged and skipped — never raise.
    """
    # Special: MultiLineEditableText uses the generic Text key too.
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
# Slot property applicators
# Dispatch is simpler — any slot accepts padding/alignment/fill_size/size_rule
# via reflection; rarely needs per-slot branching.
# ---------------------------------------------------------------------------

_H_ALIGN_MAP = {
    "Left": unreal.HorizontalAlignment.H_ALIGN_LEFT,
    "Center": unreal.HorizontalAlignment.H_ALIGN_CENTER,
    "Right": unreal.HorizontalAlignment.H_ALIGN_RIGHT,
    "Fill": unreal.HorizontalAlignment.H_ALIGN_FILL,
}
_V_ALIGN_MAP = {
    "Top": unreal.VerticalAlignment.V_ALIGN_TOP,
    "Center": unreal.VerticalAlignment.V_ALIGN_CENTER,
    "Bottom": unreal.VerticalAlignment.V_ALIGN_BOTTOM,
    "Fill": unreal.VerticalAlignment.V_ALIGN_FILL,
}


def apply_slot_properties(slot, props: Dict[str, Any]) -> None:
    """Apply slot-layout properties onto a UPanelSlot instance.

    Silently skips properties that the specific slot type doesn't expose —
    UMG slot reflection throws on unknown keys, so we guard per-key.
    """
    if slot is None:
        return

    if "padding" in props:
        _try_set(slot, "padding", _margin(props["padding"]))

    if "h_align" in props:
        _try_set(slot, "horizontal_alignment",
                 _H_ALIGN_MAP.get(props["h_align"], _H_ALIGN_MAP["Fill"]))

    if "v_align" in props:
        _try_set(slot, "vertical_alignment",
                 _V_ALIGN_MAP.get(props["v_align"], _V_ALIGN_MAP["Fill"]))

    if "fill_size" in props or "size_rule" in props:
        size = slot.get_editor_property("size") if _slot_has(slot, "size") else None
        if size is not None:
            if "fill_size" in props:
                size.set_editor_property("value", float(props["fill_size"]))
            if "size_rule" in props:
                rule = props["size_rule"]
                # "Auto" → ESlateSizeRule::Automatic, "Fill" → Fill
                # unreal.SlateSizeRule enum
                enum = unreal.SlateSizeRule.AUTOMATIC if rule == "Auto" \
                    else unreal.SlateSizeRule.FILL
                size.set_editor_property("size_rule", enum)
            _try_set(slot, "size", size)

    # CanvasPanelSlot-specific
    if "anchors_min" in props or "anchors_max" in props:
        try:
            anchors = unreal.Anchors(props.get("anchors_min", [0, 0]),
                                     props.get("anchors_max", [1, 1]))
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
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python -m pytest post_render_tool/tests/test_widget_properties.py -v
```

Expected: 9 passed. All stub-based tests green.

- [ ] **Step 3: Commit**

```bash
git add Content/Python/post_render_tool/widget_properties.py
git commit -m "feat(python): 实现 widget/slot 属性应用器（支持 13 种 widget + 常见 slot 属性）"
```

---

### Task 7: Write C++ Helper Header

**Why:** Python reflection cannot see `UWidgetBlueprint::WidgetTree`. We expose tree mutation via 3 `BlueprintCallable` UFUNCTIONs. Audit confirmed `UPanelWidget::AddChild` and `UContentWidget::SetContent` both return `UPanelSlot*`, so a 4th `GetPanelSlot` function is unnecessary. The `bIsVariable` private-bitfield issue (`Widget.h:318`) is sidestepped by the constructor's default `true` value — see Architecture notes.

**Files:**
- Create: `Source/PostRenderTool/Public/PostRenderToolBuildHelper.h`

- [ ] **Step 1: Write the header**

Create `Source/PostRenderTool/Public/PostRenderToolBuildHelper.h`:

```cpp
// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "PostRenderToolBuildHelper.generated.h"

class UWidgetBlueprint;
class UWidget;
class UPanelWidget;
class UPanelSlot;

UENUM(BlueprintType)
enum class EEnsureWidgetResult : uint8
{
    // Widget was created and added to the parent.
    Created,
    // Widget with that name already existed; left untouched.
    AlreadyExisted,
    // A widget with that name existed but its class mismatched — aborted.
    TypeMismatch,
    // Input was invalid (null blueprint, empty name, bad parent, etc.).
    InvalidInput,
    // Parent is not a panel / content widget — cannot add children.
    ParentCannotHoldChildren,
};

/**
 * Python bridge for scripted population of a UWidgetBlueprint's widget tree.
 *
 * UE 5.7 does NOT expose UWidgetBlueprint::WidgetTree to Python (BaseWidgetBlueprint.h:16-17
 * uses bare UPROPERTY() without BlueprintVisible — invisible to reflection per PyGenUtil.cpp
 * IsScriptExposedProperty rules). This helper wraps the minimum set of tree-mutation ops in
 * BlueprintCallable UFUNCTIONs so Python can drive them via unreal.PostRenderToolBuildHelper.*.
 *
 * Note on UWidget::bIsVariable: private bitfield (Widget.h:318), no public setter. Widget.cpp:195
 * constructor initializes to true by default, which matches what contract widgets need; the
 * side-effect that decorative widgets also get Variable is accepted as harmless.
 *
 * Usage from Python:
 *   root = unreal.PostRenderToolBuildHelper.ensure_root_panel(wbp, "RootPanel", unreal.VerticalBox)
 *   result, widget, slot = unreal.PostRenderToolBuildHelper.ensure_widget_under_parent(
 *       wbp, "btn_browse", unreal.Button, root)
 *   # slot is non-null when widget was newly created; apply slot properties via reflection.
 */
UCLASS()
class POSTRENDERTOOL_API UPostRenderToolBuildHelper : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /**
     * If the blueprint's WidgetTree is empty, create a root panel of the given
     * class and name. If a root already exists, leave it alone (no clobber).
     * Returns the root panel (either freshly created or pre-existing).
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static UPanelWidget* EnsureRootPanel(UWidgetBlueprint* Blueprint,
                                         FName RootName,
                                         TSubclassOf<UPanelWidget> RootClass);

    /**
     * Recursive search by FName across the whole WidgetTree (PanelWidget
     * children + ContentWidget content). Returns nullptr if not found.
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static UWidget* FindWidgetByName(UWidgetBlueprint* Blueprint,
                                     FName TargetName);

    /**
     * Ensure a widget with the given Name + Class exists as a child of the
     * provided ParentWidget. Returns the final widget (new or existing) via
     * OutWidget, its parent slot via OutSlot (nullptr when the widget pre-
     * existed — idempotency: caller must not re-apply slot properties), and
     * a status enum as the return value.
     *
     * - If a widget with that name already exists anywhere in the tree:
     *   - Same class → return AlreadyExisted, OutWidget = existing one, OutSlot = nullptr.
     *     (Caller must NOT re-apply properties — idempotency contract preserves user tweaks.)
     *   - Different class → return TypeMismatch, OutWidget/OutSlot = nullptr.
     * - If not found → construct under ParentWidget, mark blueprint structurally modified,
     *   return Created with OutWidget + OutSlot (from AddChild or SetContent).
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static EEnsureWidgetResult EnsureWidgetUnderParent(UWidgetBlueprint* Blueprint,
                                                      FName WidgetName,
                                                      TSubclassOf<UWidget> WidgetClass,
                                                      UWidget* ParentWidget,
                                                      UWidget*& OutWidget,
                                                      UPanelSlot*& OutSlot);
};
```

- [ ] **Step 2: Commit**

```bash
git add Source/PostRenderTool/Public/PostRenderToolBuildHelper.h
git commit -m "feat(module): 新增 PostRenderToolBuildHelper.h — UWidgetBlueprint::WidgetTree Python 桥接契约"
```

---

### Task 8: Implement C++ Helper

**Files:**
- Create: `Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp`

- [ ] **Step 1: Write the implementation**

Create `Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp`:

```cpp
// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolBuildHelper.h"

#include "WidgetBlueprint.h"
#include "Blueprint/WidgetTree.h"
#include "Components/Widget.h"
#include "Components/PanelWidget.h"
#include "Components/ContentWidget.h"
#include "Kismet2/BlueprintEditorUtils.h"

namespace
{
    UWidget* FindWidgetByNameRecursive(UWidget* Root, FName TargetName)
    {
        if (!Root)
        {
            return nullptr;
        }
        if (Root->GetFName() == TargetName)
        {
            return Root;
        }
        if (UPanelWidget* Panel = Cast<UPanelWidget>(Root))
        {
            for (int32 Index = 0; Index < Panel->GetChildrenCount(); ++Index)
            {
                if (UWidget* Found = FindWidgetByNameRecursive(Panel->GetChildAt(Index), TargetName))
                {
                    return Found;
                }
            }
        }
        else if (UContentWidget* ContentW = Cast<UContentWidget>(Root))
        {
            return FindWidgetByNameRecursive(ContentW->GetContent(), TargetName);
        }
        return nullptr;
    }
}

UPanelWidget* UPostRenderToolBuildHelper::EnsureRootPanel(UWidgetBlueprint* Blueprint,
                                                          FName RootName,
                                                          TSubclassOf<UPanelWidget> RootClass)
{
    if (!Blueprint || !RootClass || RootName.IsNone())
    {
        return nullptr;
    }

    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return nullptr;
    }

    if (UPanelWidget* Existing = Cast<UPanelWidget>(Tree->RootWidget))
    {
        return Existing;
    }

    if (Tree->RootWidget != nullptr)
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderToolBuildHelper] Root widget '%s' is %s (not a PanelWidget). "
                 "Refusing to overwrite — wrap or replace manually in Designer."),
            *Tree->RootWidget->GetName(),
            *Tree->RootWidget->GetClass()->GetName());
        return nullptr;
    }

    UPanelWidget* NewRoot = Cast<UPanelWidget>(Tree->ConstructWidget<UWidget>(RootClass, RootName));
    if (!NewRoot)
    {
        return nullptr;
    }
    Tree->RootWidget = NewRoot;
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    return NewRoot;
}

UWidget* UPostRenderToolBuildHelper::FindWidgetByName(UWidgetBlueprint* Blueprint,
                                                      FName TargetName)
{
    if (!Blueprint || TargetName.IsNone())
    {
        return nullptr;
    }
    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return nullptr;
    }
    return FindWidgetByNameRecursive(Tree->RootWidget, TargetName);
}

EEnsureWidgetResult UPostRenderToolBuildHelper::EnsureWidgetUnderParent(
    UWidgetBlueprint* Blueprint,
    FName WidgetName,
    TSubclassOf<UWidget> WidgetClass,
    UWidget* ParentWidget,
    UWidget*& OutWidget,
    UPanelSlot*& OutSlot)
{
    OutWidget = nullptr;
    OutSlot = nullptr;
    if (!Blueprint || !WidgetClass || WidgetName.IsNone() || !ParentWidget)
    {
        return EEnsureWidgetResult::InvalidInput;
    }
    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return EEnsureWidgetResult::InvalidInput;
    }

    // Already-exists check across the whole tree (idempotency contract).
    if (UWidget* Existing = FindWidgetByNameRecursive(Tree->RootWidget, WidgetName))
    {
        if (Existing->IsA(WidgetClass))
        {
            OutWidget = Existing;
            // OutSlot stays null: the caller MUST NOT re-apply slot props, by contract.
            return EEnsureWidgetResult::AlreadyExisted;
        }
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderToolBuildHelper] Widget '%s' exists as %s, spec wants %s — type mismatch."),
            *WidgetName.ToString(),
            *Existing->GetClass()->GetName(),
            *WidgetClass->GetName());
        return EEnsureWidgetResult::TypeMismatch;
    }

    UWidget* NewWidget = Tree->ConstructWidget<UWidget>(WidgetClass, WidgetName);
    if (!NewWidget)
    {
        return EEnsureWidgetResult::InvalidInput;
    }

    // AddChild / SetContent both return UPanelSlot* (verified PanelWidget.h:58-59,
    // ContentWidget.h:18-27) — hand it back to Python so it can set slot props
    // without a second UFUNCTION round-trip.
    if (UPanelWidget* ParentPanel = Cast<UPanelWidget>(ParentWidget))
    {
        OutSlot = ParentPanel->AddChild(NewWidget);
    }
    else if (UContentWidget* ParentContent = Cast<UContentWidget>(ParentWidget))
    {
        OutSlot = ParentContent->SetContent(NewWidget);
    }
    else
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderToolBuildHelper] Parent '%s' (%s) cannot hold children."),
            *ParentWidget->GetName(),
            *ParentWidget->GetClass()->GetName());
        return EEnsureWidgetResult::ParentCannotHoldChildren;
    }

    // Structural change → must use MarkBlueprintAsStructurallyModified, not Modify():
    // widget tree topology changes invalidate the generated class layout, so the BP
    // needs to be flagged for full recompile on next CompileBlueprint call.
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    OutWidget = NewWidget;

    // Note on bIsVariable: UWidget::bIsVariable (Widget.h:318) is a private bitfield,
    // no public setter. Widget.cpp:195 constructor initializes to TRUE by default, so
    // every widget we just constructed is automatically a Variable — exactly what
    // BindWidget / BindWidgetOptional contract widgets need for reflection. Decorative
    // widgets inherit the same default (minor overhead on generated class, harmless).
    return EEnsureWidgetResult::Created;
}
```

- [ ] **Step 2: Commit**

```bash
git add Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp
git commit -m "feat(module): 实现 UPostRenderToolBuildHelper（3 UFUNCTION 暴露 WidgetTree 操作）"
```

---

### Task 9: Manual Plugin Rebuild (user-run step)

**Why:** `UPROPERTY` changes (including new UFUNCTION registrations) require a full Editor shutdown + plugin rebuild. Live Coding does NOT pick these up.

**Files:** none modified in this task.

- [ ] **Step 1: Fully quit UE Editor**

Close all Editor windows. Verify no `UnrealEditor` process remains:

```bash
ps aux | grep -i unrealeditor | grep -v grep
```

Expected: no output.

- [ ] **Step 2: Rebuild plugin**

From the host project directory (one level above this plugin's `Plugins/` folder), run UBT or use your IDE's build target. Example command pattern for macOS / Xcode:

```bash
cd <host-project-root>
./Engine/Build/BatchFiles/Mac/Build.sh <HostProjectName>Editor Mac Development -Project="$(pwd)/<HostProjectName>.uproject" -WaitMutex -FromMsBuild
```

(Windows / Linux: use the equivalent `Build.bat` / `Build.sh`.)

Expected: `Total time in Parallel executing...` + `Build succeeded`. No errors. No `UObject` regeneration warnings.

- [ ] **Step 3: Relaunch Editor; verify Python visibility**

In the UE Editor Output Log → Python console, run:

```python
import unreal
help(unreal.PostRenderToolBuildHelper)
```

Expected: `help` prints a class description listing `ensure_root_panel`, `find_widget_by_name`, `ensure_widget_under_parent` (3 UFUNCTIONs total — `SetWidgetIsVariable` and `GetPanelSlot` are not present; see plan Architecture notes for why).

If `AttributeError: module 'unreal' has no attribute 'PostRenderToolBuildHelper'` — rebuild didn't take; check UBT output for errors.

- [ ] **Step 4: (No commit for this task — validation-only)**

---

### Task 10: Implement Build Orchestrator

**Files:**
- Create: `Content/Python/post_render_tool/build_widget_blueprint.py`

- [ ] **Step 1: Write the orchestrator**

Create `Content/Python/post_render_tool/build_widget_blueprint.py`:

```python
"""Populate BP_PostRenderToolWidget from docs/widget-tree-spec.json.

Usage inside the UE Editor Python console:

    from post_render_tool import build_widget_blueprint
    build_widget_blueprint.run_build()

Idempotent — safe to re-run. Existing widgets (identified by name, anywhere
in the tree) are left untouched; the script only:
  - creates the root panel if the tree is empty,
  - creates widgets that are declared in the spec but missing from the tree,
  - applies widget/slot properties ONLY on freshly-created widgets
    (preserving user tweaks on already-existing widgets).

After any C++ contract change (UPROPERTY(BindWidget) added/removed), rerun
this script to regenerate the missing bindings; old ones remain intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import unreal

from . import spec_loader, widget_properties


DEFAULT_SPEC_PATH = "docs/widget-tree-spec.json"


def _plugin_root() -> Path:
    """Resolve the plugin root (where PostRenderTool.uplugin lives).

    sys.path contains Content/Python; walk up two levels.
    """
    here = Path(__file__).resolve().parent  # .../Content/Python/post_render_tool
    return here.parent.parent.parent         # plugin root


def _resolve_spec_path(spec_path: Optional[str]) -> str:
    if spec_path:
        return spec_path
    return str(_plugin_root() / DEFAULT_SPEC_PATH)


def _load_blueprint(asset_path: str) -> "unreal.WidgetBlueprint":
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if bp is None:
        raise RuntimeError(
            f"Cannot load widget blueprint at '{asset_path}'. "
            "Create it first via Content Browser → Blueprint Class → "
            "PostRenderToolWidget, or see deployment-guide.md §1.3."
        )
    if not isinstance(bp, unreal.WidgetBlueprint):
        raise RuntimeError(
            f"Asset '{asset_path}' is {type(bp).__name__}, expected WidgetBlueprint."
        )
    return bp


def _build_node(bp, parent_widget, node: dict) -> None:
    """Recursive builder for a single spec node + its children."""
    widget_type = node["type"]
    name = node["name"]
    role = node["role"]
    widget_cls = widget_properties.WIDGET_CLASS_MAP.get(widget_type)
    if widget_cls is None:
        unreal.log_error(f"[build_widget_blueprint] unknown type {widget_type!r} for {name}")
        return

    # Python unreal.* classes expose the UE Class via static_class() — the
    # C++ helper expects TSubclassOf<UWidget>.
    try:
        cls_obj = widget_cls.static_class()
    except AttributeError:
        cls_obj = widget_cls  # some stubs / alt bindings

    # UFUNCTION returns (result_enum, out_widget, out_slot) as a tuple per PyGenUtil
    # out-param contract; see plan Architecture notes.
    result, widget, slot = unreal.PostRenderToolBuildHelper.ensure_widget_under_parent(
        bp, unreal.Name(name), cls_obj, parent_widget
    )

    if result == unreal.EnsureWidgetResult.TYPE_MISMATCH:
        raise RuntimeError(
            f"Widget '{name}' exists but type mismatches; abort. "
            f"Delete the widget in Designer then rerun, or rename the spec entry."
        )
    if result == unreal.EnsureWidgetResult.INVALID_INPUT:
        raise RuntimeError(f"Invalid input for widget '{name}' — check parent / class.")
    if result == unreal.EnsureWidgetResult.PARENT_CANNOT_HOLD_CHILDREN:
        raise RuntimeError(
            f"Parent of '{name}' cannot hold children — spec tree invalid."
        )

    is_newly_created = (result == unreal.EnsureWidgetResult.CREATED)

    # Apply properties ONLY on newly-created widgets (preserve user tweaks).
    # Widget.cpp:195 sets bIsVariable=true on every new widget by default — no
    # explicit call needed to make contract widgets Variable. Decorative widgets
    # inherit the same default (minor overhead; accepted trade-off).
    if is_newly_created:
        props = node.get("properties") or {}
        if props:
            widget_properties.apply_widget_properties(widget, props)

        slot_props = node.get("slot") or {}
        if slot_props and slot is not None:
            widget_properties.apply_slot_properties(slot, slot_props)

    # Recurse into children regardless of whether this widget was new or old.
    for child in node.get("children") or []:
        _build_node(bp, widget, child)


def run_build(spec_path: Optional[str] = None,
              *, save: bool = True,
              compile_bp: bool = True) -> "unreal.WidgetBlueprint":
    """Top-level entry — load spec, walk tree, save BP."""
    spec_path = _resolve_spec_path(spec_path)
    unreal.log(f"[build_widget_blueprint] loading spec from {spec_path}")

    spec = spec_loader.load_spec(spec_path)
    errors = spec_loader.validate_spec(spec)
    if errors:
        raise RuntimeError("Spec validation failed:\n" + "\n".join(errors))

    asset_path = spec["blueprint"]["asset_path"]
    bp = _load_blueprint(asset_path)

    # Ensure root panel.
    root_panel_spec = spec["blueprint"]["root_panel"]
    root_cls = widget_properties.WIDGET_CLASS_MAP[root_panel_spec["type"]]
    try:
        root_cls_obj = root_cls.static_class()
    except AttributeError:
        root_cls_obj = root_cls
    root = unreal.PostRenderToolBuildHelper.ensure_root_panel(
        bp, unreal.Name(root_panel_spec["name"]), root_cls_obj
    )
    if root is None:
        raise RuntimeError(
            "Could not ensure root panel — see UE Output Log for the "
            "root-widget-type-mismatch warning."
        )

    # Walk root_children under the root panel.
    for child_spec in spec.get("root_children") or []:
        _build_node(bp, root, child_spec)

    if compile_bp:
        unreal.log("[build_widget_blueprint] compiling blueprint…")
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)

    if save:
        unreal.log(f"[build_widget_blueprint] saving {asset_path}")
        unreal.EditorAssetLibrary.save_asset(asset_path)

    unreal.log("[build_widget_blueprint] done.")
    return bp
```

- [ ] **Step 2: Commit**

```bash
git add Content/Python/post_render_tool/build_widget_blueprint.py
git commit -m "feat(python): 新增 build_widget_blueprint 编排器 — JSON → BP (idempotent)"
```

---

### Task 11: Write Drift-Detector Test

**Why:** The same widget names appear in three places: `PostRenderToolWidget.h` UPROPERTY decls, `widget.py` tuples, and `widget-tree-spec.json`. A rename that misses one is a silent binding drift. This test makes the drift loud.

**Files:**
- Create: `Content/Python/post_render_tool/tests/test_spec_drift.py`

- [ ] **Step 1: Write the drift test**

Create `Content/Python/post_render_tool/tests/test_spec_drift.py`:

```python
"""Cross-check widget names across C++ header, widget.py, and JSON spec."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Set

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
from spec_loader import load_spec, collect_contract_names  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]


def _parse_cpp_uproperty_names() -> tuple[Set[str], Set[str]]:
    """Extract BindWidget / BindWidgetOptional names from PostRenderToolWidget.h."""
    header = REPO_ROOT / "Source/PostRenderTool/Public/PostRenderToolWidget.h"
    text = header.read_text(encoding="utf-8")

    # Match:
    #   UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    #   U<SomeClass>* name;
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


def _parse_widget_py_tuples() -> tuple[Set[str], Set[str]]:
    widget_py = REPO_ROOT / "Content/Python/post_render_tool/widget.py"
    text = widget_py.read_text(encoding="utf-8")

    def _extract_tuple(var_name: str) -> Set[str]:
        m = re.search(rf"{var_name}\s*=\s*\(([^)]*)\)", text, re.DOTALL)
        if not m:
            return set()
        body = m.group(1)
        names = re.findall(r'"([a-zA-Z_][a-zA-Z0-9_]*)"', body)
        return set(names)

    return _extract_tuple("_REQUIRED_CONTROLS"), _extract_tuple("_OPTIONAL_CONTROLS")


def _parse_json_contract_names() -> tuple[Set[str], Set[str]]:
    spec_path = REPO_ROOT / "docs/widget-tree-spec.json"
    spec = load_spec(str(spec_path))
    req, opt, _ = collect_contract_names(spec)
    return req, opt


def test_required_names_match_across_three_sources():
    cpp_req, _ = _parse_cpp_uproperty_names()
    py_req, _ = _parse_widget_py_tuples()
    json_req, _ = _parse_json_contract_names()

    if not (cpp_req == py_req == json_req):
        diffs = []
        diffs.append(f"C++ - widget.py: {sorted(cpp_req - py_req)}")
        diffs.append(f"widget.py - C++: {sorted(py_req - cpp_req)}")
        diffs.append(f"C++ - JSON: {sorted(cpp_req - json_req)}")
        diffs.append(f"JSON - C++: {sorted(json_req - cpp_req)}")
        assert False, "Required name drift detected:\n" + "\n".join(diffs)


def test_optional_names_match_across_three_sources():
    _, cpp_opt = _parse_cpp_uproperty_names()
    _, py_opt = _parse_widget_py_tuples()
    _, json_opt = _parse_json_contract_names()

    if not (cpp_opt == py_opt == json_opt):
        diffs = []
        diffs.append(f"C++ - widget.py: {sorted(cpp_opt - py_opt)}")
        diffs.append(f"widget.py - C++: {sorted(py_opt - cpp_opt)}")
        diffs.append(f"C++ - JSON: {sorted(cpp_opt - json_opt)}")
        diffs.append(f"JSON - C++: {sorted(json_opt - cpp_opt)}")
        assert False, "Optional name drift detected:\n" + "\n".join(diffs)


def test_required_count_is_33():
    _, _ = _parse_cpp_uproperty_names()
    json_req, _ = _parse_json_contract_names()
    assert len(json_req) == 33, f"Required count drift: {len(json_req)} != 33"


def test_optional_count_is_8():
    _, json_opt = _parse_json_contract_names()
    assert len(json_opt) == 8, f"Optional count drift: {len(json_opt)} != 8"
```

- [ ] **Step 2: Run the drift tests — all should pass**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python -m pytest post_render_tool/tests/test_spec_drift.py -v
```

Expected: 4 passed. If any drift is reported, align all three sources before continuing.

- [ ] **Step 3: Commit**

```bash
git add Content/Python/post_render_tool/tests/test_spec_drift.py
git commit -m "test: 新增 spec_drift 交叉校验（C++ header / widget.py / JSON 三方同步）"
```

---

### Task 12: Add Toolbar Menu Entry for "Rebuild from Spec"

**Why:** Users shouldn't need to open the Python console to rerun the build. Adding a button to the existing toolbar registration makes iteration fast.

**Files:**
- Modify: `Content/Python/post_render_tool/widget_builder.py`

- [ ] **Step 1: Read current widget_builder.py to find menu registration point**

```bash
grep -n "def register_menu_entries\|def open_widget\|def rebuild_widget\|ToolMenus" /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python/post_render_tool/widget_builder.py
```

Note the line number of the menu registration function (or the public `open_widget` / `rebuild_widget` entries).

- [ ] **Step 2: Add `rebuild_from_spec()` function**

Append to `Content/Python/post_render_tool/widget_builder.py` (after `rebuild_widget()`):

```python
def rebuild_from_spec():
    """Re-populate BP_PostRenderToolWidget from docs/widget-tree-spec.json.

    Idempotent: existing widgets (with user tweaks) are preserved; only missing
    contract widgets are added. After C++ UPROPERTY changes, full Editor
    restart + plugin rebuild is still required — this command only operates on
    the WidgetBlueprint asset, not the reflection metadata.
    """
    from . import build_widget_blueprint
    bp = build_widget_blueprint.run_build()
    rebuild_widget()
    return bp
```

- [ ] **Step 3: If the module has a toolbar/menu registration, add the entry there**

Locate the menu registration function (typically named `register_menu_entries` or similar). Inside it, alongside existing `open_widget` / `rebuild_widget` entries, add:

```python
# Inside the menu registration body — pattern will vary, adapt to existing style.
menu.add_menu_entry(
    section_name="PostRenderTool",
    entry=unreal.ToolMenuEntry(
        name="RebuildFromSpec",
        type=unreal.MultiBlockType.MENU_ENTRY,
        script_string_command="from post_render_tool import widget_builder; widget_builder.rebuild_from_spec()",
        label="Rebuild from Spec",
        tool_tip="Sync BP from docs/widget-tree-spec.json (idempotent)",
    ),
)
```

If the existing `widget_builder.py` does NOT register toolbar entries (toolbar is in C++ module), skip this step — `rebuild_from_spec()` is callable from the Python console.

- [ ] **Step 4: Smoke-test syntax**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python3 -c "import ast; ast.parse(open('post_render_tool/widget_builder.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add Content/Python/post_render_tool/widget_builder.py
git commit -m "feat(python): widget_builder 新增 rebuild_from_spec() 入口"
```

---

### Task 13: Manual Integration Test — Generate BP from Empty Asset

**Why:** Pure-Python tests cannot verify that the real WidgetTree is populated. This is the golden-path manual test.

**Files:** none; this task exercises the real Editor.

- [ ] **Step 1: Prepare test environment**

Option A — **destructive rebuild** (recommended for first integration):
1. In the Editor, Content Browser → navigate to `/PostRenderTool/Blueprints/`.
2. Delete `BP_PostRenderToolWidget` (Delete key → Force Delete).
3. Right-click → Blueprint Class → choose `PostRenderToolWidget` parent.
4. Name the new asset `BP_PostRenderToolWidget`.
5. Double-click to open; DO NOT drag any widget — leave it empty.
6. Save + close the editor tab (keep Editor running).

Option B — **idempotent rerun** (after first bootstrap):
Skip deletion; the script preserves existing widgets.

- [ ] **Step 2: Run the build from the Python console**

```python
from post_render_tool import build_widget_blueprint
bp = build_widget_blueprint.run_build()
```

Expected Output Log:
- `[build_widget_blueprint] loading spec from …/widget-tree-spec.json`
- `[build_widget_blueprint] compiling blueprint…`
- `[build_widget_blueprint] saving /PostRenderTool/Blueprints/BP_PostRenderToolWidget`
- `[build_widget_blueprint] done.`

NO `[widget_properties] ...` error lines. If warnings appear for specific properties, investigate — reconstruction should be clean.

- [ ] **Step 3: Verify BP in Designer**

1. Double-click `BP_PostRenderToolWidget` to open it.
2. **Hierarchy** panel should show the nested tree matching `bindwidget-contract.md` §5:
   - `RootPanel` (VerticalBox)
     - `lbl_root_scroll` (ScrollBox)
       - `lbl_sections` (VerticalBox)
         - `lbl_card_prereq` (Border)
         - `lbl_card_csv_file` (Border)
         - `lbl_card_csv_preview` (Border)
         - `lbl_card_coord` (Border)
         - `lbl_card_axis` (Border)
         - `lbl_card_actions` (Border)
3. Expand each Border → verify Section header (SizeBox + Image orange accent + TextBlock title) and body widgets are present.
4. **Count check:** the contract widgets must number 33 required + 8 optional = 41. Use the drift-test counts.
5. Click `btn_browse` → Details panel → verify `Is Variable` is ✓ checked.
6. Click `lbl_csv_file_title` → verify Text = "CSV File".
7. **Compile** (Ctrl+B): expect "Compile Succeeded" with no `A required widget binding "X" of type Y was not found` errors.
8. **Save** (Ctrl+S).

- [ ] **Step 4: Launch the tool and verify UI**

```python
import init_post_render_tool
```

Expected: a tab opens showing the 6 sections with correct layout + colors matching Figma. Click `btn_browse` — file dialog opens (business logic is unchanged; this verifies the BindWidget contract works end-to-end).

- [ ] **Step 5: Idempotency rerun**

```python
build_widget_blueprint.run_build()
```

Expected: `AlreadyExisted` for all 41 contract widgets (implicit — no new widgets reported); BP dirty flag should NOT raise. Reopen the BP → hierarchy unchanged.

- [ ] **Step 6: Tweak + rerun preservation**

1. In Designer, manually change the color of `btn_import` background to a wild purple (deliberately non-spec color).
2. Save the BP.
3. Run `build_widget_blueprint.run_build()` again.
4. Reopen BP → `btn_import` should STILL be purple. The spec's default isn't re-applied because the widget already exists.

If any of the above fails, document the failure mode precisely and add a new Task to fix, before marking this Task complete.

- [ ] **Step 7: Commit the validated BP asset**

```bash
git add Content/Blueprints/BP_PostRenderToolWidget.uasset
git commit -m "feat(bp): 通过 build_widget_blueprint 生成 BP_PostRenderToolWidget（Figma 1:1）"
```

---

### Task 14: Create Bootstrap Checklist (Option 3 — Manual Fallback)

**Why:** When the C++ helper isn't built yet (freshly cloned repo, first bootstrap), the automation cannot run. The checklist is the tight manual procedure.

**Files:**
- Create: `docs/bootstrap-checklist.md`

- [ ] **Step 1: Write the checklist**

Create `docs/bootstrap-checklist.md`:

````markdown
# Manual Bootstrap Checklist — BP_PostRenderToolWidget

For when `build_widget_blueprint.py` is unavailable (freshly cloned repo without rebuilt C++ module, or the helper asset is broken). Follows `bindwidget-contract.md` §5 in condensed form.

**Prefer automation when possible.** The script at `Content/Python/post_render_tool/build_widget_blueprint.py` handles everything this checklist covers, plus property application. Only fall back to this doc if the plugin hasn't been rebuilt yet.

---

## Prerequisites

- [ ] UE Editor launched, host project loaded with PostRenderTool plugin enabled
- [ ] `Content Browser → VP Post-Render Tool Content → Blueprints/` visible
- [ ] `docs/bindwidget-contract.md` open alongside (reference for 41 names)
- [ ] `docs/codebase-walkthrough.html` open at `#ui` for visual reference

---

## Phase A — Blueprint shell (2 min)

- [ ] Right-click in `Blueprints/` → Blueprint Class
- [ ] Bottom "ALL CLASSES" → search `PostRenderToolWidget`
- [ ] Select `UPostRenderToolWidget` → Select
- [ ] Name: `BP_PostRenderToolWidget` (exact)
- [ ] Double-click to open

---

## Phase B — Root panel (1 min)

- [ ] Hierarchy panel → delete default `CanvasPanel_0`
- [ ] Palette → drag `Vertical Box` to Hierarchy as new root → rename `RootPanel`

---

## Phase C — 33 required widgets (flat, fast pass; ~8 min)

Drag each widget into `RootPanel`. Names must match exactly (copy-paste from `bindwidget-contract.md` §3.1).

- [ ] `btn_recheck` — Button
- [ ] `btn_browse` — Button
- [ ] `txt_file_path` — Text Block
- [ ] `txt_frame_count` — Text Block
- [ ] `txt_focal_range` — Text Block
- [ ] `txt_timecode` — Text Block
- [ ] `txt_sensor_width` — Text Block
- [ ] `spn_fps` — Spin Box
- [ ] `txt_detected_fps` — Text Block
- [ ] `spn_frame` — Spin Box
- [ ] `txt_designer_pos` — Text Block
- [ ] `txt_designer_rot` — Text Block
- [ ] `txt_ue_pos` — Text Block
- [ ] `txt_ue_rot` — Text Block
- [ ] `btn_spawn_cam` — Button
- [ ] `cmb_pos_x_src` — Combo Box (String)
- [ ] `spn_pos_x_scale` — Spin Box
- [ ] `cmb_pos_y_src` — Combo Box (String)
- [ ] `spn_pos_y_scale` — Spin Box
- [ ] `cmb_pos_z_src` — Combo Box (String)
- [ ] `spn_pos_z_scale` — Spin Box
- [ ] `cmb_rot_pitch_src` — Combo Box (String)
- [ ] `spn_rot_pitch_scale` — Spin Box
- [ ] `cmb_rot_yaw_src` — Combo Box (String)
- [ ] `spn_rot_yaw_scale` — Spin Box
- [ ] `cmb_rot_roll_src` — Combo Box (String)
- [ ] `spn_rot_roll_scale` — Spin Box
- [ ] `btn_apply_mapping` — Button
- [ ] `btn_save_mapping` — Button
- [ ] `btn_import` — Button
- [ ] `btn_open_seq` — Button
- [ ] `btn_open_mrq` — Button
- [ ] `txt_results` — Editable Text (Multi-Line)

For each: Details panel → confirm **Is Variable** ✓ (default; do NOT uncheck).

- [ ] Compile (Ctrl+B) — must show "Compile Succeeded" with no `A required widget binding "X" of type Y was not found`
- [ ] Save (Ctrl+S)

---

## Phase D — 8 optional widgets (2 min)

All are `Text Block`:

- [ ] `prereq_label_0`
- [ ] `prereq_label_1`
- [ ] `prereq_label_2`
- [ ] `prereq_label_3`
- [ ] `prereq_label_4`
- [ ] `prereq_label_5`
- [ ] `prereq_summary`
- [ ] `txt_frame_hint`

Default Text = empty string (see `bindwidget-contract.md` §5.1 warning).

- [ ] Compile + Save

---

## Phase E — Visual layout (per Figma)

Reference: `docs/codebase-walkthrough.html#ui` (left panel mock) + `bindwidget-contract.md` §5.3–5.9 (trees).

For each Section, create this nesting in Hierarchy:

```
Border [Section card]
├─ VerticalBox
│  ├─ HorizontalBox [Header: accent + title]
│  │  ├─ SizeBox 3×13 → Image (Tint = #E8704D)
│  │  └─ TextBlock "Section title"
│  └─ <body widgets from contract>
```

**Default values** (copy into Details panel):

| Border | BrushColor = `(0.141, 0.141, 0.141, 1.0)`, Padding = `12,10,12,10` |
|---|---|
| SizeBox (accent) | W=3, H=13, Slot Padding=`0,0,8,0`, VAlign=Center |
| Image (accent) | Brush → Tint `(0.909, 0.439, 0.302, 1.0)`, Image Size `(3, 13)`, Draw As = Box |
| Section title TextBlock | Text = literal (e.g. `"CSV File"`), Slot VAlign=Center |
| Button | Slot Padding around child TextBlock = `14,6,14,6` |

- [ ] All 6 Sections have their accent stripe + title
- [ ] All contract widgets are inside their correct Section
- [ ] No widget was renamed during layout (names must match §3.1)
- [ ] Compile + Save

---

## Phase F — Submit

- [ ] Content Browser → right-click `BP_PostRenderToolWidget` → Submit (or `git add` + commit)
- [ ] Verify the `.uasset` appears in the staged files
- [ ] Commit message: `feat(bp): 手动 bootstrap BP_PostRenderToolWidget`

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `A required widget binding "X" of type Y was not found` | Missing widget / typo'd Name | Add missing widget, verify Name matches exactly |
| Widget exists but Python returns None | Unchecked `Is Variable` | Check the box, recompile |
| Tool opens blank | Root panel not compatible or BP not compiled | Phase B + Ctrl+B |
| Color looks wrong | Linear vs sRGB confusion in RGBA value | Use Linear values listed above (already converted) |

For deep debugging, see `docs/bindwidget-contract.md` §9 Failure modes.
````

- [ ] **Step 2: Commit**

```bash
git add docs/bootstrap-checklist.md
git commit -m "docs: 新增 bootstrap-checklist.md — 无自动化时的手动搭建清单"
```

---

### Task 15: Rewrite deployment-guide.md §1.3

**Why:** The deployment guide currently describes manual bootstrap as the only path. Now that automation exists, it should be primary.

**Files:**
- Modify: `docs/deployment-guide.md` lines 34–122 (§1.3)

- [ ] **Step 1: Rewrite §1.3 body**

Replace the content of §1.3 (between the `### 1.3 ...` heading line and the `### 1.4 启动工具` heading) with:

```markdown
### 1.3 首次 Bootstrap：创建 Blueprint 资产（**只做一次**，不是每个部署都要做）

> **谁应该走这一节（按场景选恢复命令，别走错）：**
>
> | 场景 | 你该做什么 | git 命令 | p4 命令 |
> |---|---|---|---|
> | **A. 全新 clone / 从未拿过这个 asset** —— 团队已有人 bootstrap，你是新机器/新同事 | 初次拉取 | `git pull` | `p4 sync` |
> | **B. 本地曾有但被删 / 损坏，depot 还健康** —— 误 `rm`、merge 冲突选错、cache 损坏 | 恢复工作区 | `git restore Content/Blueprints/BP_PostRenderToolWidget.uasset` | `p4 sync -f //.../BP_PostRenderToolWidget.uasset` |
> | **C. depot 里也没有 / 项目从未 bootstrap** —— 全新仓库、或 depot 副本也丢了 | 走本节 自动化或手工路径 | Phase 最终的 `git add` + `commit` | Phase 最终的 `p4 add` + `submit` |

**推荐路径 —— 自动化**（需要 plugin 已编译：`unreal.PostRenderToolBuildHelper` 对 Python 可见）：

1. 在 Content Browser 右键 → Blueprint Class → ALL CLASSES 搜 `PostRenderToolWidget` → 选父类 → 命名 `BP_PostRenderToolWidget` → Save（空壳即可）
2. UE Python 控制台：

   ```python
   from post_render_tool import build_widget_blueprint
   build_widget_blueprint.run_build()
   ```

3. 脚本读取 `docs/widget-tree-spec.json`，把 41 个契约 widget + 装饰结构一次性填入 BP，应用属性、slot padding、颜色，compile + save
4. 打开 BP 校验：6 个 Section 全部出现、`Compile Succeeded`
5. 继续 Step "美化" —— 在 Designer 里按 Figma 微调（脚本 rerun 不会回滚你的美化，idempotent 契约见 `build_widget_blueprint.py` 顶部注释）
6. 提交 `.uasset`

**备份路径 —— 手动**（plugin 尚未编译、或 C++ helper 不可用）：

走 `docs/bootstrap-checklist.md` 的 Phase A–F —— 流程快照 ~15 分钟。

**历史决策与回退理由（存档）：** 2026-04-11 commit `bd140d7` 曾删除 Python 自动化走纯手动路径，原因见该 commit message 和早期的 `docs/superpowers/plans/2026-04-11-blueprint-ui-autogen.md`。2026-04-17 commit `<本次>` 以基于 JSON spec + idempotent rerun + 1:1 Figma 的目标重新启用自动化；新版把"属性 + slot 布局"也纳入脚本范围（旧版只补 widget 本体）。这让后续 C++ 契约变更只需重跑脚本（而非重拖 41 个 widget）。

**技术背景：** UE 5.7 `UWidgetBlueprint::WidgetTree` 是 `UPROPERTY(Instanced)`，Python 反射看不到 —— 所以脚本走 `UPostRenderToolBuildHelper` C++ 桥接（3 个 `BlueprintCallable` UFUNCTION）。这个桥接是最小可行集：find / construct / mark-variable / get-slot。其余（属性应用、编译、保存）全在 Python 里，用 Python 原生 `unreal.EditorAssetLibrary` / `unreal.BlueprintEditorLibrary`。
```

- [ ] **Step 2: Verify the rewrite**

```bash
grep -A 2 "### 1.3" /Users/bip.lan/AIWorkspace/vp/post_render_tool/docs/deployment-guide.md | head -10
grep "build_widget_blueprint.run_build" /Users/bip.lan/AIWorkspace/vp/post_render_tool/docs/deployment-guide.md
```

Expected: the §1.3 heading + the Python snippet are present.

- [ ] **Step 3: Commit**

```bash
git add docs/deployment-guide.md
git commit -m "docs(deployment): 重写 §1.3 —— 自动化为主路径，手动为备份"
```

---

### Task 16: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add build commands section**

Find the `## Commands` section in `CLAUDE.md` and append after the existing `# UE Python console — widget management` block:

```markdown
# UE Python console — rebuild BP from JSON spec (idempotent)
from post_render_tool import build_widget_blueprint
build_widget_blueprint.run_build()

# Cross-check widget names across C++ / widget.py / JSON spec
cd Content/Python && python -m pytest post_render_tool/tests/test_spec_drift.py -v
```

- [ ] **Step 2: Add architecture note**

In the `## Architecture` section, append after the "Runtime flow:" block:

```markdown
**Build flow (Designer bootstrap):**
1. `docs/widget-tree-spec.json` declares the full WidgetTree (41 contract + decorative nesting)
2. `build_widget_blueprint.run_build()` parses spec → calls `UPostRenderToolBuildHelper` (C++ bridge) to mutate `UWidgetBlueprint.WidgetTree` (Python cannot touch WidgetTree directly — `UPROPERTY(Instanced)`, no `BlueprintReadable`)
3. `widget_properties.apply_widget_properties/apply_slot_properties` sets per-widget and slot-layout values via reflection
4. `unreal.BlueprintEditorLibrary.compile_blueprint` + `unreal.EditorAssetLibrary.save_asset` persist the `.uasset`
5. Idempotent: rerun only creates missing widgets; existing ones (possibly user-tweaked in Designer) are left untouched. Properties/slot are applied ONLY on fresh creation — user edits survive.
```

- [ ] **Step 3: Add Gotcha**

In the `## Gotchas` section, append:

```markdown
- **JSON spec is source of truth for widget hierarchy + properties.** Always edit `docs/widget-tree-spec.json` first, then re-run `build_widget_blueprint.run_build()`. Three-way drift (C++ UPROPERTY / widget.py tuples / JSON) is detected by `tests/test_spec_drift.py`.
- **C++ UFUNCTION additions require full Editor restart + plugin rebuild.** Live Coding does NOT register new UFUNCTIONs. After changing `PostRenderToolBuildHelper.h`, follow deployment-guide.md Task 9 sequence before `run_build()` sees the new API.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): 记录 build_widget_blueprint + drift detector + JSON spec 真相来源"
```

---

### Task 17: Update bindwidget-contract.md Cross-Links

**Files:**
- Modify: `docs/bindwidget-contract.md`

- [ ] **Step 1: Append §11 cross-link block**

At the end of `docs/bindwidget-contract.md` (after §10 故障排除), append:

```markdown

---

## 11. 与自动化的关系

本文档（human-readable 契约 + 填写手册）和机器可读的 `docs/widget-tree-spec.json` 是两份**并行**资料，互为校验：

| 用途 | 本文档 | widget-tree-spec.json |
|---|---|---|
| 人读 / 教学 | ✅ 主 | ❌ |
| 机器处理 / 脚本消费 | ❌ | ✅ 主 |
| 契约名列表 | §3.1 / §3.2 表格 | 根据 `role` 字段遍历 |
| 装饰件建议命名 | §4.2 `lbl_` 前缀 | 与本文档一致 |
| 填写默认值 | §5.4–5.9 表格 | 各节点 `properties` 字段 |
| 层级关系 | §5.4–5.9 ASCII 树 | 嵌套 `children` 数组 |

**三方 drift 由测试把关**：`Content/Python/post_render_tool/tests/test_spec_drift.py` 对比 `PostRenderToolWidget.h` UPROPERTY 名、`widget.py` tuples、`widget-tree-spec.json` contract 名 —— 任何一处漂移都会让测试红。本文档作为人读文档不在自动 drift 校验范围，但**改动三方中任一**时**请也更新本文档 §3 / §5 对应条目**。

**如何用 JSON 自动生成 BP**：见 `docs/deployment-guide.md` §1.3 推荐路径。
```

- [ ] **Step 2: Commit**

```bash
git add docs/bindwidget-contract.md
git commit -m "docs(contract): 新增 §11 描述与 widget-tree-spec.json / drift detector 的关系"
```

---

### Task 18: Update Memory

**Files:**
- Modify: `~/.claude/projects/-Users-bip-lan-AIWorkspace-vp-post-render-tool/memory/feedback_no_python_bp_automation.md`
- Modify: `~/.claude/projects/-Users-bip-lan-AIWorkspace-vp-post-render-tool/memory/MEMORY.md`

- [ ] **Step 1: Rewrite the feedback file**

Overwrite `~/.claude/projects/-Users-bip-lan-AIWorkspace-vp-post-render-tool/memory/feedback_no_python_bp_automation.md` with:

```markdown
---
name: BP automation is the primary bootstrap path (decision reopened 2026-04-17)
description: JSON spec + C++ bridge + Python builder is now primary; Designer is for fallback + iterative tweaks
type: feedback
---

The prior "don't propose Python/C++ helpers to auto-populate BP_PostRenderToolWidget" guidance (recorded after commit bd140d7) is **REVERSED as of 2026-04-17**.

**Why:** User reopened the decision. Their actual workflow is "automated bootstrap + Designer二次调整", not pure manual. With the JSON spec owning properties + slot layout (not just widget names), rerun gives Figma 1:1 parity and is idempotent on user tweaks. The C++ helper is minimal (3 UFUNCTIONs wrapping WidgetTree ops); the `ac8b918` + `9788e5e` history provides 70–80% of the revival code.

**How to apply:**
- Primary path: `build_widget_blueprint.run_build()` reads `docs/widget-tree-spec.json` and populates `BP_PostRenderToolWidget.uasset`.
- Drift check: `tests/test_spec_drift.py` enforces `.h` / `widget.py` / `widget-tree-spec.json` name alignment.
- When C++ contract changes (add/remove UPROPERTY(BindWidget)): update header → rebuild plugin → update JSON spec → update `widget.py` tuples → rerun `run_build()` to append missing widgets to BP → commit `.uasset` + all sources.
- Fallback manual path: `docs/bootstrap-checklist.md`. Used when plugin isn't rebuilt yet or C++ helper unavailable.
- Designer is still the iteration surface for visual polish (colors, padding, alignment tweaks) — script never clobbers existing widget properties on rerun.

Do NOT propose:
- Removing the JSON spec in favor of widget.py constants (regression).
- Replacing the C++ bridge with a pure-Python implementation (UWidgetBlueprint::WidgetTree is `UPROPERTY(Instanced)`, invisible to Python reflection — fundamentally blocked).
```

- [ ] **Step 2: Update MEMORY.md pointer line**

Read the current pointer line in MEMORY.md:

```bash
grep "python_bp_automation" ~/.claude/projects/-Users-bip-lan-AIWorkspace-vp-post-render-tool/memory/MEMORY.md
```

Replace it with:

```
- [BP automation is the primary bootstrap path](feedback_no_python_bp_automation.md) — JSON spec + C++ bridge revived 2026-04-17; Designer = fallback + polish surface
```

- [ ] **Step 3: (Memory files are not tracked in git — no commit needed)**

---

### Task 19: Final Verification & Summary

**Files:** none modified.

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python -m pytest post_render_tool/tests/ -v
```

Expected: all tests pass (`test_spec_loader.py` 12 passed, `test_widget_properties.py` 9 passed, `test_spec_drift.py` 4 passed) = **25 total**.

- [ ] **Step 2: Git log review**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git log --oneline -20
```

Verify the expected commits are present (schema, spec, loader, props, C++ header/impl, orchestrator, drift test, toolbar entry, checklist, deployment guide, CLAUDE.md, contract §11).

- [ ] **Step 3: Verify p4 depot sync**

```bash
tail -5 .git/p4-push.log
```

Expected: each commit shows `✓ <branch> pushed to p4`.

- [ ] **Step 4: Summary**

Report to the user:
- Number of new files created
- Number of files modified
- Test counts passing
- Manual Editor validation status (from Task 13)
- Commit range hash → hash

---

## Self-Review Checklist

Performed at plan-authoring time to catch spec-gap and type-drift before handing off.

- **Spec coverage:**
  - Option 1 (automation) → Tasks 1–13 produce JSON spec, C++ bridge, Python builder, drift detector, toolbar, integration test, BP asset commit. ✅
  - Option 3 (checklist) → Task 14 produces `bootstrap-checklist.md`. ✅
  - Documentation updates → Tasks 15–17 (deployment-guide, CLAUDE.md, contract §11). ✅
  - Memory revision → Task 18. ✅

- **Placeholder scan:**
  - "TBD" / "fill in later" → none present. ✅
  - "Add appropriate error handling" → none; Tasks specify `unreal.log_warning` + skip vs raise behavior. ✅
  - "Write tests for the above" without code → all test code is inline. ✅
  - "Similar to Task N" repeating code → none; each test file is complete. ✅

- **Type consistency:**
  - `WIDGET_CLASS_MAP` referenced in Tasks 5, 6, 10 → same keys as `spec_loader.ALL_TYPES`. ✅
  - `EEnsureWidgetResult` enum values referenced in C++ (Task 7) + Python (Task 10) → Python uses `unreal.EnsureWidgetResult.{CREATED,ALREADY_EXISTED,TYPE_MISMATCH,INVALID_INPUT,PARENT_CANNOT_HOLD_CHILDREN}` (snake-case upper from UE5 Python enum conversion per `PyGenUtil.cpp:2893,2908-2910`). ✅
  - `apply_widget_properties` / `apply_slot_properties` signatures match between tests (Task 5), implementation (Task 6), and use (Task 10). ✅
  - `run_build(spec_path=None, *, save=True, compile_bp=True)` entry matches `rebuild_from_spec()` caller in Task 12. ✅
  - `EnsureWidgetUnderParent` C++ out-params (`UWidget*& OutWidget, UPanelSlot*& OutSlot`) → Python tuple `(result, widget, slot)` in Task 10 orchestrator. ✅

- **Known caveats:**
  - Task 4 uses `$ref` / `$args` as **authoring placeholders only** — they are NOT resolved by the loader. The plan explicitly states to inline them. An engineer reading only Task 4 would assemble the full JSON by hand; Task 11's drift test + Task 13's compile catch errors.
  - Task 8's C++ uses `FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint)` (confirmed via `BlueprintEditorUtils.h:304-314`). This replaces the naive `Blueprint->Modify()` that the old `ac8b918` code used — widget tree structural changes need full BP recompile signaling, not just Undo marking.
  - Task 7's helper does NOT include `SetWidgetIsVariable` — `UWidget::bIsVariable` (`Widget.h:318`) is a private bitfield inaccessible to business modules. The constructor (`Widget.cpp:195`) initializes it to `true` by default, which satisfies BindWidget contract for required/optional widgets. Decorative widgets also become Variable — accepted as harmless overhead. Task 13 Step 3 verifies this works end-to-end (Is Variable checkbox shows ✓ + Python reflection succeeds).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-17-widget-blueprint-automation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development` skill. Best for a plan this size because each task has clear entry / exit, and reviewing per-task is faster than threading a 1700-line plan through a single session.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review. Faster iteration if your preference is to stay in one context window, but risks polluting context as the session grows.

**Which approach?**
