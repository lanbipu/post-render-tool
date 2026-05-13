# Timecode Sync — Design Spec

**Date**: 2026-05-13
**Status**: Draft (awaiting user review)
**Topic**: Disguise CSV → UE rendered frames ↔ on-set footage 逐帧 SMPTE timecode 同步

---

## 1. Problem

PostRenderTool 当前把 Disguise CSV 转成 UE LevelSequence + Custom MovieScene Track + DataAsset 时,**丢掉了 CSV 自带的 SMPTE timecode**。具体表现:

- `csv_parser.py` 把 `timestamp` 列(`09:44:23.22`)只存成 `CsvDenseResult.timecode_start/end: str`,未做结构化解析,逐帧 `FrameData` 无 timecode 字段
- `sequence_builder.py:113-114` 把 LevelSequence playback range 设为 `[0, frame_span]`(归零),Camera Cut Section / UPostRenderCameraSection 也用 sequence-local `[0, frame_span]`
- MovieScene 上没有 `EarliestTimecodeSource` 元数据
- MRQ 渲出的 EXR 文件名带 `{frame_number}` token 但 = sequence-local 0..N,跟现场拍摄 timecode 没有任何关联
- EXR header 不携带 SMPTE timecode 标准属性
- 没有现场实拍 plate 作为 sequence 内 visual reference,渲完才能发现错位
- 没有 OTIO sidecar,下游 DI/合成 工具拿不到 conform 元数据

结果:渲染出的序列帧无法跟现场带 timecode 的 ProRes/MOV 实拍视频做**逐帧对应**,合成/剪辑/校色 全部需要手工对帧。

## 2. Goals

最终交付一套 timecode 完整贯穿的流水线,**渲出的每一帧都能自动 conform 回现场实拍**:

- **G1** Sequencer UI 时间轴切到 Timecode 显示时,直接显示现场拍摄的 SMPTE timecode(如 `09:44:23:22`)
- **G2** MRQ 渲出的 EXR 文件,每一帧 header 内嵌 OpenEXR 标准 `timeCode` + `framesPerSecond` 属性,DaVinci 19+ / Nuke / Resolve / Flame 自动识别
- **G3** Sequencer 里可挂现场实拍视频作为 Media Track,按 embedded SMPTE timecode 自动对齐 sequence 时间轴,渲之前就能视觉验证对齐
- **G4** 渲完后输出 OTIO sidecar(`.otio`),描述 CG render + reference plate + timecode 元数据,DaVinci/Nuke Studio 一次 import 完成 conform
- **G5** EXR 文件名带 absolute CSV frame number(e.g. `render.0625914.exr`),作为人工对帧兜底
- **G6** 整条链路 fail-fast 优先,在 asset mutation 之前完成所有校验

## 3. Non-Goals

- 不解决 Disguise 端的 LTC genlock 配置(plugin 只读 CSV 输出,不触达 Disguise project)
- 不为现场视频做画面解码 / 时间码 OCR(burn-in 时间码不被支持,只读 embedded metadata)
- 不改 Path C 的 distortion 算法 / DataAsset schema / Section template evaluator 逻辑
- 不改 Sequencer-local playback range 形式(见 §4 关键洞察 — 用 MovieScene SourceTimecode 而不是改 playback range)
- 暂不支持非 24/23.976/25/29.97/30/59.94/60 fps

## 4. Key Insight — 不改 playback range,挂 SourceTimecode

读 `PostRenderCameraSectionTemplate.cpp:130-152` 后发现,evaluator 已经做了 sequence-local-frame ↔ absolute-CSV-frame 的双向映射:

```cpp
LocalDisplayTime = DisplayTime - SectionStartDisplay;            // sequence-local frame
AssetFrameOffset = LocalDisplayTime + SampleAsset->GetFirstFrame();  // ABSOLUTE CSV frame
SampleAsset->FindBoundingIndices(FFrameNumber(AssetFrameOffset), ...);
```

