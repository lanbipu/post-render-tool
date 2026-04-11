# Blueprint UI Auto-Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the manual Blueprint UI setup (documented in `docs/blueprint-ui-setup.md`) with a Python script that programmatically creates and opens a fully-functional Editor Utility Widget, providing all tool operations from within the Blueprint UI.

**Architecture:** Two new UE-dependent modules: `widget.py` defines a Python `@unreal.uclass()` extending `EditorUtilityWidget` that builds the UMG layout at runtime and handles all user interactions; `widget_builder.py` creates the EditorUtilityWidgetBlueprint asset in Content Browser and opens it via `EditorUtilitySubsystem`. The existing `ui_interface.py` is simplified to a backend-only module (cmd_* wrappers removed). `init_post_render_tool.py` is updated to auto-build and open the widget on import.

**Tech Stack:** UE 5.7 Python API (`unreal` module), EditorUtilityWidget, UMG Widgets, EditorUtilitySubsystem

---

## File Structure

```
Content/Python/post_render_tool/
├── config.py                  # UNCHANGED
├── csv_parser.py              # UNCHANGED
├── coordinate_transform.py    # UNCHANGED
├── validator.py               # UNCHANGED
├── lens_file_builder.py       # UNCHANGED
├── camera_builder.py          # UNCHANGED
├── sequence_builder.py        # UNCHANGED
├── pipeline.py                # UNCHANGED
├── ui_interface.py            # MODIFY: remove cmd_* wrappers, keep core functions
├── widget.py                  # CREATE: Python @uclass EditorUtilityWidget
├── widget_builder.py          # CREATE: EUW Blueprint asset builder + opener
└── __init__.py                # UNCHANGED

Content/Python/init_post_render_tool.py  # MODIFY: add auto-build + open widget

docs/blueprint-ui-setup.md              # MODIFY: rewrite for auto-generation flow
CLAUDE.md                               # MODIFY: update architecture section
```

## Data Flow (New)

```
init_post_render_tool.py
  → check_prerequisites()
  → widget_builder.create_widget()     # creates EUW Blueprint asset if not exists
  → widget_builder.open_widget()       # opens the widget tab

OPostRenderToolWidget (widget.py)
  construct() → _build_ui()            # builds UMG layout at runtime
  _on_browse_clicked()                 # → ui_interface.browse_csv_file() + update text
  _on_import_clicked()                 # → pipeline.run_import() + update results
  _on_open_sequencer_clicked()         # → ui_interface.open_sequencer()
  _on_open_mrq_clicked()              # → ui_interface.open_movie_render_queue()
```

---

### Task 1: Create `widget.py` — Python @uclass EditorUtilityWidget

**Files:**
- Create: `Content/Python/post_render_tool/widget.py`

This is the core widget class. It extends `EditorUtilityWidget` using UE's Python `@uclass()` decorator. The `construct()` override dynamically builds the full UMG widget tree at runtime and wires up button events.

- [ ] **Step 1: Write the widget.py module with @uclass definition and construct() layout builder**

