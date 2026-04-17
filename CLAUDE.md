# CLAUDE.md

## Project Overview

VP Post-Render Tool: Disguise Designer CSV Dense → UE 5.7 CineCameraActor + LensFile + LevelSequence.

Packaged as a **self-contained UE 5.7 plugin** (`PostRenderTool.uplugin` at repo root). Drops into any `<UEProject>/Plugins/` directory. C++ module provides a `UEditorUtilityWidget` subclass with a `meta=(BindWidget)` UPROPERTY contract; child Blueprint authored in the UMG Designer satisfies the contract; Python binds callbacks and drives the CSV → UE import pipeline.

## Commands

```bash
# Unit tests (pure Python, no UE needed)
cd Content/Python && python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -v

# Syntax check for UE-dependent modules
for f in post_render_tool/{lens_file_builder,camera_builder,sequence_builder,pipeline,ui_interface,widget,widget_builder}.py; do
  python3 -c "import ast; ast.parse(open('$f').read()); print('OK: $f')"
done

# UE Python console — launch tool
import init_post_render_tool

# UE Python console — full pipeline (bypass UI)
from post_render_tool.pipeline import run_import
result = run_import(r"path/to/csv", fps=24.0)

# UE Python console — widget management
from post_render_tool.widget_builder import open_widget, rebuild_widget, delete_widget, rebuild_from_spec
open_widget()        # load BP_PostRenderToolWidget + spawn tab + bind callbacks
rebuild_widget()     # reopen (drops cached UI, does NOT delete the Blueprint asset)
rebuild_from_spec()  # regenerate BP from docs/widget-tree-spec.json (idempotent — preserves user tweaks on existing widgets) + reopen tab
delete_widget()      # destructive: delete the deployment-authored asset (not shipped; must be re-authored per deployment-guide.md §1.3 or re-synced from version control)

# UE Python console — build BP from JSON spec (standalone, without reopen)
from post_render_tool import build_widget_blueprint
build_widget_blueprint.run_build()

# UE Python console — hot reload after editing .py files (no UE restart)
import importlib
import post_render_tool.widget_builder as wb
import post_render_tool.widget as w
importlib.reload(wb); importlib.reload(w)
wb.rebuild_widget()

# Cross-check widget names across C++ / widget.py / JSON spec (drift detector)
cd Content/Python && python -m unittest post_render_tool.tests.test_spec_drift -v
```

## Git / P4 Workflow

