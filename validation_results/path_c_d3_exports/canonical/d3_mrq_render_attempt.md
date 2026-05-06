# Path C D3 MRQ Render Attempt

## Status

- Final status: `PASS`
- MRQ dispatch: `PASS`
- UE render outputs: `13 / 13`
- Local render folder: `validation_results/path_c_d3_exports/ue_renders`
- Dispatch report: `validation_results/path_c_d3_exports/canonical/d3_mrq_render.json`

The initial duplicated-map crash below is retained as execution history. It is
no longer the current status.

## Attempt

- Source map: `/Game/Main`
- Intended render map: `/Game/PathCD3RenderValidation/PathCD3Render_Main`
- Script: `scripts/distortion_calibration/ue_path_c_validation/ue_path_c_d3_mrq_render.py`
- Remote report: `C:/temp/ue-remote/path_c_d3_mrq_render.json`
- Local report: `validation_results/path_c_d3_exports/canonical/d3_mrq_render.json`
- Render output: `validation_results/path_c_d3_exports/ue_renders/<case>/<case>.0000.png`

## Historical Crash Evidence

Pulled logs:

- `validation_results/path_c_d3_exports/remote_logs/d3_mrq_crash_test_0311.log`
- `validation_results/path_c_d3_exports/remote_logs/d3_mrq_crash_context.runtime-xml`

Key UE log message:

```text
Old world /Game/PathCD3RenderValidation/PathCD3Render_Main.PathCD3Render_Main not cleaned up by garbage collection while loading new map
Fatal error: [File:D:\build\++UE5\Sync\Engine\Source\Editor\UnrealEd\Private\EditorServer.cpp] [Line: 2524]
World Memory Leaks: 2 leaks objects and packages.
```

## Historical Interpretation

The crash happened before the 13 D3 controlled CSVs were imported into the render
map and before MRQ dispatch. It was caused by the validation script duplicating
`/Game/Main` and immediately loading the duplicated map while UE still saw a
Python-held `World` reference.

This does not invalidate:

- D3 export intake / pairing.
- D3 controlled CSV parser validation.
- D3 controlled CSV UE import smoke in `/Game/PathCD3Validation`.

## Follow-up Fix

`ue_path_c_d3_mrq_render.py` was updated to release the duplicated asset reference
and force Python / UE garbage collection before loading the duplicated map.

The next attempt was run after reopening UE Editor and completed successfully.

## Successful Attempt

- Source map: `/Game/Main`
- Duplicated render map: `/Game/PathCD3RenderValidation/PathCD3Render_Main`
- Imported controlled CSVs: `13 / 13`
- Failed imports: `0`
- MRQ jobs: `13`
- Output resolution: `1920x1080`
- Output root: `C:/temp/ue-remote/path_c_d3_render`