```python
"""Widget — VP Post-Render Tool.

Python-based EditorUtilityWidget that builds the full UI at runtime.
Only usable inside UE Editor Python environment.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import unreal

from .csv_parser import CsvParseError, parse_csv_dense
from .pipeline import PipelineResult, run_import
from .ui_interface import browse_csv_file, open_sequencer, open_movie_render_queue

logger = logging.getLogger(__name__)


@unreal.uclass()
class OPostRenderToolWidget(unreal.EditorUtilityWidget):
    """VP Post-Render Tool Editor Utility Widget.

    Programmatically builds the UMG layout in construct() and handles
    all user interactions (browse, import, open sequencer, open MRQ).
    """

    # ---------------------------------------------------------------
    # State
    # ---------------------------------------------------------------
    _csv_path: str = ""
    _fps: float = 24.0
    _last_result: Optional[PipelineResult] = None

    # Widget references (populated in _build_ui)
    _txt_file_path: Optional[unreal.TextBlock] = None
    _txt_detected_fps: Optional[unreal.TextBlock] = None
    _txt_frame_count: Optional[unreal.TextBlock] = None
    _txt_focal_range: Optional[unreal.TextBlock] = None
    _txt_timecode: Optional[unreal.TextBlock] = None
    _txt_sensor_width: Optional[unreal.TextBlock] = None
    _txt_results: Optional[unreal.MultiLineEditableText] = None
    _spn_fps: Optional[unreal.SpinBox] = None
    _btn_import: Optional[unreal.Button] = None
    _btn_open_seq: Optional[unreal.Button] = None
    _btn_open_mrq: Optional[unreal.Button] = None

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    @unreal.ufunction(override=True)
    def construct(self):
        """Called when the widget is initialized. Builds the full UI."""
        self._build_ui()

    # ---------------------------------------------------------------
    # UI Construction
    # ---------------------------------------------------------------

    def _build_ui(self):
        """Build the entire UMG widget tree dynamically."""
        # Root vertical box
        root = self._make_widget(unreal.VerticalBox)
        self.set_content(root)

        # --- Title ---
        title = self._make_text("VP Post-Render Tool", size=18, is_bold=True)
        root.add_child(title)
        self._add_spacer(root, 12.0)

        # --- CSV File Row ---
        file_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(file_row)

        lbl_file = self._make_text("CSV File: ")
        file_row.add_child(lbl_file)

        self._txt_file_path = self._make_text(
            "No file selected", color=unreal.SlateColor(unreal.LinearColor(0.5, 0.5, 0.5, 1.0))
        )
        file_row.add_child(self._txt_file_path)
        # Make file path text fill available space
        slot = self._txt_file_path.slot
        if hasattr(slot, 'set_editor_property'):
            try:
                slot.set_editor_property("size", unreal.SlateChildSize(1.0))
            except Exception:
                pass

        btn_browse = self._make_button("Browse...", self._on_browse_clicked)
        file_row.add_child(btn_browse)

        self._add_spacer(root, 8.0)

        # --- FPS Row ---
        fps_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(fps_row)

        lbl_fps = self._make_text("FPS: ")
        fps_row.add_child(lbl_fps)

        self._spn_fps = self._make_widget(unreal.SpinBox)
        self._spn_fps.set_editor_property("min_value", 1.0)
        self._spn_fps.set_editor_property("max_value", 120.0)
        self._spn_fps.set_editor_property("value", 24.0)
        self._spn_fps.on_value_changed.add_callable(self._on_fps_changed)
        fps_row.add_child(self._spn_fps)

        self._txt_detected_fps = self._make_text("Auto: --", color=unreal.SlateColor(
            unreal.LinearColor(0.5, 0.5, 0.5, 1.0)
        ))
        fps_row.add_child(self._txt_detected_fps)

        self._add_spacer(root, 8.0)

        # --- Preview Section ---
        preview_header = self._make_text("── CSV Preview ──")
        root.add_child(preview_header)

        self._txt_frame_count = self._make_text("Frames: —")
        root.add_child(self._txt_frame_count)

        self._txt_focal_range = self._make_text("Focal Length: —")
        root.add_child(self._txt_focal_range)

        self._txt_timecode = self._make_text("Timecode: —")
        root.add_child(self._txt_timecode)

        self._txt_sensor_width = self._make_text("Sensor Width: —")
        root.add_child(self._txt_sensor_width)

        self._add_spacer(root, 12.0)

        # --- Import Button ---
        self._btn_import = self._make_button("Import", self._on_import_clicked)
        root.add_child(self._btn_import)

        self._add_spacer(root, 8.0)

        # --- Results Area ---
        lbl_results = self._make_text("── Results ──")
        root.add_child(lbl_results)

        self._txt_results = self._make_widget(unreal.MultiLineEditableText)
        self._txt_results.set_editor_property("is_read_only", True)
        self._txt_results.set_text(unreal.Text(""))
        root.add_child(self._txt_results)

        self._add_spacer(root, 8.0)

        # --- Action Buttons Row ---
        action_row = self._make_widget(unreal.HorizontalBox)
        root.add_child(action_row)

        self._btn_open_seq = self._make_button("Open Sequencer", self._on_open_sequencer_clicked)
        action_row.add_child(self._btn_open_seq)

        self._btn_open_mrq = self._make_button("Open Movie Render Queue", self._on_open_mrq_clicked)
        action_row.add_child(self._btn_open_mrq)

    # ---------------------------------------------------------------
    # Widget Factory Helpers
    # ---------------------------------------------------------------

    def _make_widget(self, widget_class):
        """Create a UMG widget owned by this widget's outer."""
        try:
            return unreal.create_widget(self, widget_class)
        except Exception:
            # Fallback: direct construction
            return widget_class()

    def _make_text(self, text: str, size: int = 0, is_bold: bool = False,
                   color=None) -> unreal.TextBlock:
        """Create a TextBlock with optional styling."""
        tb = self._make_widget(unreal.TextBlock)
        tb.set_text(unreal.Text(text))
        if size > 0 or is_bold:
            font = tb.get_editor_property("font")
            if size > 0:
                font.size = size
            if is_bold:
                font.typeface_font_name = "Bold"
            tb.set_editor_property("font", font)
        if color is not None:
            tb.set_editor_property("color_and_opacity", color)
        return tb

    def _make_button(self, label: str, callback) -> unreal.Button:
        """Create a Button with a TextBlock child and an OnClicked callback."""
        btn = self._make_widget(unreal.Button)
        btn_text = self._make_text(label)
        btn.add_child(btn_text)
        btn.on_clicked.add_callable(callback)
        return btn

    def _add_spacer(self, parent, height: float):
        """Add a Spacer widget to a panel."""
        spacer = self._make_widget(unreal.Spacer)
        parent.add_child(spacer)
        slot = spacer.slot
        if hasattr(slot, 'set_editor_property'):
            try:
                slot.set_editor_property("size", unreal.Vector2D(0, height))
            except Exception:
                pass

    # ---------------------------------------------------------------
    # Event Handlers
    # ---------------------------------------------------------------

    def _on_browse_clicked(self):
        """Handle Browse button: open file dialog and load CSV preview."""
        csv_path = browse_csv_file()
        if not csv_path:
            unreal.log_warning("[widget] No file selected.")
            return

        self._csv_path = csv_path
        self._txt_file_path.set_text(unreal.Text(csv_path))

        # Parse CSV for preview
        try:
            result = parse_csv_dense(csv_path)
            fl_min, fl_max = result.focal_length_range
            self._txt_frame_count.set_text(unreal.Text(f"Frames: {result.frame_count}"))
            self._txt_focal_range.set_text(
                unreal.Text(f"Focal Length: {fl_min:.2f} – {fl_max:.2f} mm")
            )
            self._txt_timecode.set_text(
                unreal.Text(f"Timecode: {result.timecode_start} → {result.timecode_end}")
            )
            self._txt_sensor_width.set_text(
                unreal.Text(f"Sensor Width: {result.sensor_width_mm:.2f} mm")
            )
            if result.detected_fps is not None:
                self._txt_detected_fps.set_text(
                    unreal.Text(f"Auto: {result.detected_fps} fps")
                )
            else:
                self._txt_detected_fps.set_text(unreal.Text("Auto: N/A"))

            unreal.log(f"[widget] CSV preview loaded: {csv_path}")

        except CsvParseError as exc:
            self._txt_results.set_text(unreal.Text(f"CSV Error: {exc}"))
            unreal.log_warning(f"[widget] CSV parse error: {exc}")
        except Exception as exc:
            self._txt_results.set_text(unreal.Text(f"Error: {exc}"))
            unreal.log_error(f"[widget] Preview error: {exc}")

    def _on_fps_changed(self, value: float):
        """Handle FPS SpinBox value change."""
        self._fps = value

    def _on_import_clicked(self):
        """Handle Import button: run the full pipeline."""
        if not self._csv_path:
            self._txt_results.set_text(unreal.Text("Error: No CSV file selected. Click Browse first."))
            return

        self._txt_results.set_text(unreal.Text("Importing..."))

        fps = self._fps if self._fps > 0 else 0.0
        pipeline_result = run_import(self._csv_path, fps)
        self._last_result = pipeline_result

        if pipeline_result.success:
            report_text = (
                pipeline_result.report.format_report()
                if pipeline_result.report is not None
                else "Import successful (no report generated)."
            )
            self._txt_results.set_text(unreal.Text(report_text))
            unreal.log(f"[widget] Import successful: {pipeline_result.package_path}")
        else:
            self._txt_results.set_text(unreal.Text(f"Import Failed:\n{pipeline_result.error_message}"))
            unreal.log_error(f"[widget] Import failed: {pipeline_result.error_message}")

    def _on_open_sequencer_clicked(self):
        """Handle Open Sequencer button."""
        if self._last_result is None or self._last_result.level_sequence is None:
            unreal.log_warning("[widget] No LevelSequence available. Run Import first.")
            return
        open_sequencer()

    def _on_open_mrq_clicked(self):
        """Handle Open Movie Render Queue button."""
        open_movie_render_queue()
```

