# Timecode Sync — Design Spec (v2)

**Date**: 2026-05-13
**Status**: Draft v2 (incorporated CodeX review fixes)
**Topic**: Disguise CSV → UE rendered frames ↔ on-set footage 逐帧 SMPTE timecode 同步

**v2 changes from v1**:
- TimecodeSource 对象模型订正:写到 `UMovieSceneSection.TimecodeSource`,不是不存在的 `UMovieScene` setter
- 加 50 fps 支持(当前 production take_4 实际帧率)
- MRQ 文件名走原生 `UMoviePipelineOutputSetting.FrameNumberOffset`,删除"post-render rename"兜底
- 取消 MRQ auto post-render hook(跟当前 UI 手动开 MRQ 流程冲突),改"渲完手动 Patch EXR Timecode"按钮
- Reference Plate (G3) 拆到 P1/P2,加 `MediaCompositing/MediaAssets` plugin 依赖
- EXR header writer 列三个候选,P1 spike 后选
- 明确 `start_timecode` 是 `trim_static_padding` 之后的 trimmed render start

---

## 1. Problem

PostRenderTool 当前把 Disguise CSV 转成 UE LevelSequence + Custom MovieScene Track + DataAsset 时,**丢掉了 CSV 自带的 SMPTE timecode**:

- `csv_parser.py:85-86` 把 `timestamp` 列(`09:44:23.22`)只存成 `CsvDenseResult.timecode_start/end: str`,未做结构化解析,逐帧 `FrameData` 无 timecode 字段
- `sequence_builder.py:113-114` 把 LevelSequence playback range 设为 `[0, frame_span]`(归零),Camera Cut Section / UPostRenderCameraSection 也用 sequence-local `[0, frame_span]`,且 section 上没设 `TimecodeSource`
- MRQ 渲出的 EXR 文件名是 sequence-local 0..N,跟现场拍摄 timecode 没关联
- EXR header 不携带 SMPTE timecode 标准属性
- 没有现场实拍 plate 作为 sequence 内 visual reference
- 没有 OTIO sidecar,下游 DI/合成 拿不到 conform 元数据

结果:渲出的序列帧无法跟现场带 timecode 的 ProRes/MOV 实拍视频做**逐帧对应**。

## 2. Goals(分 P0 / P1 / P2)

### P0 — MVP(必交付,覆盖核心痛点)
- **G1** Sequencer UI 切到 Timecode 显示时,显示现场拍摄的 SMPTE timecode
- **G5** MRQ 渲出的 EXR 文件名带 absolute CSV frame number(e.g. `render.0625914.exr`),下游可按文件名手动 conform
- **G6** 链路 fail-fast 优先,在 asset mutation 之前完成所有校验

### P1 — 自动 conform 升级
- **G2** EXR header 内嵌 OpenEXR 标准 `timeCode` + `framesPerSecond` 属性,DaVinci 19+ / Nuke / Resolve 自动识别 timecode
- **G4** 渲完后输出 OTIO sidecar(`.otio`),描述 CG render layer + timecode 元数据,下游一次 import 完成 conform

### P2 — Visual verification
- **G3** Sequencer 里挂现场实拍视频作为 MediaPlate,按 embedded SMPTE timecode 自动对齐,渲之前就能视觉验证对齐

## 3. Non-Goals

- 不解决 Disguise 端 LTC genlock 配置(plugin 只读 CSV)
- 不为现场视频做画面解码 / 时间码 OCR(burn-in 不被支持,只读 embedded metadata)
- 不改 Path C distortion 算法 / DataAsset schema / Section template evaluator 逻辑
- 不改 LevelSequence playback range 形式(见 §4 — section 上挂 TimecodeSource,不动 playback range)
- 不改变当前"plugin 预填 MRQ queue + 用户手动开 MRQ 渲"的流程;不引入 auto post-render hook
- 暂只支持 `24 / 23.976 / 25 / 29.97 / 30 / 50 / 59.94 / 60` fps

