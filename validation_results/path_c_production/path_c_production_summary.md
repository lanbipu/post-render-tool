# Path C Production Diff — Re-delivery Spec

用来指导 Disguise 端重出一组干净配对的 CSV + 输出帧,给 Path C production
端到端像素 diff 做验收输入。规格基线 = 已通过验收的 take_5 静态帧
(`validation_results/take_5_diff/summary.md`),production 场景照搬即可。

## A. CSV 输入规格			

| 项 | 要求 |
|---|---|
| 命名 | `<take_name>_dense.csv`,例如 `shot_1_take_5_dense.csv`;文件名 stem 必须跟 Disguise 输出帧的 take 名一致 |
| Schema | Disguise Designer **spatialmap dialect**(自动识别) |
| Header(必须列) | `timestamp, frame, spatialmap:<cam>.activeCamera, spatialmap:<cam>.engineCameraPos.{x,y,z}, spatialmap:<cam>.engineCameraRotation.{x,y,z}, spatialmap:<cam>.activeCamera.resolution.{x,y}, spatialmap:<cam>.activeCamera.fieldOfView{V,H}, spatialmap:<cam>.activeCamera.aspectRatio, spatialmap:<cam>.activeCamera.focalLengthMM, spatialmap:<cam>.activeCamera.paWidthMM, spatialmap:<cam>.activeCamera.centerShiftMM.{x,y}, spatialmap:<cam>.activeCamera.k1k2k3.{x,y,z}` |
| Header(允许缺失) | overscan / overscanResolution / aperture / focus_distance(parser 有 SOFT_DEFAULTS 兜底,不影响 distortion 验收) |
| `frame` 列 | 首行帧号 = Disguise 输出帧的起始帧号(例如 Disguise 出帧 `_00000` → CSV 首行 frame = 这个 take 的录制起点)。不要随手 trim |
| 帧范围 | 静态验收:≥ 2 帧,机位完全静止(参考 `test_take_5_dense.csv` 2 帧法);motion 验收:≥ 24 帧连续(覆盖至少 1 秒 24fps) |
| 镜头参数完整 | `focalLengthMM` / `paWidthMM` / `centerShiftMM.x,y` / `k1k2k3.x,y,z` / `aspectRatio` / `fieldOfViewH` 必须每行有值;空字段会让 parser 跳过该帧 |
| `timestamp` | 从 `00:00:00.00` 起递增,跟 Disguise 内部时间码一致 |
| 文件位置 | `validation_results/path_c_production/<take_name>.csv` |

## B. Disguise 输出帧规格

| 项 | 要求 |
|---|---|
| 帧来源 | **Sequence Shot screenshot**(等价 Transmission Frame 同管道);**不是**:viewport screenshot / trackers feed / live cam preview |
| 与 CSV 的映射 | Disguise 第 N 帧 ↔ CSV 第 N 行 ↔ UE MRQ 输出第 N 帧。文件名帧号必须能反向对到 CSV `frame` 列 |
| 分辨率 | **1920 × 1080**,跟 CSV `resolution.x/y` 严格一致;不要 over-scan resize |
| 色彩管线 | **首选 EXR / linear**(跟 take_5 reference `screen_mr_set_1_00000.exr` 同管道,verified passing);如只能出 PNG,必须明确是 sRGB 还是 linear,在文件名或 sidecar 写清楚 |
| Scene 一致性 | Disguise 端使用的 `mr_set_1_target__backplate_` 场景必须与 UE `/Game/Main` 几何等价 —— LED wall 标签 / 地板网格 / 标志物 / sphere mesh helper 在两端肉眼可比对 |
| 命名约定 | `screen_mr_set_1_<take>_<NNNNN>.exr`,例如 `screen_mr_set_1_shot_1_take_5_00000.exr`,5 位补零帧号 |
| 文件位置 | `validation_results/path_c_production/reference/<take_name>/`,每帧一个文件;静态验收交 1 帧,motion 验收交完整序列 |
| 必须排除 | 不要导出包含 dynamic sky cloud / time-based procedural noise 的天空区域作为唯一比对依据 —— diff 阶段会单独 mask 掉天空 |

## C. 配对自检 checklist(交付前用户自查)

- [ ] CSV 文件 stem 与 Disguise 输出帧文件名里的 take 名一致
- [ ] CSV 第 1 行 `frame` 列数值 = Disguise 第一张输出帧文件名里的帧号
- [ ] CSV `resolution.x/y` = Disguise 输出帧实际像素尺寸
- [ ] CSV `focalLengthMM` / `paWidthMM` 与 Disguise 端镜头记录一致(抽 1 帧人工核对)
- [ ] CSV 行数 ≥ 计划交付的 Disguise 输出帧张数
- [ ] EXR(或 PNG)能在 nuke / Photoshop 正常打开,通道完整
- [ ] 文件按 §A / §B 表格里的"文件位置"放好

## D. 交付后流程(由本工具执行,用户不用操作)

1. CSV → `pipeline.run_import()` → UE Sequence + Path C MID 关键帧
2. MRQ render 对应帧范围到 `validation_results/path_c_production/ue_out/`
3. production diff 脚本(以 take_5 diff 脚本为模板)拉 reference 跟 UE 渲染做像素 diff
4. 输出 `diff_overlay_50_50.png` / `diff_heatmap.png` / `summary.md`,按 take_5 验收口径(几何对齐,忽略 sRGB tone mapping 残差与天空动态噪声)判通过

## References

- 通过验收的同口径范本:`validation_results/take_5_diff/summary.md`
- CSV parser schema 实现:`Content/Python/post_render_tool/csv_parser.py` (spatialmap dialect)
- Path C 主 plan §6:`docs/custom-postprocess-distortion-final-plan.md`