- [ ] **Step 2: Verify syntax**

Run:
```bash
cd Content/Python && python3 -c "import ast; ast.parse(open('post_render_tool/widget.py').read()); print('OK: widget.py')"
```
Expected: `OK: widget.py`

- [ ] **Step 3: Commit**

```bash
git add Content/Python/post_render_tool/widget.py
git commit -m "feat: add Python @uclass EditorUtilityWidget with runtime UI construction"
```

---

### Task 2: Create `widget_builder.py` — Blueprint Asset Builder

**Files:**
- Create: `Content/Python/post_render_tool/widget_builder.py`

This module provides two functions: `create_widget()` creates the EditorUtilityWidgetBlueprint asset in Content Browser (pointing to the Python @uclass as parent), and `open_widget()` opens it as an editor tab via `EditorUtilitySubsystem`.

- [ ] **Step 1: Write the widget_builder.py module**

```python
"""Widget Builder — VP Post-Render Tool.

Creates and opens the EditorUtilityWidget Blueprint asset.
Only usable inside UE Editor Python environment.
"""

from __future__ import annotations

import logging

import unreal

logger = logging.getLogger(__name__)

# Asset location in Content Browser
WIDGET_PACKAGE_PATH = "/Game/PostRenderTool"
WIDGET_ASSET_NAME = "EUW_PostRenderTool"
WIDGET_FULL_PATH = f"{WIDGET_PACKAGE_PATH}/{WIDGET_ASSET_NAME}"


def widget_exists() -> bool:
    """Check if the EUW Blueprint asset already exists in Content Browser."""
    return unreal.EditorAssetLibrary.does_asset_exist(
        f"{WIDGET_FULL_PATH}.{WIDGET_ASSET_NAME}"
    )


def create_widget() -> object:
    """Create the EditorUtilityWidgetBlueprint asset.

    If the asset already exists, returns the existing one without overwriting.

    Returns
    -------
    unreal.EditorUtilityWidgetBlueprint
        The created or existing widget Blueprint asset.
    """
    # Check if already exists
    asset_path = f"{WIDGET_FULL_PATH}.{WIDGET_ASSET_NAME}"
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        unreal.log(f"[widget_builder] Widget already exists: {asset_path}")
        return unreal.EditorAssetLibrary.load_asset(asset_path)

    # Ensure directory
    if not unreal.EditorAssetLibrary.does_directory_exist(WIDGET_PACKAGE_PATH):
        unreal.EditorAssetLibrary.make_directory(WIDGET_PACKAGE_PATH)

    # Create the EditorUtilityWidgetBlueprint using factory
    factory = unreal.EditorUtilityWidgetBlueprintFactory()

    # Set parent class to our Python @uclass
    # Import our widget class — this triggers @uclass registration
    from .widget import OPostRenderToolWidget
    try:
        factory.set_editor_property("parent_class", OPostRenderToolWidget)
    except Exception as exc:
        unreal.log_warning(
            f"[widget_builder] Could not set parent_class via factory: {exc}. "
            "Trying alternative approach..."
        )
        # Alternative: create with default parent, then reparent
        pass

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    widget_bp = asset_tools.create_asset(
        WIDGET_ASSET_NAME,
        WIDGET_PACKAGE_PATH,
        None,  # asset_class — None lets the factory decide
        factory,
    )

    if widget_bp is None:
        raise RuntimeError(
            f"Failed to create EditorUtilityWidgetBlueprint at {WIDGET_FULL_PATH}"
        )

    # If factory didn't accept parent_class, try reparenting
    try:
        current_parent = widget_bp.get_editor_property("parent_class")
        if current_parent != OPostRenderToolWidget:
            # Try reparent API
            if hasattr(unreal, "KismetSystemLibrary"):
                unreal.BlueprintEditorLibrary.reparent_blueprint(
                    widget_bp, OPostRenderToolWidget
                )
                unreal.log("[widget_builder] Reparented to OPostRenderToolWidget.")
    except Exception as exc:
        unreal.log_warning(
            f"[widget_builder] Reparent not available: {exc}. "
            "Widget will use default EditorUtilityWidget parent. "
            "UI must be configured manually in Blueprint Designer."
        )

    # Save the asset
    unreal.EditorAssetLibrary.save_asset(
        widget_bp.get_path_name(), only_if_is_dirty=False
    )
    unreal.log(f"[widget_builder] Widget Blueprint created: {WIDGET_FULL_PATH}")

    return widget_bp


def open_widget() -> None:
    """Open the PostRenderTool widget as an editor tab.

    Creates the widget asset first if it doesn't exist.
    """
    widget_bp = create_widget()

    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        subsystem.spawn_and_register_tab(widget_bp)
        unreal.log("[widget_builder] Widget tab opened.")
    except Exception as exc:
        unreal.log_error(f"[widget_builder] Failed to open widget tab: {exc}")
        # Fallback: try running as Editor Utility Widget directly
        try:
            unreal.EditorUtilityLibrary.run_editor_utility_widget(widget_bp)
            unreal.log("[widget_builder] Widget opened via EditorUtilityLibrary fallback.")
        except Exception as exc2:
            unreal.log_error(
                f"[widget_builder] Fallback also failed: {exc2}. "
                "Please right-click the asset in Content Browser > Run Editor Utility Widget."
            )


def delete_widget() -> bool:
    """Delete the existing widget Blueprint asset (for rebuilding).

    Returns
    -------
    bool
        True if deleted, False if not found.
    """
    asset_path = f"{WIDGET_FULL_PATH}.{WIDGET_ASSET_NAME}"
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        unreal.EditorAssetLibrary.delete_asset(asset_path)
        unreal.log(f"[widget_builder] Widget deleted: {asset_path}")
        return True
    return False


def rebuild_widget() -> object:
    """Delete and recreate the widget Blueprint asset.

    Returns
    -------
    unreal.EditorUtilityWidgetBlueprint
        The newly created widget Blueprint asset.
    """
    delete_widget()
    return create_widget()
```

