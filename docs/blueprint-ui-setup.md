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