`UPostRenderCameraSamples.SourceFrameNumbers` 已经是 absolute CSV frame(`pack_samples` 直接 append `frame.frame_number`)。

**这意味着**:不需要把 LevelSequence playback range / Camera Cut Section / UPostRenderCameraSection 改成 absolute frame。只要在 `UMovieScene` 上挂 `EarliestTimecodeSource = csv_result.start_timecode`,Sequencer UI 切到 Timecode 显示模式时会自动把 sequence-local frame 0 渲染为 `09:44:23:22`。

收益:
- sequence_builder 改动量小 → take_4 production diff 回归风险低
- Section template / Custom Track / DataAsset 全部不动
- evaluator 行为不变

## 5. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Disguise CSV (timestamp HH:MM:SS:FF + frame 625914 + camera data)   │
└────────────────────────┬────────────────────────────────────────────┘
                         ↓
┌────────────────────────┴────────────────────────────────────────────┐
│ csv_parser (改造):                                                   │
│   - Timecode dataclass + parse(s, fps)                              │
│   - FrameData 加字段 timecode: Timecode                              │
│   - CsvDenseResult 加 start_timecode/end_timecode/frame_rate         │
│   - SMPTE 等价性校验 (timecode ↔ frame_number)                       │
└────────────────────────┬────────────────────────────────────────────┘
                         ↓
        ┌────────────────┼────────────────┬────────────────┐
        ↓                ↓                ↓                ↓
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ sequence_    │  │ media_track_ │  │ mrq_exr_     │  │ otio_export  │
│ builder      │  │ builder (新) │  │ timecode_    │  │ (新)         │
│ (小改)       │  │              │  │ writer (新)  │  │              │
│              │  │ - ffprobe    │  │              │  │ - OpenTime-  │
│ - MovieScene │  │   读现场视频 │  │ - MRQ post-  │  │   lineIO     │
│   挂         │  │   embedded   │  │   render     │  │ - timeline   │
│   SourceTC   │  │   timecode   │  │   hook       │  │   = CG render│
│ - playback   │  │ - Media      │  │ - 给每帧 EXR │  │     layer +  │
│   range 不变 │  │   Track 按   │  │   补 timeCode│  │     plate    │
│              │  │   tc 对齐    │  │   attr       │  │     ref +    │
│              │  │              │  │              │  │     metadata │
└──────┬───────┘  └──────────────┘  └──────────────┘  └──────────────┘
       ↓
┌──────────────────────────────────────────────────────────────────────┐
│ LevelSequence 资产 + UPostRenderCameraSamples DataAsset               │
│   (MovieScene 上挂 SourceTimecode = csv.start_timecode)              │
│   Sequencer UI 时间轴显示 SMPTE timecode, CG cam + plate 同框可视化   │
└──────────────────────────────────────────────────────────────────────┘
       ↓ MRQ render
┌──────────────────────────────────────────────────────────────────────┐
│ 输出:                                                                 │
│  - render.0625914.exr ...  (文件名带 absolute CSV frame number)      │
│  - 每个 .exr header 内嵌 SMPTE timeCode + framesPerSecond            │
│  - <shot>.otio sidecar (CG + plate + timecode timeline)              │
└──────────────────────────────────────────────────────────────────────┘
```

**5 个新增/修改单元,boundary 解耦**:

| 单元 | 职责 | 依赖 | 独立测试 |
|---|---|---|---|
| `csv_parser`(改) | Timecode 解析 + SMPTE 等价校验 | pure Python | ✓ unit test |
| `sequence_builder`(小改) | MovieScene SourceTimecode 注入 + filename pattern 用 absolute frame | unreal + C++ wrapper(若需) | UE in-editor |
| `media_track_builder`(新) | 现场视频按 embedded TC 自动对齐挂进 sequence | unreal + ffprobe | UE in-editor + ffprobe mock |
| `mrq_exr_timecode_writer`(新) | MRQ render hook,EXR header 补 timeCode 属性 | unreal + PyPI OpenEXR | 离线对已渲目录跑 |
| `otio_export`(新) | 渲完 dump `.otio` sidecar | PyPI OpenTimelineIO | unit test + DaVinci import |

## 6. Data Flow

### 6.1 CSV → 内存 Timecode

`csv_parser.py` 新增:

```python
@dataclass(frozen=True)
class Timecode:
    hours: int
    minutes: int
    seconds: int
    frames: int
    drop_frame: bool          # 29.97 / 59.94 时 True
    rate_num: int             # e.g. 24000
    rate_den: int             # e.g. 1001

    @classmethod
    def parse(cls, s: str, fps: float) -> "Timecode": ...
    def to_frames(self) -> int:                   # 从 00:00:00:00 起算的总帧数
    def __str__(self) -> str:                     # "09:44:23:22" or "09:44:23;22" (drop)