- [ ] **Step 2: Verify syntax**

Run:
```bash
cd Content/Python && python3 -c "import ast; ast.parse(open('post_render_tool/widget_builder.py').read()); print('OK: widget_builder.py')"
```
Expected: `OK: widget_builder.py`

- [ ] **Step 3: Commit**

```bash
git add Content/Python/post_render_tool/widget_builder.py
git commit -m "feat: add widget_builder for programmatic EUW Blueprint creation"
```

---

### Task 3: Simplify `ui_interface.py` — Remove cmd_* Wrappers

**Files:**
- Modify: `Content/Python/post_render_tool/ui_interface.py`

Remove `cmd_browse()` and `cmd_import()` since the widget now calls pipeline functions directly. Remove the `UIState` singleton since widget.py owns state. Keep `browse_csv_file()`, `open_sequencer()`, and `open_movie_render_queue()` as utility functions.

- [ ] **Step 1: Remove UIState class and _preview_from_result helper**

Delete lines 27–69 (UIState class + _preview_from_result). These are no longer needed — widget.py manages its own state.

- [ ] **Step 2: Remove load_csv_preview function**

Delete the `load_csv_preview()` function (lines 136–177). The widget calls `parse_csv_dense()` directly instead of going through this JSON wrapper.

- [ ] **Step 3: Remove execute_import function**

