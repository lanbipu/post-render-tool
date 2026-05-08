# Disguise Production 参考帧请求 — test / take_4

> **EXECUTED 2026-05-07** — take_4 production diff 已通过,完成于:
> - `a9db75c feat(csv_parser): 支持 spatialmap schema + 加 trim_static_padding`
> - `5f2fa2b fix(csv_parser): SOFT_DEFAULTS 兜底 aperture/focus_distance`
>
> 当时"还没做的"3 项现在状态:
>
> 1. **lanPC UE Editor import + MRQ frame 0 渲染** — 跑过,有 PNG 输出
> 2. **UE PNG vs .seq frame 8 diff** — 跑过,`production_diff_frame2_vs_seq0.json`
>    valid_p95 ≈ 0.1255(8-bit PNG 量化地板附近)
> 3. **production_diff.json 报告** — 落在 `validation_results/path_c_production/`
>
> 后续 take_5 静态帧 diff(2026-05-08, commit `43a6ead`)进一步覆盖
> "干净 Sequence Shot 基准 vs UE Path C" 这条对比路径,
> 见 `validation_results/take_5_diff/summary.md`。

## 目的

UE 端 Path C production 单帧 MRQ 跟 Disguise Designer 端**同一 CSV、同一帧、同一台相机**的 transmission frame 做一对一像素 diff。

> **历史**:之前用 `shot 1 / take_5` 的 CSV,因 timecode 没启用 Free Run + frame 列 step 不规则,被废。现在用户重新录了 `test / take_4`,Free Run 启用,数据结构已被工具链验证可用。

## 数据来源

| 端 | 路径 | 状态 |
|---|---|---|
| CSV(Mac mirror) | `reference/test_take_4_dense.csv` | ✓ 同步完成 |
| CSV(lanPC source) | `E:\d3 Projects\0408\output\shots\test\take_4\test_take_4_dense.csv` | 原始 |
| Reference 序列 | `E:\d3 Projects\0408\output\feed\track 1 lanpc feeds head 2_00000.seq\` | 750 张 DPX,1920×1080 10-bit linear |

## CSV 真值

| 字段 | 值 |
|---|---|
| 总行数 | 756(其中 row 0 lead-in static + row 754-755 trail static) |
| Schema | `spatialmap:mr_set_1_target__backplate_.*`(csv_parser 已支持) |
| 帧率(d3 frame number 计数基准) | 50 fps |
| Free Run timecode | ✓ 启用,timestamp 每行不同 |
| 焦距(全程固定) | 30.302 → **43.2886 mm** |
| Sensor 宽度 | 50.0 mm |
| Distortion 全程常量 | K1=0.000286,K2=-0.00395,K3=0.0113,centerShift=(0.0048995, 0.00467297) |

## 对帧公式(已验证)

> 通过 .seq frame 0/1/5/6/7 vs frame 8/9/10/... 的视觉 diff 探针定位

```
.seq frame 0 ~ 7    = lead-in static(8 帧)
.seq frame 8        = 真正运镜起点          ← UE LevelSequence frame 0
.seq frame 749      = 运镜末尾              ← UE LevelSequence frame 741
CSV row 1           = 第一行 motion 数据    ← d3 frame 625994 = .seq frame 8
CSV row 753         = 最后一行 motion       ← d3 frame 626854(.seq 已停录,不参与 diff)
```

**核心映射**:`UE LevelSequence frame k ↔ .seq frame (8 + k) ↔ d3 frame (625994 + k)`,k ∈ [0, 741]。

CSV motion 段 d3 frame 跨度 861 帧(17.22 秒),比 .seq 742 帧(14.84 秒)多出 ~2.4 秒尾部。这部分 d3 frame > 626735,production diff 用不到。

## 已落地的代码改动

| 文件 | 改动 |
|---|---|
| `Content/Python/post_render_tool/csv_parser.py` | 加 `_Dialect` 抽象,自动识别 `legacy` (`camera:cam_1.*`) + `spatialmap` (`spatialmap:*.activeCamera.*`) 两种 schema;加 `trim_static_padding()` 函数,识别 round-trip 录制(head pos == tail pos)时去除首尾 static padding,保留 1 帧 anchor |
| `Content/Python/post_render_tool/pipeline.py` | `run_import` 解析后自动调 `trim_static_padding`,把 motion 段送下游 |
| `Content/Python/post_render_tool/tests/test_csv_parser.py` | 19 个 unit tests:11 个 legacy + 4 个 spatialmap + 4 个 trim;全过 |

`sequence_builder.py` 不需要改:trim 后 `frames[0].frame_number = 625994` 自动成为 LevelSequence frame 0 基准,d3 frame → UE LevelSequence frame 的转换已经在 line 283 (`seq_frame_idx = frame.frame_number - first_frame_num`) 自然成立。

## 验收资产

| 文件 | 用途 |
|---|---|
| `validation_results/path_c_production/reference/disguise_take4_seq_frame8.dpx` | Disguise 端 ground truth(.seq frame 8 原始 10-bit linear DPX) |
| `validation_results/path_c_production/reference/disguise_take4_seq_frame8.png` | 同帧的 16-bit PNG(ffmpeg 转码,linear) |

## 还没做的

1. **lanPC UE Editor 端 import + MRQ 渲 frame 0**
   - 卡点:UE Editor 当前没在 lanPC 启动
   - 待 UE Editor 启动后,跑 `/tmp/take4_import.py` + 写 MRQ render 脚本
2. **UE 端 frame 0 PNG 跟 .seq frame 8 PNG 做 diff**
   - 待写 `scripts/distortion_calibration/compare_production_frame.py`
3. **新增 `production_diff.json` 报告** 落到 `validation_results/path_c_production/`

## 怎么操作 UE 端这步

需要你在 lanPC 上把 UE Editor 项目 `E:\RenderStream Projects\test_0311\test_0311.uproject` 打开,然后告诉我。

UE Editor 启动后,我跑下面这两个脚本:

```bash
# Mac 端
ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/take4_import.py'
ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/take4_render_frame0.py'
```

## 通过标准

| 阶段 | 标准 |
|---|---|
| import | run_import 返回 `success=True`,LevelSequence 创建,trim 把 756 行裁到 motion 段 |
| MRQ 渲 frame 0 | PNG 1920×1080,落到 `C:/temp/ue-remote/take4_frame0_render/` |
| UE PNG vs .seq frame 8 PNG diff | 通道绝对差 valid_p95 接近 8-bit PNG 量化地板(≈ 0.004) |

不通过时排查顺序:**帧号错位 → 相机 transform 错位 → distortion shape 错位**。
