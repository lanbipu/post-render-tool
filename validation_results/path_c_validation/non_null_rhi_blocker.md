# Path C Non-Null RHI Blocker

## Verdict

`RESOLVED FOR VALIDATION`: headless non-null RHI execution did not reach the
Python evidence write, but the already-open UE Editor remote execution path
successfully rendered the MRQ validation frames.

The original failure remains classified as a remote/headless render environment
blocker, not as a Path C shader or controller code failure.

## Command

```powershell
& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" `
  "E:/RenderStream Projects/test_0311/test_0311.uproject" `
  -unattended -nop4 `
  -ExecutePythonScript="C:/temp/ue-remote/ue_path_c_smoke.py --spawn-actor=1 --output-json=C:/temp/ue-remote/path_c_smoke_spawn_actor.json"
```

## Observed Failure

The process initialized D3D12 successfully, then terminated before the Python
script could write `path_c_smoke_spawn_actor.json`.

Observed terminal lines:

```text
LogRHI: Using Default RHI: D3D12
LogD3D12RHI: Failed to create swapchain with the following parameters:
Unexpected system error - process will terminate
```

## Impact

- `-nullrhi` transient controller smoke remains valid and passed.
- Open UE Editor remote execution completed actor-spawn smoke and MRQ rendering.
- Identity and K-axis render gates now use these evidence files:
  - `validation_results/path_c_validation/path_c_mrq_render.json`
  - `validation_results/path_c_validation/renders/path_c_identity.png`
  - `validation_results/path_c_validation/renders/path_c_k1.png`
  - `validation_results/path_c_validation/renders/path_c_k2.png`
  - `validation_results/path_c_validation/renders/path_c_k3.png`