Delete the `execute_import()` function (lines 180–219). The widget calls `run_import()` directly.

- [ ] **Step 4: Simplify open_sequencer — remove UIState dependency**

Replace the UIState-dependent `open_sequencer()` with a version that accepts an optional `level_sequence` parameter:

```python
def open_sequencer(level_sequence=None) -> None:
    """Open the Sequencer editor for a given LevelSequence.

    Parameters
    ----------
    level_sequence:
        The LevelSequence asset to open. If None, does nothing.
    """
    if level_sequence is None:
        unreal.log_warning(
            "[ui_interface] open_sequencer: no LevelSequence provided."
        )
        return

    try:
        subsystem = unreal.get_editor_subsystem(unreal.LevelSequenceEditorSubsystem)
        subsystem.open_level_sequence(level_sequence)
        unreal.log("[ui_interface] Sequencer opened.")
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"[ui_interface] open_sequencer error: {exc}")
```

- [ ] **Step 5: Remove cmd_browse and cmd_import functions**

Delete `cmd_browse()` (lines 266–294) and `cmd_import()` (lines 297–314). The widget handles these flows directly.

- [ ] **Step 6: Remove unused imports**

Remove `from .csv_parser import CsvDenseResult, CsvParseError, parse_csv_dense` and `from .pipeline import PipelineResult, run_import` since the JSON wrapper functions that used them are gone. Keep only what `browse_csv_file()`, `open_sequencer()`, and `open_movie_render_queue()` need.