```

`FrameData` 加字段 `timecode: Timecode`。`CsvDenseResult` 把现有的 `timecode_start: str / timecode_end: str` 替换为 `start_timecode: Timecode / end_timecode: Timecode`,加 `frame_rate: tuple[int, int]`。

**等价性校验**:解析时验证 `frame.frame_number - first.frame_number == frame.timecode.to_frames() - first.timecode.to_frames()`。任何帧不一致 → `raise CsvTimecodeMismatch`,附帧号 + 实测值 + 期望值。

**Drop-frame 判定**:fps 落在 29.97 ± 0.01 / 59.94 ± 0.01 区间 → drop_frame=True,分隔符 `;`。其他 fps → drop_frame=False,分隔符 `:`。`_FRACTIONAL_FPS` 从 sequence_builder 提到 csv_parser 共享。

### 6.2 LevelSequence → MovieScene SourceTimecode

`sequence_builder.py` 改造点(在 Step 2 设 frame rate 后,Step 3 设 playback range 前插入):

```python
# Step 2.5: 注入 MovieScene Source Timecode (Sequencer UI 显示用)
tc = csv_result.start_timecode
unreal.PostRenderToolBuildHelper.set_movie_scene_source_timecode(
    level_sequence,
    tc.hours, tc.minutes, tc.seconds, tc.frames,
    tc.drop_frame,
)
```

C++ 端 `PostRenderToolBuildHelper.cpp` 加一个 UFUNCTION wrapper(理由见 §8.1 — `UMovieScene::SetEarliestTimecodeSource` Python 暴露面待验证,wrapper 是保底):

```cpp
UFUNCTION(BlueprintCallable, Category="PostRenderTool|Sequencer")
static void SetMovieSceneSourceTimecode(
    ULevelSequence* LevelSequence,
    int32 Hours, int32 Minutes, int32 Seconds, int32 Frames,
    bool bDropFrame);
```

**Playback range / Camera Cut Section / UPostRenderCameraSection range 全部不动**(见 §4 关键洞察)。

### 6.3 现场视频 → Media Track 自动对齐

`media_track_builder.py` 新模块:

```python
def attach_reference_plate(
    level_sequence: unreal.LevelSequence,
    video_path: str,
    sequence_start_timecode: Timecode,
    sequence_first_csv_frame: int,
    fps: float,
    *,
    manual_offset_frames: Optional[int] = None,
) -> unreal.MovieSceneMediaTrack:
    """挂现场实拍视频,按 SMPTE timecode 自动对齐."""
