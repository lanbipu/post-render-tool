# Path C D3 UE Import Smoke Attempt

## Status

- Final status: `PASS`
- Open UE Editor import smoke: `PASS`
- Controlled imports: `13 / 13`
- Required distortion tracks: `PASS`
- Report: `validation_results/path_c_d3_exports/canonical/ue_batch_import.json`

The earlier blockers below are retained as execution history. They are no
longer the current status.

## Attempt 1 - Open UE Editor Remote Bridge

- Command: `run_ue.py C:/temp/ue-remote/ue_path_c_batch_import.py`
- Result: `BLOCKED`
- Evidence: no UE Editor process responded on multicast `239.0.0.1:6766` within `4s`.

## Attempt 2 - UnrealEditor-Cmd -nullrhi

- Command:

```text
D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe
E:/RenderStream Projects/test_0311/test_0311.uproject
-nullrhi
-nosplash
-unattended
-ExecutePythonScript=C:/temp/ue-remote/ue_path_c_batch_import.py
```

- Result: `BLOCKED`
- UE created the isolated validation level:
  - `/Game/PathCD3Validation/PathCD3Validation_ImportSmoke_Level`
- UE created the first test `LensFile`:
  - `/Game/PathCD3Validation/Imports/path_c_focal24_k1_p0p5/LF_path_c_focal24_k1_p0p5`
- UE terminated during `CineCameraActor` / controller import setup with:
  - `Unexpected system error - process will terminate`
- No `C:/temp/ue-remote/path_c_d3_batch_import.json` was generated.

## Partial Remote Assets

The crash left only test-prefixed assets under the isolated validation root:

```text
E:/RenderStream Projects/test_0311/Content/PathCD3Validation/PathCD3Validation_ImportSmoke_Level.umap
E:/RenderStream Projects/test_0311/Content/PathCD3Validation/Imports/path_c_focal24_k1_p0p5/LF_path_c_focal24_k1_p0p5.uasset
```

These are not production `PostRender` assets.

## Historical Blocker Classification

The `-nullrhi` failure above was an execution-environment blocker, not evidence
of CSV, shader, controller, or `LevelSequence` failure. The later open-Editor
run supersedes it.

## Attempt 3 - Open UE Editor Remote Bridge

- Command: `run_ue.py C:/temp/ue-remote/ue_path_c_batch_import.py`
- Result: `PASS`
- Remote report: `C:/temp/ue-remote/path_c_d3_batch_import.json`
- Local report: `validation_results/path_c_d3_exports/canonical/ue_batch_import.json`
- Imported controlled cases: `13`
- Failed cases: `0`
- Required tracks found on every imported `LevelSequence`:
  - `Aspect`
  - `CenterU`
  - `CenterV`
  - `DistortionWeight`
  - `K1`
  - `K2`
  - `K3`

Remote bridge note:

- The bridge process returned a local `UnicodeEncodeError` while printing a `✓`
  character to Windows `GBK` stdout.
- UE had already completed the import and wrote the JSON report.
- The JSON report is the authoritative result for this smoke test.

## Final Remote Assets

UE wrote only isolated test-prefix assets:

```text
/Game/PathCD3Validation/PathCD3Validation_ImportSmoke_Level
/Game/PathCD3Validation/Imports/<case>/LF_<case>
/Game/PathCD3Validation/Imports/<case>/LS_<case>
```

Remote filesystem count:

- `1` validation `.umap`
- `13` `LensFile` `.uasset`
- `13` `LevelSequence` `.uasset`