The final `ui_interface.py` should contain only:
- `browse_csv_file()` — file dialog utility
- `open_sequencer(level_sequence)` — open sequencer for a given sequence
- `open_movie_render_queue()` — open MRQ window
- `_ok()` / `_err()` helpers — REMOVE (no longer needed)

- [ ] **Step 7: Verify the simplified file**

Run:
```bash
cd Content/Python && python3 -c "import ast; ast.parse(open('post_render_tool/ui_interface.py').read()); print('OK: ui_interface.py')"
```
Expected: `OK: ui_interface.py`

- [ ] **Step 8: Commit**

```bash
git add Content/Python/post_render_tool/ui_interface.py
git commit -m "refactor: simplify ui_interface to utility functions only

Remove UIState, JSON wrappers, and cmd_* functions.
Widget.py now handles state and calls pipeline directly."
```

---

### Task 4: Update `widget.py` — Fix open_sequencer Call

**Files:**
- Modify: `Content/Python/post_render_tool/widget.py`

After Task 3 changed `open_sequencer()` to accept a `level_sequence` parameter, update the widget's call site.

- [ ] **Step 1: Update _on_open_sequencer_clicked to pass level_sequence**

Change:
```python
    def _on_open_sequencer_clicked(self):
        """Handle Open Sequencer button."""
        if self._last_result is None or self._last_result.level_sequence is None:
            unreal.log_warning("[widget] No LevelSequence available. Run Import first.")
            return
        open_sequencer()
```

To:
```python
    def _on_open_sequencer_clicked(self):
        """Handle Open Sequencer button."""
        if self._last_result is None or self._last_result.level_sequence is None:
            unreal.log_warning("[widget] No LevelSequence available. Run Import first.")
            return
        open_sequencer(self._last_result.level_sequence)
```

- [ ] **Step 2: Verify syntax**

Run:
```bash
cd Content/Python && python3 -c "import ast; ast.parse(open('post_render_tool/widget.py').read()); print('OK: widget.py')"
```
Expected: `OK: widget.py`

- [ ] **Step 3: Commit**

```bash
git add Content/Python/post_render_tool/widget.py
git commit -m "fix: pass level_sequence to open_sequencer in widget"
```

---

### Task 5: Update `init_post_render_tool.py` — Auto-Build and Open Widget

**Files:**
- Modify: `Content/Python/init_post_render_tool.py`

Add automatic widget creation and opening after prerequisite checks pass.

- [ ] **Step 1: Add widget auto-build after prerequisite check**

Replace the entire file with:

```python
"""VP Post-Render Tool — Init and launch.

Usage in UE Python console:
    import init_post_render_tool
"""
import unreal


def _class_exists(class_name: str) -> bool:
    """Check if a UE class is available (i.e., its plugin is loaded)."""
    return hasattr(unreal, class_name)


def check_prerequisites() -> bool:
    """Verify all required plugins are loaded."""
    all_ok = True

    # Python Editor Script Plugin — if we're running this, it's loaded
    unreal.log("  OK: Python Editor Script Plugin (running Python now)")

    # Editor Scripting Utilities — check for EditorAssetLibrary
    if _class_exists("EditorAssetLibrary"):
        unreal.log("  OK: Editor Scripting Utilities")
    else:
        unreal.log_error("  MISSING: Editor Scripting Utilities")
        unreal.log_error("  -> Edit > Plugins > search 'Editor Scripting' > Enable > Restart")
        all_ok = False

    # Camera Calibration — check for LensFile class
    if _class_exists("LensFile"):
        unreal.log("  OK: Camera Calibration (LensFile available)")
    else:
        unreal.log_error("  MISSING: Camera Calibration")
        unreal.log_error("  -> Edit > Plugins > search 'Camera Calibration' > Enable > Restart")
        all_ok = False

    # CineCameraActor — should always exist but verify
    if _class_exists("CineCameraActor"):
        unreal.log("  OK: CineCameraActor")
    else:
        unreal.log_error("  MISSING: CineCameraActor (unexpected)")
        all_ok = False

    # LevelSequence
    if _class_exists("LevelSequence"):
        unreal.log("  OK: LevelSequence")
    else:
        unreal.log_error("  MISSING: LevelSequence — enable 'Level Sequence Editor' plugin")
        all_ok = False

    # EditorUtilitySubsystem — needed for widget tab
    if _class_exists("EditorUtilitySubsystem"):
        unreal.log("  OK: EditorUtilitySubsystem")
    else:
        unreal.log_error("  MISSING: EditorUtilitySubsystem")
        unreal.log_error("  -> Edit > Plugins > search 'Editor Utility' > Enable > Restart")
        all_ok = False

    return all_ok


def launch_tool():
    """Check prerequisites, create widget if needed, and open the UI."""
    unreal.log("=" * 50)
    unreal.log("VP Post-Render Tool — Initializing...")
    unreal.log("=" * 50)

    if not check_prerequisites():
        unreal.log_error("Please enable missing plugins and restart the editor.")
        return

    unreal.log("All prerequisites met.")
    unreal.log("-" * 50)

    # Build and open the widget
    from post_render_tool.widget_builder import open_widget
    unreal.log("Opening VP Post-Render Tool UI...")
    open_widget()

    unreal.log("=" * 50)
    unreal.log("VP Post-Render Tool ready.")
    unreal.log("=" * 50)


# Auto-launch on import
launch_tool()
```