```

实现步骤:
1. 调 `ffprobe -v error -select_streams v:0 -show_entries stream_tags=timecode -of default=nw=1:nk=1 <video_path>` 读 embedded SMPTE timecode
2. 若 stdout 空 → 若 `manual_offset_frames is None` → `raise NoEmbeddedTimecodeError`(UI 弹窗指引用户)
3. 解析视频 timecode 字符串 → `Timecode`
4. `offset_frames = video_tc.to_frames() - sequence_start_timecode.to_frames()`(可为负)
5. 创建 `unreal.FileMediaSource`,`set_file_path(video_path)`,作为资产存到 `/Game/PostRender/RefPlates/<asset_name>`
6. 加 `MovieSceneMediaTrack` + Section,section `set_range(offset_frames, offset_frames + video_frame_count)`

**注意**:section start 是 sequence-local frame(因为 sequence playback range 仍归零)。offset 是负数也合法 — section 起点早于 sequence 起点,Sequencer 会自动 clip。

### 6.4 MRQ EXR Per-Frame Timecode Metadata

`mrq_exr_timecode_writer.py` 新模块。两个公开 API:

```python
def write_timecode_to_exr_sequence(
    output_dir: str,
    filename_pattern: str,        # "render.{frame:07d}.exr"
    start_csv_frame: int,         # absolute (e.g. 625914)
    start_timecode: Timecode,
    fps: float,
) -> int:
    """离线对已渲完目录跑,返回处理的文件数."""

def register_mrq_post_render_hook(
    pipeline: unreal.MoviePipeline,
    start_csv_frame: int,
    start_timecode: Timecode,
    fps: float,
) -> None:
    """MRQ pipeline 渲完 callback,自动跑 write_timecode_to_exr_sequence."""
```

**OpenEXR header 写入**(用 PyPI `OpenEXR` 包):
- 属性 `timeCode`:OpenEXR 标准 SMPTE timecode 类型(time + user_data 两个 uint32)。具体 Python binding 类名(`Imath.TimeCode` 或 `OpenEXR.TimeCode`)在 implementation 阶段以装出来的版本为准
- 属性 `framesPerSecond`:有理数类型(numerator / denominator)
- 写之前 read header 现有属性,merge(不覆盖 MRQ 写的 `compression` / `pixelAspectRatio` 等)

**MRQ filename pattern**:LevelSequence playback range 是 sequence-local 0..N,MRQ `{frame_number}` token 默认会输出 0..N。要让文件名是 absolute CSV frame,有两条路:(a) MRQ output config 用支持 frame offset 的 token,(b) post-render 步骤按 absolute CSV frame 重命名。具体选哪条取决于 MRQ 原生 token 调研结果(见 §11 Open Question #3)。

### 6.5 OTIO Sidecar 输出

`otio_export.py` 新模块:

```python
def export_sidecar(
    sidecar_path: str,
    shot_name: str,
    cg_render_dir: str,
    cg_filename_pattern: str,    # "render.{frame:07d}.exr"
    plate_video_path: Optional[str],
    start_csv_frame: int,
    frame_count: int,
    start_timecode: Timecode,
    fps: float,
) -> None: ...
```

输出 OTIO timeline 结构:

```
Timeline (rate = fps, global_start_time = start_timecode)
 ├─ Track "CG Render" (kind=Video)
 │    └─ Clip "shot_<name>_cg"
 │         media_reference = ImageSequenceReference(
 │            target_url_base, name_prefix="render.", name_suffix=".exr",
 │            start_frame=start_csv_frame, frame_zero_padding=7, rate=fps)
 │         source_range = TimeRange(
 │            start_time=RationalTime(start_csv_frame, fps),
 │            duration=RationalTime(frame_count, fps))
 └─ Track "Reference Plate" (kind=Video, 可选)
      └─ Clip "shot_<name>_plate"
           media_reference = ExternalReference(target_url=plate_video_path)
           source_range = TimeRange(...)  # 按 video embedded TC 对齐
