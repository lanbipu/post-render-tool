# CLAUDE.md

## Project Overview

VP Post-Render Tool: Disguise Designer CSV Dense → UE 5.7 CineCameraActor + LensFile + LevelSequence.
Python scripts for UE Editor, no external dependencies.

## Commands

```bash
# Unit tests (pure Python, no UE needed)
cd Content/Python && python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -v

# Syntax check for UE-dependent modules
for f in post_render_tool/{lens_file_builder,camera_builder,sequence_builder,pipeline,ui_interface}.py; do
  python3 -c "import ast; ast.parse(open('$f').read()); print('OK: $f')"
done

# UE Python console — prerequisite check
import init_post_render_tool

# UE Python console — full import
from post_render_tool.pipeline import run_import
result = run_import(r"path/to/csv", fps=24.0)

# UE Python console — launch tool (loads template + opens widget)
import init_post_render_tool

# UE Python console — widget management
from post_render_tool.widget_builder import open_widget, rebuild_widget, delete_widget
open_widget()      # load template + spawn tab + inject UI
rebuild_widget()   # reopen (drops cached UI, does NOT delete the template)
delete_widget()    # destructive: delete template asset; must recreate manually

# UE Python console — hot reload after editing .py files (no UE restart)
import importlib
import post_render_tool.widget_builder as wb
import post_render_tool.widget as w
importlib.reload(wb); importlib.reload(w)
wb.open_widget()
```

## One-time template setup (UE Editor)

The widget Blueprint must be created **manually once** in the UE Editor.
Programmatic factory creation is not viable in UE 5.7 because the
auto-generated root widget is created with `bIsVariable = false`,
producing a UPROPERTY without `CPF_BlueprintVisible` that Python cannot
access (see `widget_builder.TEMPLATE_SETUP_INSTRUCTIONS`).

Steps:
1. Content Browser → `/Game/PostRenderTool/`
2. Right-click → Editor Utilities → Editor Utility Widget
3. Pick parent class: `EditorUtilityWidget` (native)
4. Name: `EUW_PostRenderTool`
5. Open the Designer, drag a `Vertical Box` as the root
6. Rename it to `RootPanel`, **check "Is Variable"** in the Details panel
7. Compile + Save

## Architecture

```
Content/Python/post_render_tool/
├── config.py                  # Configurable constants (axis mapping, thresholds)
├── csv_parser.py              # F1: CSV Dense parser (pure Python)
├── coordinate_transform.py    # F2: Coord transform (pure Python, configurable)
├── validator.py               # F6: FOV check + anomaly detection (pure Python)
├── lens_file_builder.py       # F3: .ulens generation (requires unreal)
├── camera_builder.py          # F4: CineCameraActor (requires unreal)
├── sequence_builder.py        # F5: LevelSequence + animation (requires unreal)
├── pipeline.py                # Orchestrator (requires unreal)
├── ui_interface.py            # Utility functions: file dialog, sequencer, MRQ (requires unreal)
├── widget.py                  # F7: Plain Python UI builder (requires unreal)
└── widget_builder.py          # F7: EUW Blueprint + UI injection (requires unreal)
```

Pure Python modules (csv_parser, coordinate_transform, validator) have no `unreal` import — testable outside UE.
UE-dependent modules can only run inside UE Editor.

## Gotchas

- **Coordinate transform defaults are UNVERIFIED.** `config.py` POSITION_MAPPING / ROTATION_MAPPING
  are initial guesses. Must test with real data in UE viewport before production use.
- **LensFile API varies across UE versions.** `lens_file_builder.py` has dual try/except paths.
  If both fail, it raises RuntimeError (not silent).
- **Frame cadence preserved.** sequence_builder uses `frame_number - first_frame_number` as keyframe
  time, NOT consecutive indices. Gaps in CSV frame column create gaps in LevelSequence.
- **`PluginBlueprintLibrary.is_plugin_loaded()` does NOT work** in some UE builds.
  Use `hasattr(unreal, "ClassName")` to detect plugin availability instead.
- **UE Python module reload:** After editing config.py, use `importlib.reload()` — no UE restart needed.
- **UE Python reflection visibility:** `get_editor_property` / `dir()` only see
  UPROPERTYs with `CPF_BlueprintVisible | CPF_BlueprintAssignable`, or editor-only
  UPROPERTYs with `CPF_Edit` (see `PyGenUtil.cpp` `IsScriptExposedProperty` /
  `ShouldExportEditorOnlyProperty`). Bare `UPROPERTY()` is invisible from Python.