- [ ] **Step 2: Verify syntax**

Run:
```bash
cd Content/Python && python3 -c "import ast; ast.parse(open('init_post_render_tool.py').read()); print('OK: init_post_render_tool.py')"
```
Expected: `OK: init_post_render_tool.py`

- [ ] **Step 3: Commit**

```bash
git add Content/Python/init_post_render_tool.py
git commit -m "feat: auto-build and open Blueprint UI on init

import init_post_render_tool now creates the EUW Blueprint asset
and opens the tool UI automatically."
```

---

### Task 6: Syntax Verification for All New/Modified UE-Dependent Modules

**Files:**
- Check: `Content/Python/post_render_tool/widget.py`
- Check: `Content/Python/post_render_tool/widget_builder.py`
- Check: `Content/Python/post_render_tool/ui_interface.py`
- Check: `Content/Python/init_post_render_tool.py`

- [ ] **Step 1: Run AST syntax check on all modified files**

Run:
```bash
cd Content/Python
for f in post_render_tool/widget.py post_render_tool/widget_builder.py post_render_tool/ui_interface.py init_post_render_tool.py; do
  python3 -c "import ast; ast.parse(open('$f').read()); print('OK: $f')"
done
```

Expected: All 4 files print `OK`.

- [ ] **Step 2: Run existing unit tests to verify no regressions**

Run:
```bash
cd Content/Python && python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -v
```

Expected: All existing tests PASS. The pure-Python modules (csv_parser, coordinate_transform, validator) are unchanged, so tests should be unaffected.

- [ ] **Step 3: Commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: address syntax/test issues from blueprint UI changes"
```

(Skip this step if no fixes were needed.)

---

### Task 7: Update Documentation

**Files:**
- Modify: `docs/blueprint-ui-setup.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Rewrite blueprint-ui-setup.md for auto-generation flow**

Replace the entire file with:

```markdown
# VP Post-Render Tool — Blueprint UI

The tool's Blueprint UI is generated and opened automatically via Python.

## Quick Start

In UE Python console:

```python
import init_post_render_tool
```

This will:
1. Check all required plugins are loaded
2. Create the `EUW_PostRenderTool` Editor Utility Widget in `Content/PostRenderTool/`
3. Open the tool UI as an editor tab

## Manual Widget Management

```python
from post_render_tool.widget_builder import open_widget, rebuild_widget, delete_widget

# Open (creates if not exists)
open_widget()

# Force rebuild (delete + create + open)
rebuild_widget()

# Delete the widget asset
delete_widget()
```

## UI Features

- **Browse**: Open file picker for Disguise Designer CSV Dense file
- **CSV Preview**: Shows frame count, focal length range, timecode, sensor width
- **FPS**: Manual FPS setting (1–120) or auto-detect from CSV
- **Import**: Run the full pipeline (LensFile + CineCameraActor + LevelSequence)
- **Open Sequencer**: Open the imported LevelSequence in Sequencer editor
- **Open Movie Render Queue**: Open MRQ for rendering

## Troubleshooting

### Widget not opening
If `open_widget()` fails, try:
1. Check Output Log for errors
2. Verify plugins: `import init_post_render_tool`
3. Rebuild: `from post_render_tool.widget_builder import rebuild_widget; rebuild_widget()`
4. Manual: Right-click `Content/PostRenderTool/EUW_PostRenderTool` → Run Editor Utility Widget

### Widget layout not rendering
If the widget opens but shows a blank panel, the Python @uclass registration may have failed.
Try restarting the UE Editor and running `import init_post_render_tool` again.
```

