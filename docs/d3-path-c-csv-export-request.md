# Path C D3 CSV 导出需求

## 目标

这份文档定义用于验证当前 `Path C custom post-process distortion`
实现的 D3 Designer CSV 和 matched Disguise Frame 导出要求。

本批数据不是为了制作 production-looking shot，而是为了获得可归因的
controlled validation frames：

1. 每个 test case 在 D3 Designer 中设置一个固定 camera state。
2. 使用 D3 Designer 默认 `Shot Recorder` export workflow 导出 CSV。
3. 为同一个 camera state 导出 matched Disguise Frame。
4. 把整个 D3 project folder 交给 Codex。
5. Codex 根据默认 export rules、CSV 内容和 image metadata 做 discovery、pairing、整理、重命名。
6. UE 通过 PostRenderTool 导入整理后的 CSV，并重新 render 同一 frame。
7. 对比 UE render output 和 matched Disguise Frame。

## 全局设置

使用 `MR Set` 或 `RenderStream-to-MR-Set` workflow。不要把 probe image
直接 map 到 camera plate。

除非某个 row 明确覆盖，以下 values 必须保持固定：

| Field | Value | 说明 |
|---|---:|---|
| `camera:cam_1.resolution.x` | `1920` | 匹配当前 UE validation profile。 |
| `camera:cam_1.resolution.y` | `1080` | 匹配当前 UE validation profile。 |
| `camera:cam_1.overscan.x` | `1.3` | 写入 CSV；在 MR Set workflow 中不是 blocker。 |
| `camera:cam_1.overscan.y` | `1.3` | 写入 CSV；在 MR Set workflow 中不是 blocker。 |
| `camera:cam_1.overscanResolution.x` | `2496` | 来自 `1920 * 1.3`。 |
| `camera:cam_1.overscanResolution.y` | `1404` | 来自 `1080 * 1.3`。 |
| `camera:cam_1.paWidthMM` | `35.0` | 所有 rows 保持 sensor width 固定。 |
| `camera:cam_1.aspectRatio` | `1.77779` | 所有 rows 保持固定。 |
| `camera:cam_1.aperture` | `18` | 不参与 distortion validation。 |
| `camera:cam_1.focusDistance` | `12` | 不参与 distortion validation。 |

所有 controlled rows 必须保持同一 camera pose：

| Field | Value |
|---|---:|
| `camera:cam_1.offset.x` | `0` |
| `camera:cam_1.offset.y` | `2.25` |
| `camera:cam_1.offset.z` | `-11.6` |
| `camera:cam_1.rotation.x` | `0` |
| `camera:cam_1.rotation.y` | `0` |
| `camera:cam_1.rotation.z` | `-0` |

每个 test case 的导出要求：

- 每个 test case 单独录制一次。
- 不要求手动创建自定义 folder layout。
- 不要求手动按本文档重命名 D3 默认导出的 files。
- 录制期间不要修改 camera parameters。
- 每次录制只对应一个固定 camera state。
- 每次录制导出一个 CSV 和一个 matched Disguise Frame。
- CSV 和 image 必须对应同一个 test case。
- 不要额外 crop。
- 不要 resize。
- 如果导出 UV probe，优先使用 OpenEXR。
- 如果导出 natural MR Set content，用 PNG 可以接受，只做 position-only comparison。
- natural-image position comparison 不强制关闭 tone mapping 和 LUT。
- UV/channel numeric comparison 必须关闭 tone mapping、LUT、gamma transform、color management。

## D3 Designer 默认导出规则

官方文档中该功能名称是 `Shot Recorder`。如果现场 UI 中显示为其他名称，以实际
D3 Designer UI 为准，但后处理会按以下规则先做 discovery：

- `Shot Recorder` 会在 D3 project folder 下创建 `output` folder。
- recording exports 默认进入 `output/shots/<slate>/take_xxx/`。
- 如果未设置 slate，默认可能使用 `no_slate`。
- 每个 `take_xxx` folder 内会包含 `.shot` recording。
- 如果选择 `CSV (Dense)`，同一个 take folder 内会有 `.csv`。
- `CSV (Dense)` 会在每个 timestamp 输出所有 recorded parameters 的 values。
- `CSV (Compact)` 只输出发生变化的 values；本验证不推荐。
- 可以开启 take snapshot 或 screenshot；如果有默认截图输出，也一并保留。