```

依赖 PyPI `OpenTimelineIO`(pure Python wheel)。无 `unreal` 依赖,可 unit test。

### 6.6 编排层 `pipeline.py`

`run_import` 加可选参数:

```python
def run_import(
    csv_path: str,
    fps: float,
    *,
    reference_plate_path: Optional[str] = None,
    auto_export_otio: bool = False,
    otio_output_dir: Optional[str] = None,
) -> dict: ...
```

新增独立函数 `run_export_otio(level_sequence_path, output_dir)` 给 UI "渲完后导 OTIO" 按钮单独调。

### 6.7 UI(`widget.py` + `widget-tree-spec.json`)

新增 3 个 widgets,同步到三处(`PostRenderToolWidget.h` UPROPERTY / `widget.py` `_REQUIRED_CONTROLS` / `widget-tree-spec.json`),由 `test_spec_drift` 兜底:

| widget name | type | 用途 |
|---|---|---|
| `txt_reference_plate_path` | `UEditableTextBox` | 现场视频路径 |
| `btn_browse_plate` | `UButton` | 文件选择对话框 |
| `btn_export_otio` | `UButton` | 触发 `run_export_otio` |

## 7. Components(接口契约一览)

| 文件 | 状态 | 公开 API surface | 依赖 |
|---|---|---|---|
| `csv_parser.py` | 改造 | `Timecode` dataclass,`FrameData.timecode`,`CsvDenseResult.start_timecode/end_timecode/frame_rate` | pure Python |
| `sequence_builder.py` | 小改 | API 签名不变,内部新增 Step 2.5(SourceTimecode) | unreal + C++ wrapper |
| `media_track_builder.py` | 新 | `attach_reference_plate(...)` | unreal + ffprobe(系统 PATH) |
| `mrq_exr_timecode_writer.py` | 新 | `write_timecode_to_exr_sequence(...)`,`register_mrq_post_render_hook(...)` | unreal + PyPI OpenEXR |
| `otio_export.py` | 新 | `export_sidecar(...)` | PyPI OpenTimelineIO |
| `pipeline.py` | 改 | `run_import(...)` 加 kwargs,新增 `run_export_otio(...)` | 同上聚合 |
| `widget.py` + spec.json | 改 | 3 个新 widget,callback 桥接 | — |
| `PostRenderToolBuildHelper.h/.cpp` | 改 | 新 UFUNCTION `SetMovieSceneSourceTimecode(...)`(若 Python 直接调不通) | UMG + LevelSequence + MovieScene |

## 8. Risk & Fallback

### 8.1 UE 5.7 Python API 暴露面(day-1 必验证)

按 [[feedback_verify_ue_python_api]],写实现前必须先 grep `/Users/bip.lan/AIWorkspace/vp/UnrealEngine/` 引擎源,列证据。`scripts/probe_ue_timecode_api.py` 是 day-1 任务:

| 调用 | 验证状态 | 不可见时 fallback |
|---|---|---|
| `level_sequence.set_display_rate(FrameRate)` | ✓ 已在用 | — |
| `UMovieScene::SetEarliestTimecodeSource(FMovieSceneTimecodeSource)` | ✗ 待 grep | C++ wrapper `PostRenderToolBuildHelper::SetMovieSceneSourceTimecode(平参数)` |
| `unreal.Timecode` struct | ✗ 待 grep | 同上,wrapper 接平参数避免 struct 暴露问题 |
| `unreal.FMovieSceneTimecodeSource` struct | ✗ 待 grep | 同上 |
| `unreal.MovieSceneMediaTrack` + `MovieSceneMediaSection` | ✗ 待 grep | 降级 `MovieSceneCinematicShotTrack` 套外部 .uasset;最差砍 G3,保留 G1/G2/G4 |
| `unreal.FileMediaSource` + `set_file_path` | ✗ 待 grep | `AssetTools.create_asset` + `set_editor_property("file_path", ...)` |
| MRQ `on_pipeline_finished` callback Python 绑定 | ✗ 待 grep | 降级:不挂 hook,UI 加"渲完后 → 补 EXR timecode"按钮手动一键 |
| `unreal.MoviePipelineExecutorBase` Python 子类 | ✓ 引擎文档有 | — |
| MRQ filename token 支持 absolute CSV frame | ✗ 待查 MRQ doc | 降级:post-render 步骤改名(`render.{seq_local}.exr` → `render.{abs}.exr`) |

### 8.2 CSV 解析层(fail-fast 优先)

| 异常 | 处理 |
|---|---|
| timestamp 格式无法解析 | `raise CsvParseError`,附帧号 + 原始字符串 |
| timestamp ↔ frame_number 不等价 | `raise CsvTimecodeMismatch`,列第一处不匹配帧 |
| fps 不在已知表 | `raise UnsupportedFrameRate`,列当前已知值 |
| 跨午夜 timecode(first=23:59:55, end=00:00:10) | 支持 + warning"sequence 跨午夜,建议拆 take" |

### 8.3 Reference Plate 视频

| 异常 | 处理 |
|---|---|
| 系统 PATH 无 `ffprobe` | UI 弹窗提示装 ffmpeg + 链接;不阻塞 sequence 主流程(plate 是可选) |
| 视频文件不可读 | fail-fast |
| 视频无 embedded SMPTE timecode | fail-fast,弹窗指引用户填手动 offset frame 或先用 ffmpeg 写入 timecode |
| 视频 fps ≠ sequence fps | warning,允许继续 |
| offset 异常大(±1 小时) | warning,允许继续 |

### 8.4 EXR Timecode 写入

| 异常 | 处理 |
|---|---|
| `import OpenEXR` 失败 | plugin 启动检测,UI 顶部红条;不阻塞其他功能 |
| post-render hook 抢锁 | 等 `on_pipeline_finished`,不是 `on_shot_finished` |
| EXR header 已有 `timeCode` 属性 | overwrite + log |
| 输出格式不是 EXR | 跳过 + warning(PNG/JPG 无 timecode metadata 标准) |

### 8.5 OTIO Sidecar

| 异常 | 处理 |
|---|---|
| `import opentimelineio` 失败 | UI 顶部红条 |
| 输出路径已存在 | overwrite + log |
| 相对/绝对路径 | OTIO ExternalReference 用 `file://` 绝对路径,sidecar 注释说明如需移交跑 `otio.adapters` 重写 |