- **UE Python UFUNCTION requirement:** plain C++ methods are NOT Python-callable.
  Known gotchas: `UserWidget::GetRootWidget()` (not UFUNCTION — use
  `EditorUtilityWidget::FindChildWidgetByName` or a named Blueprint variable),
  `FKismetEditorUtilities::CompileBlueprint` (non-UObject static — use
  `unreal.BlueprintEditorLibrary.compile_blueprint` instead).
- **Widget is plain Python, NOT @uclass:** `widget.py` is a plain Python class
  (`PostRenderToolUI`) that builds UMG layout into a provided `EditorUtilityWidget`.
  The Blueprint is a **user-created template** with a VerticalBox named `RootPanel`
  marked as variable.  UI is injected after spawn via `find_utility_widget_from_blueprint`.
  See "One-time template setup" above for the manual creation steps.
- **Why manual template?** UE 5.7's `EditorUtilityWidgetBlueprintFactory` auto-creates
  the root panel with `bIsVariable = false`, so the compiler emits a UPROPERTY
  without `CPF_BlueprintVisible`.  Python's `get_editor_property` and `dir()`
  cannot see the widget at all.  `find_child_widget_by_name` also returned None
  on the spawned instance, suggesting the WidgetTree archetype is not propagated
  for factory-created widgets in this build.  Manual template creation in the
  Designer marks the widget as a variable, producing a script-visible UPROPERTY.
- **Widget runtime UI construction:** `widget.py` builds the UMG layout in `__init__()`.
  If the UE Python API for `create_widget()` or `add_child()` behaves differently
  across UE versions, the layout may need adjustment.

## UE Source Code Reference

UE 5.7 engine source: `/Users/bip.lan/AIWorkspace/vp/UnrealEngine/`

For uncertain UE Python API behavior, read the source directly instead of guessing:
- `Engine/Plugins/Experimental/PythonScriptPlugin/Source/PythonScriptPlugin/Private/PyGenUtil.cpp`
  — property/function script-exposure rules (`IsScriptExposedProperty`, `ShouldExportEditorOnlyProperty`)
- `Engine/Source/Runtime/UMG/` — UMG runtime (`UserWidget`, `WidgetTree`, `PanelWidget`)
- `Engine/Source/Editor/UMGEditor/` — `WidgetBlueprint`, `WidgetBlueprintCompiler`
- `Engine/Source/Editor/Blutility/` — `EditorUtilityWidget`, `EditorUtilityWidgetBlueprintFactory`, `EditorUtilitySubsystem`

<!-- DOCSMITH:KNOWLEDGE:BEGIN -->
## Knowledge Base (Managed by Docsmith)

- Knowledge entrypoint: `.claude/knowledge/_INDEX.md`
- Config file: `.claude/knowledge.json`

### Current Sources
- `developer-disguise-one` (8 files) → `.claude/knowledge/developer-disguise-one/`
- `help-disguise-one` (262 files) → `.claude/knowledge/help-disguise-one/`
- `ue50-docs` (292 files) → `.claude/knowledge/ue50-docs/`
- `ue51-docs` (284 files) → `.claude/knowledge/ue51-docs/`
- `ue52-docs` (333 files) → `.claude/knowledge/ue52-docs/`
- `ue53-docs` (29 files) → `.claude/knowledge/ue53-docs/`
- `ue54-docs` (321 files) → `.claude/knowledge/ue54-docs/`
- `ue55-docs` (324 files) → `.claude/knowledge/ue55-docs/`
- `ue56-docs` (389 files) → `.claude/knowledge/ue56-docs/`
- `ue57-docs` (411 files) → `.claude/knowledge/ue57-docs/`

### Query Protocol
1. Read `.claude/knowledge/_INDEX.md` to route to the relevant source.
2. Open `<source>/_INDEX.md` and shortlist target documents by `topic/summary/keywords`.
3. Read target file TL;DR first, then read full content when needed.
4. Before answering, prioritize evidence from `KnowledgeBase docs`; use external knowledge only when KB coverage is insufficient.
5. In every answer, include:
   - `Knowledge Sources`: exact KB document paths used.
   - `External Inputs`: non-KB knowledge used and why.
   - If no KB match: `No relevant KnowledgeBase docs found`.

### Refresh Command
```bash
.venv/bin/python -m cli --project-links --refresh-index .
```
<!-- DOCSMITH:KNOWLEDGE:END -->