## 3.5 trim_static_padding 语义(影响所有 timecode 写入)

`pipeline.py:129` 在 build asset 之前调 `trim_static_padding(csv_result)`,会把首尾静止帧裁掉,**`csv_result.timecode_start/end` 同步指向 trimmed motion segment 的首尾**(`csv_parser.py:388-395`)。

本 spec 所有 `start_timecode` / `start_csv_frame` / Section TimecodeSource / MRQ FrameNumberOffset / EXR timecode / OTIO start_frame **统一以 trimmed 之后的 `csv_result.frames[0]` 为锚点**。意味着:

- 渲出的第一帧 = trimmed motion segment 的第一帧
- Sequencer 时间轴 frame 0 对应的 SMPTE = trimmed start 的 timecode
- 现场视频如果包含 trim 掉的静止段,attach plate 时需要按 trimmed start 对齐(不是 raw CSV start)

## 4. Key Insight — Section.TimecodeSource(订正 v1 错误)

v1 spec 写错了:`UMovieScene` 没有 `SetEarliestTimecodeSource` setter。UE 5.7 `MovieScene.cpp:1854` 的 `GetEarliestTimecodeSource()` 是 getter,扫描所有 sections 取最小的 `TimecodeSource`。真正的字段在 `UMovieSceneSection`:

- `MovieSceneSection.h:181-198`:`FMovieSceneTimecodeSource` USTRUCT,含 `FTimecode Timecode` + `int32 DeltaFrame`
- `MovieSceneSection.h:790-793`:`UPROPERTY() FMovieSceneTimecodeSource TimecodeSource;` 在每个 Section 上

**修正方案**:在 sequence_builder 创建完 Camera Cut Section + UPostRenderCameraSection 后,通过 C++ wrapper 设这两个 section 的 `TimecodeSource`:

```cpp
// PostRenderToolBuildHelper.h - 新 UFUNCTION
UFUNCTION(BlueprintCallable, Category="PostRenderTool|Sequencer")
static void SetSectionTimecodeSource(
    UMovieSceneSection* Section,
    int32 Hours, int32 Minutes, int32 Seconds, int32 Frames,
    bool bDropFrame,
    int32 DeltaFrame);
```

Sequencer UI 读 `MovieScene::GetEarliestTimecodeSource()`,从 sections 聚合;只要每个 section 都设了同一个 TimecodeSource,UI 显示就对。

evaluator 行为完全不变(TimecodeSource 只影响 UI 显示和 `GetEarliestTimecodeSource` 查询)。

## 5. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Disguise CSV (timestamp + frame_number + camera data)               │
└────────────────────────┬────────────────────────────────────────────┘
                         ↓
┌────────────────────────┴────────────────────────────────────────────┐
│ csv_parser (改造):                                                   │
│   - Timecode dataclass + parse()                                    │
│   - FrameData.timecode                                              │
│   - CsvDenseResult.start_timecode/end_timecode/frame_rate (新增,    │
│     与既有 timecode_start/end: str 并存以保兼容)                     │
│   - SMPTE 等价性校验                                                 │
│   - trim_static_padding 同步更新结构化 timecode                      │
└────────────────────────┬────────────────────────────────────────────┘
                         ↓
        ┌────────────────┼──────────────────┬───────────────────┐
        ↓ P0             ↓ P0               ↓ P1                ↓ P2
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐
│ sequence_    │  │ ui_interface │  │ mrq_exr_         │  │ media_plate_ │
│ builder      │  │ (小改)       │  │ timecode_writer  │  │ builder (新) │
│ (小改)       │  │              │  │ (新)             │  │              │
│              │  │ - MRQ job    │  │                  │  │ - MediaSource│
│ - 每个 Section│  │   preset:    │  │ - 离线 patcher:  │  │ - MediaPlate │
│   设          │  │   FrameNum-  │  │   读 dir + write │  │   或 Media   │
│   Timecode-  │  │   berOffset  │  │   timeCode/      │  │   Track 按   │
│   Source(    │  │   = first_   │  │   framesPerSec   │  │   embedded   │
│   Camera Cut │  │   csv_frame  │  │   to EXR header  │  │   tc 对齐    │
│   + UPostRen-│  │   FileNameF- │  │ - UI 按钮触发    │  │ - Build.cs加 │
│   derCamera) │  │   ormat =    │  │   (不挂渲染 hook)│  │   Media-     │
│              │  │   render.{   │  │                  │  │   Compositing│
│ - playback   │  │   frame_     │  │                  │  │              │
│   range 不变 │  │   number}    │  │                  │  │              │
└──────┬───────┘  └──────────────┘  └──────────────────┘  └──────────────┘
       ↓                                    ↓
       │                            ┌──────────────────┐
       │                            │ otio_export (新) │
       │                            │ - P1             │
       │                            │ - 离线 dump      │
       │                            │   <shot>.otio    │
       │                            └──────────────────┘
       ↓
