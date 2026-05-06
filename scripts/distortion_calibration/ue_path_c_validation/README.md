# UE Path C Validation Harness

This folder contains the dedicated validation harness for the Path C custom
post-process material. It must not reuse legacy `LS_shot_*` or `LS_synth_*`
assets as correctness baselines because those assets do not prove the
`PostRenderDistortionControllerComponent` / `DistortionWeight` binding path.

## Scripts

- `ue_path_c_smoke.py`
  - Runs inside UE.
  - Default mode creates a transient `PostRenderDistortionControllerComponent`
    without spawning level actors.
  - Optional `--spawn-actor=1` mode creates a transient `PathCValidation_Camera`
    and adds the component. Use this only in a non-null editor session if
    `-nullrhi` actor spawn is unstable.
  - Binds `/PostRenderTool/Materials/M_PRT_OfficialSensorInverse`.
  - Writes known `K1/K2/K3/CenterU/CenterV/Aspect/DistortionWeight`.
  - Emits JSON inspection.

- `compare_path_c_render.py`
  - Runs on Mac.
  - Compares UE render output against a vectorized Python reference matching
    `distortion_math.official_sensor_inverse_uv`.
  - Supports `--reference-base` so K-axis checks can use the UE identity render
    as the source image and avoid confusing shader geometry with UE texture
    import / PNG / tonemapping color transforms.
  - Emits JSON and Markdown metrics.
  - Reports missing UE render output as `BLOCKED`, not as shader failure.

- `ue_path_c_mrq_render.py`
  - Runs inside an already-open UE Editor via `remote_execution`.
  - Creates timestamped `PathCValidation_*` level/sequence assets only under
    `/Game/PathCValidation`.
  - Renders `identity`, `k1`, `k2`, and `k3` MRQ frames to
    `C:/temp/ue-remote/path_c_validation_render/<case>/`.
  - Writes `C:/temp/ue-remote/path_c_mrq_render.json`.

## Smoke Command

```bash
scp scripts/distortion_calibration/ue_path_c_validation/ue_path_c_smoke.py \
    lanpc:C:/temp/ue-remote/ue_path_c_smoke.py

printf '%s\n' \
  '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" "E:/RenderStream Projects/test_0311/test_0311.uproject" -nullrhi -unattended -nop4 -ExecutePythonScript="C:/temp/ue-remote/ue_path_c_smoke.py"; exit $LASTEXITCODE' \
  | ssh lanpc powershell -NoProfile -ExecutionPolicy Bypass -Command -

scp lanpc:C:/temp/ue-remote/path_c_smoke.json \
    validation_results/path_c_validation/path_c_smoke.json
```

## Render Compare Commands

```bash
scp scripts/distortion_calibration/uv_probe_3840x2160.exr \
    scripts/distortion_calibration/ue_path_c_validation/ue_path_c_mrq_render.py \
    lanpc:C:/temp/ue-remote/

ssh lanpc \
  '"D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/ue_path_c_mrq_render.py'

mkdir -p validation_results/path_c_validation/renders
scp lanpc:C:/temp/ue-remote/path_c_mrq_render.json \
    validation_results/path_c_validation/path_c_mrq_render.json
scp 'lanpc:C:/temp/ue-remote/path_c_validation_render/identity/path_c_identity.0000.png' \
    validation_results/path_c_validation/renders/path_c_identity.png
scp 'lanpc:C:/temp/ue-remote/path_c_validation_render/k1/path_c_k1.0000.png' \
    validation_results/path_c_validation/renders/path_c_k1.png
scp 'lanpc:C:/temp/ue-remote/path_c_validation_render/k2/path_c_k2.0000.png' \
    validation_results/path_c_validation/renders/path_c_k2.png
scp 'lanpc:C:/temp/ue-remote/path_c_validation_render/k3/path_c_k3.0000.png' \
    validation_results/path_c_validation/renders/path_c_k3.png

python3 scripts/distortion_calibration/ue_path_c_validation/compare_path_c_render.py \
  --case identity \
  --input-probe scripts/distortion_calibration/uv_probe_3840x2160.exr \
  --ue-render validation_results/path_c_validation/renders/path_c_identity.png \
  --reference-base validation_results/path_c_validation/renders/path_c_identity.png \
  --output-json validation_results/path_c_validation/identity_compare.json \
  --output-md validation_results/path_c_validation/identity_compare.md
```

Repeat with `--case k1`, `--case k2`, and `--case k3` while keeping
`--reference-base validation_results/path_c_validation/renders/path_c_identity.png`.
