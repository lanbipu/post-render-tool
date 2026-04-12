# VP Post-Render Tool — Blueprint UI

The tool's UI is built at runtime by Python (`widget.py`), but it injects
itself into a **template Editor Utility Widget Blueprint** that you create
once in the UE Editor.

## Why a manual template?

UE 5.7's `EditorUtilityWidgetBlueprintFactory` creates the root panel with
`bIsVariable = false`, so the compiler emits a UPROPERTY without
`CPF_BlueprintVisible`. Python's `get_editor_property` and `dir()` cannot
see the widget, and `find_child_widget_by_name` also returns `None` on the
spawned instance. Manual creation in the Designer marks the widget as a
variable, producing a script-visible UPROPERTY that Python can access.

## One-time template setup

1. **Content Browser** → navigate to `/Game/PostRenderTool/` (create if missing)
2. Right-click → **Editor Utilities** → **Editor Utility Widget**
3. In the parent class picker, pick **`EditorUtilityWidget`** (the native
   class — *not* a custom subclass)
4. Name the asset **`EUW_PostRenderTool`**
5. **Double-click** to open the Widget Designer
6. From the **Palette**, drag a **Vertical Box** into the Hierarchy as the root
7. Select the Vertical Box. In the **Details** panel:
   - Rename it to **`RootPanel`**
   - **Check the "Is Variable" checkbox** at the top of the Details panel
8. **Compile** (`Ctrl+B`) and **Save** (`Ctrl+S`)
9. Close the Widget Designer

## Quick Start

In UE Python console:

```python
import init_post_render_tool
```

This will:
1. Check all required plugins are loaded
2. Load the `EUW_PostRenderTool` template from `/Game/PostRenderTool/`
3. Spawn the widget as an editor tab
4. Inject the Python-built UI into the template's `RootPanel`

If the template is missing, the log shows the full setup instructions and
re-running the import will pick it up automatically.

## Manual Widget Management

```python
from post_render_tool.widget_builder import open_widget, rebuild_widget, delete_widget

# Load template + spawn tab + inject UI
open_widget()

# Drop cached UI and reopen (does NOT delete the template)
rebuild_widget()

# Destructive: delete the template asset.  You must recreate it (see steps
# above) before the next open_widget() call.
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

### `Template Blueprint not found`
The asset at `/Game/PostRenderTool/EUW_PostRenderTool` does not exist.
Follow the **One-time template setup** section above.

### `Template is missing the 'RootPanel' variable`
The template exists but its root widget is not named `RootPanel` or is not
marked as a variable. Open the template in the Widget Designer, fix the
root widget's name and "Is Variable" checkbox, then compile and save.

### `'RootPanel' is a CanvasPanel, expected VerticalBox`
The root widget is the wrong type. Replace it with a Vertical Box, rename
to `RootPanel`, mark as variable, compile and save.

### Widget tab opens but UI is empty
Check the Output Log for `[widget]` warnings — they include the exact
template constraint that failed and the full setup instructions.