本验证允许使用 D3 Designer default filenames。Codex 后处理阶段会：

- 扫描 `output/shots/**/take_*`。
- 读取每个 CSV 的 camera fields。
- 判断该 take 对应哪个 test case。
- 查找同一 take 或同一导出时间附近的 image。
- 生成整理后的 canonical folder 和 filenames。
- 生成 pairing report，列出每个 CSV/image 的来源路径和识别依据。

如果某个 CSV 内检测到 camera parameters 在录制期间发生变化，该 take 会被标记为
`INVALID_TRANSITION_RECORDING`，不会作为正式 validation evidence。

## Required CSV A - Focal And K Axis

Target case group：

```text
focal_k_axis
```

导出数量：

- `8` 次独立 recordings。
- `8` 个 D3 default CSV files。
- `8` 个 matched Disguise Frame images。

目的：

- 验证 `K1` 在不同 `focalLengthMM` 下的行为。
- 验证 `K2` 和 `K3` 是否与 `K1` 使用同一套 normalization convention。
- 为每个 `focalLengthMM` 提供 identity anchor。

此 group 中每个 test case 固定以下 values，除非 table 明确覆盖：

| Field | Value |
|---|---:|
| `camera:cam_1.centerShiftMM.x` | `0.0` |
| `camera:cam_1.centerShiftMM.y` | `0.0` |

需要导出的 test cases：

| Case ID | `focalLengthMM` | `k1k2k3.x` | `k1k2k3.y` | `k1k2k3.z` |
|---|---:|---:|---:|---:|
| `path_c_focal24_k_zero` | `24.0` | `0.0` | `0.0` | `0.0` |
| `path_c_focal24_k1_p0p5` | `24.0` | `0.5` | `0.0` | `0.0` |
| `path_c_focal30p302_k_zero` | `30.302` | `0.0` | `0.0` | `0.0` |
| `path_c_focal30p302_k1_p0p5` | `30.302` | `0.5` | `0.0` | `0.0` |
| `path_c_focal50_k_zero` | `50.0` | `0.0` | `0.0` | `0.0` |
| `path_c_focal50_k1_p0p5` | `50.0` | `0.5` | `0.0` | `0.0` |
| `path_c_focal30p302_k2_p0p5` | `30.302` | `0.0` | `0.5` | `0.0` |
| `path_c_focal30p302_k3_p0p5` | `30.302` | `0.0` | `0.0` | `0.5` |

## Required CSV B - Center Shift

Target case group：

```text
center_shift
```

导出数量：

- `5` 次独立 recordings。
- `5` 个 D3 default CSV files。
- `5` 个 matched Disguise Frame images。

目的：

- 验证 `centerShiftMM.x` 和 `centerShiftMM.y` 的 mapping。
- 保持 distortion active，让 center shift 在 radial model 中可观测。

此 group 中每个 test case 固定以下 values，除非 table 明确覆盖：

| Field | Value |
|---|---:|
| `camera:cam_1.focalLengthMM` | `30.302` |
| `camera:cam_1.k1k2k3.x` | `0.5` |
| `camera:cam_1.k1k2k3.y` | `0.0` |
| `camera:cam_1.k1k2k3.z` | `0.0` |

需要导出的 test cases：

| Case ID | `centerShiftMM.x` | `centerShiftMM.y` |
|---|---:|---:|
| `path_c_center_k1_p0p5_shift_zero` | `0.0` | `0.0` |
| `path_c_center_k1_p0p5_shiftx_n0p5` | `-0.5` | `0.0` |
| `path_c_center_k1_p0p5_shiftx_p0p5` | `0.5` | `0.0` |
| `path_c_center_k1_p0p5_shifty_n0p5` | `0.0` | `-0.5` |
| `path_c_center_k1_p0p5_shifty_p0p5` | `0.0` | `0.5` |