┌──────────────────────────────────────────────────────────────────────┐
│ LevelSequence + UPostRenderCameraSamples DataAsset                    │
│   每个 Section.TimecodeSource = trimmed start timecode               │
│   Sequencer UI 时间轴显示 SMPTE; CG cam + (P2) plate 同框可视化       │
└──────────────────────────────────────────────────────────────────────┘
       ↓ MRQ render (用户手动开 MRQ 渲, plugin 不接 hook)
┌──────────────────────────────────────────────────────────────────────┐
│ 输出 (P0):                                                            │
│  - render.0625914.exr ... (FrameNumberOffset 让文件名带 absolute     │
│    CSV frame, ZeroPadFrameNumbers=7)                                 │
│                                                                       │
│ 输出 (P1, 用户点 "Patch EXR Timecode" 按钮):                          │
│  - 每个 .exr header 内嵌 SMPTE timeCode + framesPerSecond            │
│  - <shot>.otio sidecar                                               │
└──────────────────────────────────────────────────────────────────────┘
```

## 6. Data Flow

### 6.1 CSV → 内存 Timecode (P0)

`csv_parser.py` 新增:

```python
@dataclass(frozen=True)
class Timecode:
    hours: int
    minutes: int
    seconds: int
    frames: int
    drop_frame: bool
    rate_num: int
    rate_den: int

    @classmethod
    def parse(cls, s: str, fps: float) -> "Timecode": ...
    def to_frames(self) -> int:
    def __str__(self) -> str:    # "09:44:23:22" or "09:44:23;22"
