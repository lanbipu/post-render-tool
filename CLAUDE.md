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

# UE Python console — launch tool (creates + opens widget)
import init_post_render_tool

# UE Python console — widget management
from post_render_tool.widget_builder import open_widget, rebuild_widget
open_widget()      # create if needed + open
rebuild_widget()   # delete + recreate + open
```

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
- **Widget is plain Python, NOT @uclass:** `widget.py` is a plain Python class
  (`PostRenderToolUI`) that builds UMG layout into a provided `EditorUtilityWidget`.
  The Blueprint uses native `EditorUtilityWidget` parent (safe to serialize).
  UI is injected after spawn via `find_utility_widget_from_blueprint`.
- **Widget runtime UI construction:** `widget.py` builds the UMG layout in `__init__()`.
  If the UE Python API for `create_widget()` or `add_child()` behaves differently
  across UE versions, the layout may need adjustment.

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
