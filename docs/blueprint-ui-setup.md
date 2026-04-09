# Editor Utility Widget Blueprint Setup Guide

This Blueprint UI must be created manually in UE 5.7 Editor.

## Step 1: Create the Widget

1. Content Browser → right-click → **Editor Utilities → Editor Utility Widget**
2. Name: `EUW_PostRenderTool`
3. Save to: `Content/PostRenderTool/`

## Step 2: Widget Layout (UMG)

```
VerticalBox (root, padding 16)
├── TextBlock "VP Post-Render Tool" (font 18, bold)
├── Spacer (8px)
├── HorizontalBox
│   ├── TextBlock "CSV File:"
│   ├── TextBlock [txt_FilePath] (flex, gray text "No file selected")
│   └── Button [btn_Browse] → "Browse..."
├── HorizontalBox
│   ├── TextBlock "FPS:"
│   ├── SpinBox [spn_FPS] (min=1, max=120, default=24)
│   └── TextBlock [txt_DetectedFPS] (gray, "Auto: --")
├── Spacer (8px)
├── Border (background gray)
│   └── VerticalBox
│       ├── TextBlock "── CSV Preview ──"
│       ├── TextBlock [txt_FrameCount] "Frames: —"
│       ├── TextBlock [txt_FocalRange] "Focal Length: —"
│       ├── TextBlock [txt_Timecode] "Timecode: —"
│       └── TextBlock [txt_SensorWidth] "Sensor Width: —"
├── Spacer (8px)
├── Button [btn_Import] → "Import" (accent color, large)
├── Spacer (8px)
├── Border (results area)
│   └── MultiLineEditableText [txt_Results] (read-only, monospace)
├── Spacer (8px)
├── HorizontalBox
│   ├── Button [btn_OpenSequencer] → "Open Sequencer"
│   └── Button [btn_OpenMRQ] → "Open Movie Render Queue"
```

## Step 3: Blueprint Event Graph

### btn_Browse → OnClicked

```
Execute Python Command:
  "from post_render_tool.ui_interface import cmd_browse; cmd_browse()"
```

Then read the JSON result from Python to update preview text blocks.

Alternatively, use a simpler approach:

```
Python Command → "from post_render_tool import ui_interface; ui_interface._state.csv_path"
→ Set txt_FilePath text
```

### btn_Import → OnClicked

```
Execute Python Command:
  "from post_render_tool.ui_interface import cmd_import; cmd_import('{csv_path}', {fps})"
```

Parse the JSON result and update txt_Results.

### btn_OpenSequencer → OnClicked

```
Execute Python Command:
  "from post_render_tool.ui_interface import open_sequencer; open_sequencer()"
```

### btn_OpenMRQ → OnClicked

```
Execute Python Command:
  "from post_render_tool.ui_interface import open_movie_render_queue; open_movie_render_queue()"
```

## Step 4: Run the Widget

Right-click `EUW_PostRenderTool` → **Run Editor Utility Widget**

## Alternative: Quick Start Without Blueprint

If you prefer to skip the Blueprint UI for now, you can use the tool directly from UE's Python console:

```python
from post_render_tool.pipeline import run_import
result = run_import(r"C:\path\to\shot1_take5_dense.csv", fps=24.0)
print(result.report.format_report())
```