### 8.6 sequence_builder 改动回归

最大风险:Step 2.5 注入 SourceTimecode 后,take_4 production diff 是否仍通过。

**预期**:SourceTimecode 只影响 Sequencer UI 显示和 MovieScene 元数据,evaluator 用 `TickResolution / DisplayRate` 计算,与 SourceTimecode 无关 → 几何完全不变。

**验证**:
- take_4 完整 import + Sequencer scrub + MRQ 渲染 1 帧 静态 diff vs 现有 baseline,残差应在数值噪声范围
- 若 fail → SourceTimecode 注入位置错(可能动到 frame rate / playback range 间接影响),回退到注入前检查

### 8.7 状态污染防护

延续现有"asset mutation 之前 fail-fast"原则:

```
Step 0  pre-validate overscan (已有)
Step 0a pre-validate CSV timecode 等价性 ← 新增
Step 0b pre-validate plate video readable + has embedded TC ← 新增 (若指定 plate)
Step 1  清空 + 重建 LevelSequence (asset mutation 开始)
Step 2  Set frame rate
Step 2.5 Inject MovieScene SourceTimecode ← 新增
Step 3+ ...
```

Step 0/0a/0b 全过才能进 Step 1。

## 9. Testing & Verification

### 9.1 Unit tests(pure Python,无 UE)

新增 `tests/test_csv_parser_timecode.py`:
- 24fps 非 drop-frame 解析(`09:44:23:22`)
- 29.97 drop-frame 解析(`09:44:23;22`)
- 跨午夜(`23:59:58:23` → `00:00:00:01`)
- SMPTE 等价性失败 fail-fast(伪造 timestamp ↔ frame_number 不一致的 CSV)
- 旧 schema(legacy `camera:cam 1.timestamp`)+ 新 schema(spatialmap)双兼容
- `Timecode.to_frames` 数学(drop-frame 帧数计算正确)

新增 `tests/test_otio_export.py`:
- timeline 结构包含 CG track + plate track
- ImageSequenceReference 起始帧 = absolute CSV frame
- DaVinci-compatible(用 `otio.schema.Timeline.find_clips()` 校验)