```

**字段策略**:
- `FrameData` 加 `timecode: Timecode`(新)
- `CsvDenseResult` **保留** `timecode_start: str / timecode_end: str`(向后兼容,有外部 import),**新增** `start_timecode: Timecode / end_timecode: Timecode / frame_rate: tuple[int, int]`
- `trim_static_padding(csv_result)` 同步更新结构化字段:trim 后的 `start_timecode = trimmed[0].timecode`,`end_timecode = trimmed[-1].timecode`

**等价性校验**:解析时验证 `frame.frame_number - first.frame_number == frame.timecode.to_frames() - first.timecode.to_frames()`。不一致 → `raise CsvTimecodeMismatch`,附帧号 + 实测值 + 期望值。

**支持帧率**:`24 / 23.976 / 25 / 29.97 / 30 / 50 / 59.94 / 60`。
- Drop-frame:`29.97 ± 0.01` 和 `59.94 ± 0.01` → `drop_frame=True`,分隔符 `;`
- 其他(含 50 fps)→ `drop_frame=False`,分隔符 `:`

### 6.2 LevelSequence Sections → TimecodeSource (P0)

`sequence_builder.py` 改造:

- Camera Cut Section(Step 4 已建)创建后,加一步:

```python
tc = csv_result.start_timecode  # trimmed
unreal.PostRenderToolBuildHelper.set_section_timecode_source(
    camera_cut_section,
    tc.hours, tc.minutes, tc.seconds, tc.frames,
    tc.drop_frame,
    0,  # DeltaFrame = 0 (Section start frame in sequence-local = 0)
)
```

- UPostRenderCameraSection(Step 6 已建)创建后,同样调一次

C++ 端 `PostRenderToolBuildHelper.h/.cpp` 加 UFUNCTION `SetSectionTimecodeSource(...)`(签名见 §4)。

**Playback range / Camera Cut Section range / UPostRenderCameraSection range 全部不动**。

### 6.3 MRQ 文件名 = absolute CSV frame (P0)

CodeX 验证:UE 5.7 `MoviePipelineOutputSetting.h:101` 有 `FrameNumberOffset: int32`,`MoviePipelineBlueprintLibrary.cpp:1059` 会把它加到 `{frame_number}` token。

`ui_interface.open_movie_render_queue` 改造(已有 `create_job_from_sequence` + `ensure_job_has_default_settings`):

```python
# 在 create_job_from_sequence 之后,改 job 的 output setting
output_setting = job.get_configuration().find_or_add_setting_by_class(
    unreal.MoviePipelineOutputSetting
)
output_setting.frame_number_offset = csv_result.frames[0].frame_number  # trimmed first
output_setting.zero_pad_frame_numbers = 7
output_setting.file_name_format = "render.{frame_number}"
# 用户开 MRQ 改 output format 为 EXR, 渲完文件名 = render.0625914.exr
```

**注意**:`csv_result` 在 MRQ 触发时已不在 scope(asset 已建完落盘)。要么把 `first_csv_frame` 持久化到 LevelSequence 或 DataAsset 上(已有 `UPostRenderCameraSamples.GetFirstFrame()`),要么 UI 触发 MRQ 时重读 sample asset。**走重读 sample asset 路径**,因为 `GetFirstFrame()` 是现成的且权威。

### 6.4 EXR Header SMPTE Timecode (P1)

**先做 spike,再选 writer**。Spike 用一帧真实 MRQ 渲出来的 EXR,验证三个候选哪个能在写 `timeCode` + `framesPerSecond` 的同时,**完整保留** MRQ 写的 multipart / channels / compression / pixelAspectRatio 等属性:

| 候选 | 优点 | 风险 |
|---|---|---|
| (a) PyPI `OpenEXR` 包 | 纯 Python,跨平台 | 老的 binding 不支持 multipart,可能丢 channels |
| (b) `oiiotool` CLI(OpenImageIO) | 业界标准,attribute 操作完整 | 系统依赖,Windows 安装不一定原生 |
| (c) `UMoviePipelineImagePassBase` 自定义子类 | 渲染时一次性写对,无 post-process | 改 MRQ output path 复杂度高 |

Spike 任务(implementation plan day-1):
1. 用 MRQ 渲一帧 EXR
2. 依次跑三个 writer 加 `timeCode` 属性
3. 用 `oiiotool --info -v` 对比 header,看 channels / compression / multipart 是否完整
4. 选最干净的方案

**API surface 不变**,只是内部实现不同:

```python
def patch_exr_timecode_in_dir(
    output_dir: str,
    filename_pattern: str,        # "render.{frame:07d}.exr"
    start_csv_frame: int,         # absolute,trimmed (= UPostRenderCameraSamples.GetFirstFrame())
    start_timecode: Timecode,
    fps: float,
) -> int: ...
```

**UI 集成**:加一个 `btn_patch_exr_timecode` 按钮,用户在 MRQ 渲完后**手动**点。**不**注册 MRQ post-render auto hook(跟当前"plugin 预填 queue + 用户手动开 MRQ"流程冲突)。

### 6.5 OTIO Sidecar (P1)

`otio_export.py` 新模块:

```python
def export_sidecar(
    sidecar_path: str,
    shot_name: str,
    cg_render_dir: str,
    cg_filename_pattern: str,
    start_csv_frame: int,         # absolute, trimmed
    frame_count: int,
    start_timecode: Timecode,
    fps: float,
) -> None: ...
```

**OTIO 字段语义先 DaVinci 实测**(CodeX 提示):
- `ImageSequenceReference.start_frame = start_csv_frame` 必填
- `available_range` vs `source_range` 起点用 `RationalTime(0, fps)` 还是 `RationalTime(start_csv_frame, fps)` 取决于 DaVinci 19+ import 行为
- Implementation 阶段 spike:写两种变体,DaVinci 各 import 一次,看哪个能让 timecode 跟现场视频自动对齐

OTIO 不依赖 unreal,可 unit test 写 `RationalTime` 数学和 schema 正确性,DaVinci compatibility 走集成测试。

依赖 PyPI `OpenTimelineIO`(pure Python wheel)。

### 6.6 Reference Plate(P2,有依赖前置条件)

**前置条件**:plugin 必须加 Media plugin 依赖,**当前没有**(`PostRenderTool.Build.cs:21` 只有 `MovieSceneTracks`):

```csharp
// PostRenderTool.Build.cs 增加:
"MediaAssets",        // FileMediaSource, MediaTexture
"MediaCompositing",   // MovieSceneMediaTrack, MovieSceneMediaSection
```

```ini
# PostRenderTool.uplugin Plugins 数组增加:
{ "Name": "MediaCompositing", "Enabled": true },
{ "Name": "MediaPlate",       "Enabled": true }
```

**P2 决策点**:G3 的"视觉对齐"是哪种形态?
- (i) **Timeline metadata-only**:在 sequence 加 `MovieSceneMediaTrack + Section`,Section.MediaSource 指向现场视频,Sequencer **不渲染** plate 画面 — 只为 OTIO/conform 元数据完整
- (ii) **Viewport visual overlay**:加 MediaPlate Actor 或 SceneCapture 后处理,在 viewport / preview 里能实际看到现场画面 + CG cam 叠合

(i) 工作量小但不解决"渲前视觉验证";(ii) 真正解决但需要决定渲染管线(MediaPlate vs Composure)。P2 阶段单独立 spec/plan。

### 6.7 编排层与 UI

`pipeline.py` 改造:
- `run_import` 签名不变(`csv_path`, `fps`)
- 内部多走一遍 timecode 写入(由 sequence_builder 完成)
- 新增 `run_patch_exr_timecode(output_dir, level_sequence_path)`:从 sequence 关联的 DataAsset 读 `GetFirstFrame()` + start timecode,触发 §6.4 writer
- 新增 `run_export_otio(level_sequence_path, output_dir)`:同上拿元数据 + dump sidecar

`widget.py` + `widget-tree-spec.json` 新增 widgets(同步到 `PostRenderToolWidget.h` UPROPERTY,`test_spec_drift` 兜底):

| widget name | type | Phase | 用途 |
|---|---|---|---|
| `btn_patch_exr_timecode` | `UButton` | P1 | 触发 `run_patch_exr_timecode` |
| `txt_render_output_dir` | `UEditableTextBox` | P1 | EXR 输出目录(给 patcher 用) |
| `btn_export_otio` | `UButton` | P1 | 触发 `run_export_otio` |
| `txt_reference_plate_path` | `UEditableTextBox` | P2 | 现场视频路径 |
| `btn_attach_plate` | `UButton` | P2 | 触发 `attach_reference_plate` |

## 7. Components(接口契约一览)

| 文件 | 状态 | Phase | 公开 API surface | 依赖 |
|---|---|---|---|---|
| `csv_parser.py` | 改造 | P0 | `Timecode`,`FrameData.timecode`,`CsvDenseResult.start_timecode/end_timecode/frame_rate`(并存旧 string 字段) | pure Python |
| `sequence_builder.py` | 小改 | P0 | 内部 `set_section_timecode_source(...)` 调 2 次 | unreal + 新 UFUNCTION |
| `ui_interface.py` | 小改 | P0 | `open_movie_render_queue` 预填 `FrameNumberOffset`/filename | unreal |
| `PostRenderToolBuildHelper.h/.cpp` | 改 | P0 | 新 UFUNCTION `SetSectionTimecodeSource(...)` | MovieScene |
| `mrq_exr_timecode_writer.py` | 新 | P1 | `patch_exr_timecode_in_dir(...)` | spike 后选 |
| `otio_export.py` | 新 | P1 | `export_sidecar(...)` | PyPI OpenTimelineIO |
| `pipeline.py` | 改 | P1 | `run_patch_exr_timecode(...)`,`run_export_otio(...)` | 聚合 |
| `widget.py` + spec.json | 改 | P1+P2 | 5 个新 widget,callback 桥接 | — |
| `media_plate_builder.py` | 新 | P2 | `attach_reference_plate(...)`(待 P2 spec) | unreal + ffprobe + Media plugins |
| `PostRenderTool.Build.cs` + `.uplugin` | 改 | P2 | 加 `MediaAssets / MediaCompositing` + `MediaPlate` plugin | — |

## 8. Risk & Fallback

### 8.1 UE 5.7 Python API 暴露面(day-1 必验证)

按 [[feedback_verify_ue_python_api]],写实现前必须 grep `/Users/bip.lan/AIWorkspace/vp/UnrealEngine/` 引擎源给 `file:line` 证据:

| 调用 | 验证状态 | 不可见时 fallback |
|---|---|---|
| `MovieSceneSection.h:790-793 TimecodeSource` UPROPERTY | ✓ 引擎源已确认 | C++ wrapper(已规划) |
| `unreal.FTimecode` / `unreal.FMovieSceneTimecodeSource` Python | ✗ 待 grep | C++ wrapper 接平参数,避免 struct 暴露问题 |
| `MoviePipelineOutputSetting.frame_number_offset` Python | ✗ 待 grep | C++ wrapper or fallback:`set_editor_property` |
| `unreal.MoviePipelineQueueSubsystem` / `create_job_from_sequence` | ✓ 已在用(`ui_interface.py:176-188`) | — |
| MRQ EXR multipart 完整保留 | ✗ 待 spike | 见 §6.4 三个 writer 候选 |
| `UMoviePipelineImagePassBase` Python 子类 | ✗ 仅 §6.4 候选(c)需要 | 候选(a)/(b) 不依赖 |

### 8.2 CSV 解析层(fail-fast 优先)

| 异常 | 处理 |
|---|---|
| timestamp 格式无法解析 | `raise CsvParseError`,附帧号 + 原始字符串 |
| timestamp ↔ frame_number 不等价 | `raise CsvTimecodeMismatch`,列第一处不匹配帧 |
| fps 不在支持表 | `raise UnsupportedFrameRate`,列当前支持的 8 个值 |
| 跨午夜 timecode | 支持 + warning"sequence 跨午夜,建议拆 take" |
| `trim_static_padding` 后 trimmed 帧数 < 2 | 维持现有 trim 逻辑的 fail-fast |

### 8.3 MRQ FrameNumberOffset

| 异常 | 处理 |
|---|---|
| `frame_number_offset` Python 不可见 | C++ wrapper 套 `set_editor_property` |
| 用户在 MRQ 改了 `FileNameFormat` 把 token 删了 | 文件名跟预设不一致,patcher 找不到 → fail-fast 提示用户保留 token |
| MRQ output 格式不是 EXR(选了 PNG) | patcher 跳过 + warning(PNG 无 timecode standard) |

### 8.4 EXR Timecode Patcher

| 异常 | 处理 |
|---|---|
| 选定 writer 装不上(如 oiiotool 缺失) | UI 顶部红条 + 装 / 切 writer 指引 |
| EXR header 已有 `timeCode` 属性(重复 patch) | overwrite + log |
| Patcher 写入后丢 channel / 损坏 multipart | spike 阶段就拦截,选别的 writer;落地后定期回归一帧 |
| Patcher 目录里混了非 sequence 的 EXR | 按 filename pattern regex 过滤,不匹配的跳过 + log |

### 8.5 OTIO Sidecar

| 异常 | 处理 |
|---|---|
| `import opentimelineio` 失败 | UI 顶部红条 |
| 输出路径已存在 | overwrite + log |
| DaVinci import 不识别 source_range 起点 | spike 期间就定 — 走第二种 variant |

### 8.6 sequence_builder 改动回归

最大风险:Section TimecodeSource 写入后,take_4 production diff 是否仍通过。

**预期**:TimecodeSource 只影响 Sequencer UI 显示和 `GetEarliestTimecodeSource()` 查询,evaluator 用 `TickResolution / DisplayRate` 计算,与 TimecodeSource 无关 → 几何完全不变。

**验证**:take_4 完整 import + Sequencer scrub + MRQ 渲一帧 静态 diff vs 现有 baseline,残差应在数值噪声范围。

### 8.7 状态污染防护

延续"asset mutation 之前 fail-fast"原则:

```
Step 0  pre-validate overscan (已有)
Step 0a pre-validate CSV timecode 等价性 ← 新增 (P0)
Step 1  清空 + 重建 LevelSequence (asset mutation 开始)
Step 2  Set frame rate
Step 3  Set playback range (不变)
Step 4  Camera Cut Section
Step 4a Set Camera Cut Section.TimecodeSource ← 新增 (P0)
Step 5  Build sample DataAsset
Step 6  UPostRenderCameraSection
Step 6a Set UPostRenderCameraSection.TimecodeSource ← 新增 (P0)
Step 7  Save
```

trim 在 pipeline 层已经做,sequence_builder 拿到的 `csv_result` 是 trimmed,所有 timecode 写入用 `csv_result.frames[0]` 锚点即可。

## 9. Testing & Verification

### 9.1 Unit tests(pure Python)

新增 `tests/test_csv_parser_timecode.py`:
- 24fps 非 drop / 25fps / **50fps**(production case) / 29.97 drop / 59.94 drop 解析
- 跨午夜(`23:59:58:23` → `00:00:00:01`)
- SMPTE 等价性失败 fail-fast
- 旧 schema(legacy) + 新 schema(spatialmap)双兼容
- `Timecode.to_frames` 数学(drop-frame 帧数计算正确)
- `trim_static_padding` 后 `start_timecode / end_timecode` 跟随 trimmed 首尾

新增 `tests/test_otio_export.py`:
- timeline 结构(CG track)
- `ImageSequenceReference.start_frame == absolute trimmed first frame`
- 两种 source_range variant 都能 serialize(具体哪个 DaVinci 喜欢由集成测试定)

新增 `tests/test_exr_timecode_patcher.py`(离线):
- 渲一帧灰图 EXR → patch → 读 header 验证 `timeCode` + `framesPerSecond` 数值正确
- drop-frame / 50fps / 25fps 三种 case
- Multipart EXR 重 patch 后所有 part 仍可读

### 9.2 UE in-editor 集成测试(lanPC)

按 take_4(50 fps 实际 production case)+ take_5(回归)跑:

**P0 验证**:
1. **回归**:take_4 完整 import,MRQ 渲 1 帧 → diff vs baseline 残差 < 数值噪声
2. **G1**:Sequencer 打开 LevelSequence,View → Show Timecode 切到 SMPTE 显示,时间轴 frame 0 显示 trimmed start timecode
3. **G5**:MRQ 用预填 job 渲 1 帧 → 文件名 = `render.0625914.exr`(或 trimmed first frame number)
4. **G6**:制造 CSV timestamp ↔ frame mismatch,确认 fail-fast 不动 asset

**P1 验证**:
5. **G2**:渲一帧 EXR → 点 "Patch EXR Timecode" → `oiiotool --info -v` 看 `timeCode` 属性 = trimmed start timecode,`framesPerSecond` = `50/1`
6. **G2 multipart**:patch 后所有 channels / compression / pixelAspectRatio 仍可读
7. **G4**:点 "Export OTIO" → DaVinci 19+ import,timeline 自动按 SMPTE timecode 对齐现场视频

**P2 验证**(单独 spec/plan,本 spec 不展开)

### 9.3 Cross-system conform 验证

最终接受标准:把渲出的 EXR sequence + 现场 ProRes 一起拖进 DaVinci 19+,**不指定任何 timecode 参数**,timeline 自动按 SMPTE timecode 对齐。逐帧 scrub,CG 和 plate 时间码一致。

## 10. Rollout

按 P0 / P1 / P2 三段交付。每段独立 mergeable,跑通才动下一段。

不引入 feature flag(按 [[feedback_no_temporary_runtime_switches]])。直接替换。

回退路径:
- csv_parser 改动 → git revert 即可,unit test 兜底
- sequence_builder Section TimecodeSource → 单点 revert
- ui_interface MRQ preset → 单点 revert
- P1/P2 模块全是新文件,删除即恢复

不向后兼容旧 LevelSequence 资产:重新 `run_import` 会清空 + 重建(已有逻辑)。

## 11. Open Questions(implementation plan 阶段调研)

1. `unreal.FTimecode` / `unreal.FMovieSceneTimecodeSource` Python 暴露面 grep 引擎源,给 `file:line` 证据
2. `MoviePipelineOutputSetting.frame_number_offset` Python 是否可见,fallback 是 `set_editor_property` 还是 C++ wrapper
3. EXR header writer 三个候选(OpenEXR python / oiiotool / MRQ output 自定义)spike 选哪个 — day-1 任务
4. OTIO `source_range` 起点用 `RationalTime(0, fps)` 还是 `RationalTime(start_csv_frame, fps)` — DaVinci import 实测
5. P2 阶段 Reference Plate 是 timeline metadata 还是 viewport visual overlay — P2 启动前单独决策

## 12. References

- 现有架构:`docs/superpowers/plans/2026-05-13-custom-moviescene-track.md`
- DataAsset schema:`Source/PostRenderTool/Public/PostRenderCameraSamples.h`
- Evaluator frame mapping:`Source/PostRenderTool/Private/PostRenderCameraSectionTemplate.cpp:107-152`
- 现有 timecode 字段(string-only):`Content/Python/post_render_tool/csv_parser.py:85-86,394-395,576-577`
- `trim_static_padding`:`Content/Python/post_render_tool/csv_parser.py:388`,调用点 `pipeline.py:129`
- 现有 playback range 归零:`Content/Python/post_render_tool/sequence_builder.py:110-114`
- MRQ 集成现状:`Content/Python/post_render_tool/ui_interface.py:167-188`
- Plugin 依赖现状:`Source/PostRenderTool/PostRenderTool.Build.cs:21`,`PostRenderTool.uplugin`
- UE 5.7 Section TimecodeSource 字段:`Engine/Source/Runtime/MovieScene/Public/MovieSceneSection.h:181-198,790-793`
- UE 5.7 GetEarliestTimecodeSource getter:`Engine/Source/Runtime/MovieScene/Private/MovieScene.cpp:1854`
- UE 5.7 MRQ FrameNumberOffset:`Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineCore/Public/MoviePipelineOutputSetting.h:101`
- UE 5.7 MRQ filename token expansion:`Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineCore/Private/MoviePipelineBlueprintLibrary.cpp:1059`
- OpenEXR standard attributes:`https://openexr.com/en/latest/StandardAttributes.html`
- OpenTimelineIO ImageSequenceReference:`https://opentimelineio.readthedocs.io/en/latest/api/python/opentimelineio.schema.html`
- take_4 production reference(50 fps + Free Run timecode):`docs/archive/path_c/d3-production-reference-request.md:38`