## Optional CSV C - Production Match

Target case group：

```text
production_match
```

导出数量：

- 至少 `1` 次独立 recording。
- 至少 `1` 个 D3 default CSV file。
- 至少 `1` 个 matched Disguise Frame image。

目的：

- controlled CSVs 通过后，用真实 production camera values 做最终 smoke comparison。

要求：

- 使用真实 production camera values。
- CSV 和 image frame numbers 必须 exact match。
- 不要 crop。
- 不要 resize。
- 使用与 controlled tests 相同的 `MR Set` 或 `RenderStream` workflow。

推荐 case id：

```text
path_c_production_match_frame_<frame_number>
```

## 命名规范

本批数据不要求你手动按以下规范命名。以下 canonical names 会由 Codex 在后处理阶段生成。

整理后的 CSV 和 image files 会按以下规则命名：

- 只使用 lowercase filenames。
- 只使用 ASCII filenames。
- 使用 `_` 分隔。
- 不使用 spaces。
- 不使用中文字符。
- 不使用 parentheses。
- 正数使用 `p`。
- 负数使用 `n`。
- numeric tokens 内的小数点使用 `p`。
- 精确 `0.0` 使用 `zero`。

Examples：

```text
path_c_focal30p302_k1_p0p5.png
path_c_center_k1_p0p5_shiftx_n0p5.png
path_c_production_match_frame_1790.png
```

## 返回目录结构

现场导出时不需要手动创建以下结构。你可以直接返回完整 D3 project folder。

Codex 整理后会生成以下 canonical layout：

```text
path_c_d3_exports/
├── discovery_report.json
├── pairing_report.md
├── focal_k_axis/
│   ├── path_c_focal24_k_zero.csv
│   ├── path_c_focal24_k_zero.png
│   ├── path_c_focal24_k1_p0p5.csv
│   ├── path_c_focal24_k1_p0p5.png
│   ├── path_c_focal30p302_k_zero.csv
│   ├── path_c_focal30p302_k_zero.png
│   ├── path_c_focal30p302_k1_p0p5.csv
│   ├── path_c_focal30p302_k1_p0p5.png
│   ├── path_c_focal50_k_zero.csv
│   ├── path_c_focal50_k_zero.png
│   ├── path_c_focal50_k1_p0p5.csv
│   ├── path_c_focal50_k1_p0p5.png
│   ├── path_c_focal30p302_k2_p0p5.csv
│   ├── path_c_focal30p302_k2_p0p5.png
│   ├── path_c_focal30p302_k3_p0p5.csv
│   └── path_c_focal30p302_k3_p0p5.png
├── center_shift/
│   ├── path_c_center_k1_p0p5_shift_zero.csv
│   ├── path_c_center_k1_p0p5_shift_zero.png
│   ├── path_c_center_k1_p0p5_shiftx_n0p5.csv
│   ├── path_c_center_k1_p0p5_shiftx_n0p5.png
│   ├── path_c_center_k1_p0p5_shiftx_p0p5.csv
│   ├── path_c_center_k1_p0p5_shiftx_p0p5.png
│   ├── path_c_center_k1_p0p5_shifty_n0p5.csv
│   ├── path_c_center_k1_p0p5_shifty_n0p5.png
│   ├── path_c_center_k1_p0p5_shifty_p0p5.csv
│   └── path_c_center_k1_p0p5_shifty_p0p5.png
└── production_match/
    ├── path_c_production_match_frame_<frame_number>.csv
    └── path_c_production_match_frame_<frame_number>.png
```

## 完成检查

- D3 project folder 已清空旧 exports，避免混入历史 take。
- 每个 test case 都有一次独立 recording。
- 每次 recording 期间 camera parameters 保持不变。
- 每次 recording 都导出 `CSV (Dense)`。
- 每个 test case 都有 matched Disguise Frame。
- 可以保留 D3 default folder names 和 filenames。
- 交付时返回完整 D3 project folder，而不是只挑选部分 files。
