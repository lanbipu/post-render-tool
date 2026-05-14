# PostRenderTool Plugin — First-Time Setup

This guide covers installing the PostRenderTool plugin into a UE 5.7 project
from scratch. Follow in order.

## 1. Prerequisites

- UE 5.7 (Launcher or Source build)
- macOS: Xcode (for UBT)
- Windows: Visual Studio 2022 with "Game development with C++" workload
- A host `.uproject` to install into
- Required built-in UE plugins enabled in the host project:
  - **Camera Calibration** — provides the `LensFile` asset class and the
    `LensComponent` runtime component that the pipeline attaches to
    `CineCameraActor`. `LensComponent` is NOT a separate plugin; it ships
    inside Camera Calibration. Without this plugin, the import pipeline
    fails at the LensFile step (`AttributeError: module 'unreal' has no
    attribute 'LensFile'`) or the LensComponent step (`Failed to find
    object 'Class /Script/LensComponent.LensComponent'`)
  - **Level Sequence Editor** — required for the `LevelSequence` export
  - `PythonScriptPlugin` / `EditorScriptingUtilities` — auto-enabled by
    this plugin's `.uplugin`, no manual action needed

### P1 timecode-sync (optional — only if using EXR / OTIO conform helpers)

`Patch EXR Timecode` and `Export OTIO Sidecar` widget buttons need two
Python wheels in the UE-embedded Python 3.11 (same `pip install --user`
pattern):

- **`oiio-static-python==3.0.8.1.1`** — OpenImageIO 3.0.8 Python binding
  (statically built, no system OIIO install required). Used in-process
  to write typed SMPTE `timeCode` + rational `FramesPerSecond` attributes
  into MRQ-rendered EXR files so DaVinci 19+ / Nuke / Flame auto-conform.
  Backend swapped from subprocess `oiiotool` CLI on 2026-05-14; see
  `scripts/exr_timecode_spike_report.md` for the swap rationale.
- **`opentimelineio`** — Python wheel for the `.otio` sidecar writer.

Install:

```bash
# macOS / Linux
<UE5.7>/Engine/Binaries/ThirdParty/Python3/.../python3 -m pip install --user oiio-static-python==3.0.8.1.1 opentimelineio
```

```powershell
# Windows
& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" -m pip install --user oiio-static-python==3.0.8.1.1 opentimelineio
```

If you install AFTER UE Editor is already running, the editor caches
`sys.path` at startup — restart the editor, or call `site.addsitedir`
inside your script (as `scripts/integration_p1.py` does).

Optional dev tool: `exrheader.exe` for typed-attribute ground-truth
verification. On lanPC it ships with the `openimageio` conda package at
`C:\Tools\miniforge3\Library\bin\exrheader.exe`. macOS:
`brew install openimageio`.

Without these, the P0 import pipeline still works; only the P1 conform
helpers error out with install instructions.

## 2. Install the plugin

### Option A — Symlink (recommended for development)

```bash
HOST_PROJECT=/path/to/YourProject
ln -sfn /Users/bip.lan/AIWorkspace/vp/post_render_tool \
        "$HOST_PROJECT/Plugins/PostRenderTool"
```

### Option B — Copy (for distribution / shipping)

```bash
cp -R /Users/bip.lan/AIWorkspace/vp/post_render_tool \
      "$HOST_PROJECT/Plugins/PostRenderTool"
```

## 3. Build the plugin

1. Close the host UE Editor if it is running
2. Right-click the `.uproject` → "Services" → "Generate Xcode Project"
   (macOS) or "Generate Visual Studio project files" (Windows)
3. Open the host project's `.uproject`
4. UE will detect the new C++ plugin and prompt:
   *"The following modules are missing or built with a different engine
   version: PostRenderTool. Would you like to rebuild them now?"*
5. Click **Yes** and wait for UBT to finish (30s – 5min)
6. Verify success: Edit → Plugins → search "Post-Render" → the plugin
   should appear with a green checkmark under "Virtual Production"