- [ ] **Step 2: Update CLAUDE.md Architecture section**

In `CLAUDE.md`, update the Architecture section to include the new files:

Change:
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
└── ui_interface.py            # Blueprint UI interface (requires unreal)
```

To:
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
├── widget.py                  # F7: Python @uclass EditorUtilityWidget (requires unreal)
└── widget_builder.py          # F7: EUW Blueprint asset builder (requires unreal)
```

- [ ] **Step 3: Add widget.py to the Gotchas section in CLAUDE.md**

Add after the existing gotchas:

```markdown
- **Widget @uclass registration:** `widget.py` uses `@unreal.uclass()` to register
  `OPostRenderToolWidget` with the UE reflection system. The class MUST be imported
  before `widget_builder.create_widget()` creates the Blueprint asset. `widget_builder.py`
  handles this import automatically.
- **Widget runtime UI construction:** `widget.py` builds the UMG layout in `construct()` at
  runtime. If the UE Python API for `create_widget()` or `add_child()` behaves differently
  across UE versions, the layout may need adjustment.
```

- [ ] **Step 4: Update Commands section in CLAUDE.md**

Add widget-specific commands:

```markdown
# UE Python console — launch tool (creates + opens widget)
import init_post_render_tool

# UE Python console — widget management
from post_render_tool.widget_builder import open_widget, rebuild_widget
open_widget()      # create if needed + open
rebuild_widget()   # delete + recreate + open
```

- [ ] **Step 5: Commit**

```bash
git add docs/blueprint-ui-setup.md CLAUDE.md
git commit -m "docs: update for auto-generated Blueprint UI

Rewrite blueprint-ui-setup.md for Python auto-generation flow.
Update CLAUDE.md architecture, gotchas, and commands."
```

---

### Task 8: Final Review and Commit

**Files:**
- All files from Tasks 1–7

- [ ] **Step 1: Verify complete file list**

Run:
```bash
git status
git diff --stat main
```

Expected changed/created files:
- `Content/Python/post_render_tool/widget.py` (NEW)
- `Content/Python/post_render_tool/widget_builder.py` (NEW)
- `Content/Python/post_render_tool/ui_interface.py` (MODIFIED)
- `Content/Python/init_post_render_tool.py` (MODIFIED)
- `docs/blueprint-ui-setup.md` (MODIFIED)
- `CLAUDE.md` (MODIFIED)

- [ ] **Step 2: Run full syntax check**

Run:
```bash
cd Content/Python
for f in post_render_tool/{widget,widget_builder,ui_interface,pipeline,config,csv_parser,coordinate_transform,validator,lens_file_builder,camera_builder,sequence_builder}.py init_post_render_tool.py; do
  python3 -c "import ast; ast.parse(open('$f').read()); print('OK: $f')"
done
```

Expected: All files print `OK`.

- [ ] **Step 3: Run full unit test suite**

Run:
```bash
cd Content/Python && python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -v
```

Expected: All tests PASS.

- [ ] **Step 4: Verify no untracked files leaked**

Run:
```bash
git status
```

Confirm no unexpected files (`.DS_Store`, `__pycache__`, etc.) are staged.

---

## API Risk Notes

The following UE Python APIs are used but may behave differently across UE versions. The implementation should include try/except fallbacks:

1. **`unreal.create_widget(outer, widget_class)`** — Primary way to create UMG widgets at runtime. If unavailable, fall back to `widget_class()` direct construction.

2. **`panel.add_child(widget)`** — Adding children to VerticalBox/HorizontalBox. Should be available on all PanelWidget subclasses.

3. **`button.on_clicked.add_callable(callback)`** — Binding Python callables to multicast delegates. If `add_callable` is unavailable, try `add_function(self, 'method_name')` or `add_function_unique()`.

4. **`factory.set_editor_property("parent_class", python_class)`** — Setting the parent class of a BlueprintFactory to a Python @uclass. If unavailable, use `BlueprintEditorLibrary.reparent_blueprint()` after creation.

5. **`EditorUtilitySubsystem.spawn_and_register_tab(widget_bp)`** — Opening a widget as an editor tab. If unavailable, fall back to `EditorUtilityLibrary.run_editor_utility_widget()`.

6. **`self.set_content(root_widget)`** — Setting the root widget of a UserWidget at runtime. If unavailable, try `self.widget_tree.root_widget = root_widget`.
