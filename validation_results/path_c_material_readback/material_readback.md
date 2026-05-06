# Path C Material Readback Evidence

## Verdict

`PASS`: UE asset readback confirms the saved material asset contains the full-width Path C HLSL line.

This evidence is a direct readback from the UE material asset, not an inference from `set_editor_property()` plus `save_asset()`.

## Command

- UE commandlet: `DumpMaterialExpressionInfo`
- Asset path: `/PostRenderTool/Materials/M_PRT_OfficialSensorInverse`
- Evidence CSV: `validation_results/path_c_material_readback/material_custom_nodes.csv`

## Expected Custom Node

- Node description: `OfficialSensorInverse`
- Expected code line:

```hlsl
float2 r = float2(d.x, d.y / Aspect);
```

## Readback Result

The CSV row for `MaterialExpressionCustom` with description `OfficialSensorInverse` contains:

```hlsl
float2 r = float2(d.x, d.y / Aspect);
```

It also contains the expected final source-UV displacement line:

```hlsl
return UV + fac * d * DistortionWeight;
```