- **Post-commit hook pushes the CURRENT branch to the Helix4Git depot** on every commit (`scripts/git-hooks/post-commit`, `core.hooksPath = scripts/git-hooks`, installed via commits `0581b3c` → `a46045f`). `main` and feature branches both push; hook exits 0 on failure so it never blocks commits. Output: `[p4-sync] ✓ <branch> pushed to p4` on stderr; rolling log at `.git/p4-push.log`.
- **P4 workspace mirror**: `/Users/bip.lan/AIWorkspace/vp/p4-workspace/ue/post-render-tool/` is a parallel clone of the same depot, pinned to `main` for UE Editor consumption. Feature-branch commits land in the depot but don't advance this mirror. `P4CLIENT = claude-workspace` (set via `P4CLIENT=claude-workspace p4 ...` or `~/.p4config`).
- **Worktree convention**: For multi-commit refactors, create a worktree outside the repo: `git worktree add ~/.config/superpowers/worktrees/post_render_tool/<branch> -b feature/<name>`. Keeps the main working tree and the p4 workspace mirror clean. Each commit still pushes the feature branch to the depot (safe — `main` doesn't move until merge).
- **Main repo vs worktree**: Edits in a worktree on a non-main branch are invisible to the main repo's working tree until you `git checkout <branch>` in main or merge. If someone says "I don't see the new files", that's usually why.
- **Known hook quirk — `--no-ff` merges don't trigger the hook.** `git merge --no-ff` creates a merge commit, but the `post-commit` hook does NOT fire on it in this setup (observed at `2db9686`, session 2026-04-12). After any `--no-ff` merge into `main`, manually run `git push p4 main` to advance the p4 depot. Fast-forward merges (no new commit) don't need a push at all.

## First-time setup

See `docs/plugin-setup.md` for first-time plugin installation, UBT build, and Blueprint authoring instructions.

## Architecture

VP Post-Render Tool is a self-contained UE 5.7 plugin. The repo root IS the plugin root:

```
post_render_tool/                               ← plugin root
├── PostRenderTool.uplugin                      ← plugin manifest
├── Source/
│   └── PostRenderTool/
│       ├── PostRenderTool.Build.cs             ← module descriptor (UMG, Blutility, UnrealEd, …)
│       ├── Public/
│       │   ├── PostRenderToolModule.h          ← empty module entry point
│       │   └── PostRenderToolWidget.h          ← C++ BindWidget contract (41 UPROPERTYs)
│       └── Private/
│           ├── PostRenderToolModule.cpp
│           └── PostRenderToolWidget.cpp        ← empty NativeConstruct stub
├── Content/
│   ├── Blueprints/
│   │   └── BP_PostRenderToolWidget.uasset     ← not in upstream plugin source; first bootstrap authors once via deployment-guide.md §1.3 and commits to the project repo, later clones/deployments just sync
│   └── Python/
│       ├── init_post_render_tool.py            ← entry point, calls widget_builder.open_widget()
│       └── post_render_tool/
│           ├── config.py                       # Configurable constants (axis mapping, thresholds)
│           ├── csv_parser.py                   # CSV Dense parser (pure Python)
│           ├── coordinate_transform.py         # Coord transform (pure Python, configurable)
│           ├── validator.py                    # FOV check + anomaly detection (pure Python)
│           ├── lens_file_builder.py            # .ulens generation (requires unreal)
│           ├── camera_builder.py               # CineCameraActor (requires unreal)
│           ├── sequence_builder.py             # LevelSequence + animation (requires unreal)
│           ├── pipeline.py                     # Orchestrator (requires unreal)
│           ├── ui_interface.py                 # File dialog, sequencer, MRQ (requires unreal)
│           ├── widget.py                       # BindWidget binder + callbacks
│           ├── widget_builder.py               # Asset loader + tab spawner
│           └── widget_programmatic.py.bak      # archival (pre-plugin builder, unused)
└── docs/
    ├── plugin-setup.md                         ← first-time install guide
    └── bindwidget-contract.md                  ← 41 widget name/type reference
```

UE loads the plugin from `<UEProject>/Plugins/PostRenderTool/`, mounts `Content/` at the virtual path `/PostRenderTool/`, and adds `Content/Python/` to `sys.path`.

**BindWidget contract:** `UPostRenderToolWidget` (C++) declares 33 required + 8 optional widget pointers via `UPROPERTY(BlueprintReadOnly, meta=(BindWidget))` / `meta=(BindWidgetOptional)`. The child Blueprint `BP_PostRenderToolWidget` must contain widgets with matching names and types, or the UMG compiler fails the Blueprint build with `A required widget binding "X" of type Y was not found.`

**Runtime flow:**
1. User runs `import init_post_render_tool` in the UE Python console
2. `widget_builder.open_widget()` loads `/PostRenderTool/Blueprints/BP_PostRenderToolWidget`
3. `EditorUtilitySubsystem.spawn_and_register_tab()` spawns the widget instance
4. `PostRenderToolUI(widget)` acquires every bound widget via `host.get_editor_property("btn_browse")` (etc.) and wires callbacks
5. Button clicks drive the existing pure-Python business logic (`parse_csv_dense`, `transform_position`, `run_import`, `spawn_test_camera`, …)

**Build flow (Designer bootstrap automation):**
1. `docs/widget-tree-spec.json` is the single source of truth for the full WidgetTree (41 contract + decorative nesting + widget properties + slot padding).
2. `build_widget_blueprint.run_build()` parses the spec → calls `UPostRenderToolBuildHelper` (C++ bridge, 3 UFUNCTIONs) to mutate `UWidgetBlueprint.WidgetTree`. Python cannot touch WidgetTree directly (`BaseWidgetBlueprint.h:16-17` → bare `UPROPERTY()` without `BlueprintVisible` is invisible to Python reflection per `PyGenUtil.cpp::IsScriptExposedProperty`).
3. `widget_properties.apply_widget_properties/apply_slot_properties` sets per-widget + slot-layout values via `set_editor_property()` reflection.
4. `unreal.BlueprintEditorLibrary.compile_blueprint` + `unreal.EditorAssetLibrary.save_asset` persist the `.uasset`.
5. Idempotent: rerun only creates widgets that are missing by name; existing ones (possibly user-tweaked in Designer) are left untouched. Properties/slot are applied ONLY on fresh creation — user edits survive.
6. C++ side: `UPostRenderToolBuildHelper` exposes `EnsureRootPanel`, `FindWidgetByName`, `EnsureWidgetUnderParent` (the latter returns `(result_enum, widget, slot)` as a Python tuple via UFUNCTION out-params).

Pure-Python modules (`csv_parser`, `coordinate_transform`, `validator`, `spec_loader`, `widget_properties`) have no `unreal` import and are testable outside UE Editor.

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
- **BindWidget requires explicit `BlueprintReadOnly`.** `UPROPERTY(meta=(BindWidget))`
  alone is NOT Python-visible. You must write
  `UPROPERTY(BlueprintReadOnly, meta=(BindWidget)) UButton* btn_foo;`
  to make `host.get_editor_property("btn_foo")` work from Python. `BlueprintReadOnly`
  is what sets `CPF_BlueprintVisible`; `meta=(BindWidget)` is the UMG compiler hint
  that auto-binds the pointer to a same-named widget in the child Blueprint.
- **Live Coding does NOT support UPROPERTY changes.** Adding, removing, or renaming
  a BindWidget UPROPERTY in `PostRenderToolWidget.h` requires a full Editor restart
  and a full plugin rebuild (UHT must re-run to regenerate reflection metadata).
  Live Coding only works for method body edits. Child Blueprints must be recompiled
  after parent UPROPERTY changes.
- **Python-vs-Designer name drift is a silent bug.** A mismatch between
  `_REQUIRED_CONTROLS` in `widget.py` and the UPROPERTY names in
  `PostRenderToolWidget.h` causes `get_editor_property()` to return None, and the
  binder logs a warning but keeps going. Keep the two sides in sync; see
  `docs/bindwidget-contract.md` for the authoritative list.
- **JSON spec is the fourth source of truth for widget names.** Besides `PostRenderToolWidget.h`
  UPROPERTY names and `widget.py`'s `_REQUIRED_CONTROLS`/`_OPTIONAL_CONTROLS`, `docs/widget-tree-spec.json`
  also lists the 33+8 contract names. Three-way drift (C++ / widget.py / JSON) is detected by
  `post_render_tool/tests/test_spec_drift.py` — rerun it after any contract rename.
- **`UWidget::bIsVariable` cannot be set from business C++.** Widget.h:318 is a private bitfield with
  no public setter; `UMGEditor::SWidgetDetailsView.cpp:641` is the only code that writes it (because
  UMGEditor module has compile-time private access). Workaround: `Widget.cpp:195` constructor
  initializes it to `true` by default, which satisfies BindWidget reflection for all widgets
  constructed via `UWidgetTree::ConstructWidget`. Cost: decorative widgets become variables too
  (harmless; a few extra UPROPERTYs on the generated class).
- **Widget tree structural changes need `FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified`,
  not `Blueprint->Modify()`.** `Modify()` is Undo-only; structural mutations require the stronger
  marker to invalidate the generated class layout for the next compile. Used inside
  `UPostRenderToolBuildHelper::{EnsureRootPanel,EnsureWidgetUnderParent}`.
- **C++ UFUNCTION changes require full Editor restart + plugin rebuild.** Live Coding registers new
  UFUNCTIONs inconsistently. After touching `PostRenderToolBuildHelper.h`/`.cpp`, quit the Editor,
  rebuild the plugin via UBT, relaunch, and verify `unreal.PostRenderToolBuildHelper.ensure_widget_under_parent`
  is visible in `help(unreal.PostRenderToolBuildHelper)` before running `build_widget_blueprint.run_build()`.

## UE Source Code Reference

UE 5.7 engine source: `/Users/bip.lan/AIWorkspace/vp/UnrealEngine/`

For uncertain UE Python API behavior, read the source directly instead of guessing:
- `Engine/Plugins/Experimental/PythonScriptPlugin/Source/PythonScriptPlugin/Private/PyGenUtil.cpp`
  — property/function script-exposure rules (`IsScriptExposedProperty`, `ShouldExportEditorOnlyProperty`)
- `Engine/Source/Runtime/UMG/` — UMG runtime (`UserWidget`, `WidgetTree`, `PanelWidget`)
- `Engine/Source/Editor/UMGEditor/` — `WidgetBlueprint`, `WidgetBlueprintCompiler` (BindWidget validation lives here)
- `Engine/Source/Editor/Blutility/` — `EditorUtilityWidget`, `EditorUtilityWidgetBlueprintFactory`, `EditorUtilitySubsystem`
- `Engine/Source/Editor/BlueprintEditorLibrary/Public/BlueprintEditorLibrary.h` — `CompileBlueprint` UFUNCTION

For API edge cases, dispatch an `Explore` subagent with a concrete question (e.g. "verify X is a UFUNCTION in UE 5.7") and require `file:line` citations. Faster than grepping the engine source yourself and keeps the main context clean.

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