新增 `tests/test_mrq_exr_writer.py`(离线模式,不依赖 unreal):
- 渲一帧灰图 EXR(用 OpenEXR Python 自己写一张)→ 跑 `write_timecode_to_exr_sequence` → 读 header 验证 `timeCode` 属性存在且数值正确
- drop-frame 时分隔符正确

### 9.2 UE in-editor 集成测试(lanPC)

按 take_4 / take_5 baseline 跑:

1. **回归**:take_4 完整 import,MRQ 渲 1 帧 → diff vs baseline 残差 < 数值噪声
2. **G1 验证**:Sequencer 打开 LevelSequence,View → Show Timecode 切到 SMPTE 显示,时间轴 frame 0 显示 `09:44:23:22`(或 CSV start timecode)
3. **G2 验证**:MRQ 渲一帧 EXR → `oiiotool --info -v render.0625914.exr` 看 header,`timeCode` 属性 = `09:44:23:22`,`framesPerSecond` = `24/1`
4. **G3 验证**:UI 选一个带 embedded timecode 的 ProRes 文件 → "Attach Reference Plate" → Sequencer 里看到 Media Track,scrub 时 plate 跟 CG 视觉对齐
5. **G4 验证**:渲完点 "Export OTIO" → 用 `otio.adapters.read_from_file` parse 输出 → DaVinci 19+ 导入,timeline 自动 conform
6. **G5 验证**:渲出文件名 `render.0625914.exr`(absolute CSV frame)
7. **G6 验证**:制造 CSV timestamp ↔ frame mismatch / plate 视频无 embedded TC,确认 fail-fast 不动 asset

### 9.3 Cross-system conform 验证

最终接受标准:把渲出的 EXR sequence + 现场 ProRes 一起拖进 DaVinci 19+,**不指定任何 timecode 参数**,timeline 自动按 SMPTE timecode 对齐。逐帧 scrub 任意位置,CG 和 plate 的时间码一致。

## 10. Rollout

不引入 feature flag(按 [[feedback_no_temporary_runtime_switches]])。直接替换。

回退路径:
- CSV 解析层改动有 unit test 覆盖,如 regression 直接 git revert
- MovieScene SourceTimecode 注入是新增 Step 2.5,git revert 这一段即可
- Media Track / EXR writer / OTIO 是全新模块,删除即恢复

不向后兼容旧 LevelSequence 资产:重新 `run_import` 会清空 + 重建(已有逻辑)。

## 11. Open Questions(implementation plan 阶段调研)

1. `UMovieScene::SetEarliestTimecodeSource` Python 暴露面 — grep 引擎源给 `file:line` 证据
2. `unreal.MovieSceneMediaTrack` + `FileMediaSource` Python 暴露面 — 同上
3. MRQ output filename token 是否原生支持 absolute CSV frame mapping,还是需要 post-render rename
4. MRQ `on_pipeline_finished` Python callback 绑定具体写法 — UE 5.7 doc + 引擎源
5. OpenEXR Python wheel 在 UE 内置 Python(3.11)的 macOS/Windows 安装路径

## 12. References

- 现有架构:`docs/superpowers/plans/2026-05-13-custom-moviescene-track.md`
- DataAsset schema:`Source/PostRenderTool/Public/PostRenderCameraSamples.h`
- Evaluator frame mapping:`Source/PostRenderTool/Private/PostRenderCameraSectionTemplate.cpp:107-152`
- 现有 timecode 字段(string-only):`Content/Python/post_render_tool/csv_parser.py:85-86,394-395,576-577`
- 现有 playback range 归零:`Content/Python/post_render_tool/sequence_builder.py:110-114`
- OpenEXR timecode 标准:`https://openexr.com/en/latest/OpenEXRFileLayout.html#standard-attributes`
- OpenTimelineIO ImageSequenceReference:`https://opentimelineio.readthedocs.io/en/stable/api/python/opentimelineio.schema.html#opentimelineio.schema.ImageSequenceReference`