## 4. Author the Blueprint (first time only)

If `Content/Blueprints/BP_PostRenderToolWidget.uasset` does not exist yet
(fresh repo), create it:

1. Content Browser → Plugins → VP Post-Render Tool Content → Blueprints
2. Right-click → Blueprint Class → search `PostRenderToolWidget`
3. Select `UPostRenderToolWidget` → click Select
4. Name the new asset `BP_PostRenderToolWidget`
5. Double-click to open the Designer
6. Delete the default `CanvasPanel_0` root, drag a `VerticalBox` as the new root, name it `RootPanel`
7. Add widgets to satisfy the BindWidget contract — see
   `Source/PostRenderTool/Public/PostRenderToolWidget.h` for the exact
   list of 26 required names and types
8. Compile (Ctrl+B). If the Compiler Results panel shows
   "A required widget binding X was not found", add the missing widget
9. Save (Ctrl+S)
10. Commit the `.uasset`:
    ```bash
    git add Content/Blueprints/BP_PostRenderToolWidget.uasset
    git commit -m "feat: add BP_PostRenderToolWidget authored layout"
    ```

## 5. Run the tool

In the UE Python console (Output Log → filter dropdown → Python):

```python
import init_post_render_tool
```

The tool panel should appear as a new editor tab.

## 6. Hot reload after Python edits

```python
import importlib
import post_render_tool.widget as w
import post_render_tool.widget_builder as wb
importlib.reload(w)
importlib.reload(wb)
wb.rebuild_widget()
```

This picks up changes to `widget.py` / `widget_builder.py` without
restarting the Editor. (Does **not** pick up C++ UPROPERTY changes — those
require a full rebuild, see below.)

## 7. When C++ changes

Any edit to `PostRenderToolWidget.h` (adding / removing / renaming a
UPROPERTY) requires:

1. Close the UE Editor entirely
2. Rebuild the plugin: `xcodebuild` or via IDE
3. Re-open the host project
4. UMG will recompile `BP_PostRenderToolWidget` against the new contract
5. If a required widget is missing in the Blueprint after the C++ change,
   compile will fail — add the widget in the Designer and try again

Live Coding is **not** reliable for UPROPERTY changes. Always do a full
rebuild.

## 8. Distributing to another machine

To share the plugin with a teammate:

1. (Same platform + same UE version) Zip the whole
   `Plugins/PostRenderTool/` directory including `Binaries/Mac/` or
   `Binaries/Win64/`. Teammate unzips into their project's `Plugins/`
   folder and opens the project — no rebuild needed.

2. (Different platform or version) Zip everything **except** `Binaries/`.
   Teammate unzips, opens project, accepts the rebuild prompt. Requires
   their machine to have Xcode / Visual Studio installed.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Plugin not visible in Edit → Plugins | Plugin directory not under `Plugins/` | Check the `Plugins/PostRenderTool/` path |
| Rebuild fails: "module not found" | Missing Build.cs dependency | Check `Source/PostRenderTool/PostRenderTool.Build.cs` |
| BP compile error: "binding X not found" | Blueprint widget missing/misnamed | Add widget in Designer matching `PostRenderToolWidget.h` |
| Python: `'btn_browse' UPROPERTY is None` | Blueprint not compiled against current C++ | Compile BP in Designer, restart tool |
| `ModuleNotFoundError: post_render_tool` | Plugin Python path not mounted | Restart UE Editor, verify plugin enabled |
| Tool panel opens but buttons do nothing | Events not bound | Hot-reload `widget.py`, check Output Log for `[widget]` errors |
| `module 'unreal' has no attribute 'LensFile'` during Import | Camera Calibration plugin disabled | Edit → Plugins → enable "Camera Calibration" → restart Editor |
| `Failed to find object 'Class /Script/LensComponent.LensComponent'` | Same as above — `LensComponent` lives inside Camera Calibration, not a separate plugin | Enable Camera Calibration, not some "Lens Component" plugin (which is hidden and not intended for direct user enable) |
