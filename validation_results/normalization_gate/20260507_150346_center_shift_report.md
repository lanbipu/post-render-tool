# CenterShift Sweep

- Verdict: **REVIEW**
- Formula tested: `CenterU = 0.5 + csx_mm / sensor_width_mm`

| frame | csx mm | median dx px | expected dx px | +err px | -err px | best sign |
|---|---:|---:|---:|---:|---:|---|
| `disguise_focal30p302_csx_n0p05.exr` | -0.050 | +4.738 | -5.486 | 10.224 | 0.748 | -formula |
| `disguise_focal30p302_csx_n0p10.exr` | -0.100 | +11.252 | -10.971 | 22.224 | 0.281 | -formula |
| `disguise_focal30p302_csx_p0p05.exr` | +0.050 | -5.034 | +5.486 | 10.520 | 0.452 | -formula |
| `disguise_focal30p302_csx_p0p10.exr` | +0.100 | -11.252 | +10.971 | 22.224 | 0.281 | -formula |
