# Path C Production Shot Validation

## Scope

This folder records the first production-shot pass after Path C MRQ validation.
It uses the real CSV `shot 1_take_5_dense.csv` and the project map `/Game/Main`.

## Matrix

| Gate | Status | Evidence |
|---|---|---|
| Merge validation branch to `main` | PASS | commit `169cee9` |
| lanPC plugin formula is full-width | PASS | remote `distortion_math.py` / `build_distortion_material.py` inspection |
| CSV parse metadata | PASS | `path_c_production_import_main.json` |
| Production import in `/Game/Main` | PASS | `path_c_production_import_main.json` |
| Sequence has Path C distortion tracks | PASS | `path_c_production_inspect.json` |
| Production MRQ frame render | PASS | `path_c_production_render.json`, `path_c_production_shot_1_take_5_dense.0000.png` |
| Production UE-vs-Disguise image diff | BLOCKED | `path_c_production_reference_probe.json` |

## Results

- `run_import()` succeeded in `/Game/Main`.
- Generated/updated package: `/Game/PostRender/shot_1_take_5_dense`.
- Generated/updated sequence:
  `/Game/PostRender/shot_1_take_5_dense/LS_shot_1_take_5_dense`.
- FOV report from the import: max FOV error `0.0001 deg`.
- The sequence has a `PostRenderDistortionController` binding with 7 float tracks:
  `K1`, `K2`, `K3`, `CenterU`, `CenterV`, `Aspect`, `DistortionWeight`.
- MRQ rendered one production frame at `1920 x 1080`:
  `path_c_production_shot_1_take_5_dense.0000.png`.

## Blocker

The available local candidate reference images are not a verified matched
Disguise frame for this UE render. Quick probe against:

- `/Volumes/Docs/temp/screen_cam 1 transmission_00000.png`
- `/Volumes/Docs/temp/screen_live cam 1 transmission_00000.png`

shows very large channel differences (`p95 ~= 0.8588`) and substantially
different mean brightness. Treat this as a reference-pairing blocker, not a Path
C shader/controller failure.

## Next Input Needed

Provide or identify the exact Disguise transmission frame that matches:

- CSV: `shot 1_take_5_dense.csv`
- frame: first sequence frame / `0000`
- map/scene: `/Game/Main` equivalent
- resolution: `1920 x 1080` or a known resize rule
- color pipeline: PNG/sRGB or EXR/linear, documented

Once the matched reference is identified, run the production image diff as a
separate gate.
