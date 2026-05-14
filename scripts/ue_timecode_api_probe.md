# UE 5.7 Timecode API Probe Report

Source root: `/Users/bip.lan/AIWorkspace/vp/UnrealEngine`

| API | Evidence (file:line) | Python visible? |
|---|---|---|
| UMovieSceneSection::TimecodeSource UPROPERTY | `Engine/Source/Runtime/MovieScene/Public/MovieSceneSection.h:792` — UPROPERTY(EditAnywhere, Category="Section") ↵ 	FMovieSceneTimecodeSource TimecodeSource | ✓ likely (EditAnywhere → CPF_Edit, ShouldExportEditorOnlyProperty) |
| FMovieSceneTimecodeSource USTRUCT 定义 | `Engine/Source/Runtime/MovieScene/Public/MovieSceneSection.h:180` — USTRUCT(BlueprintType) ↵ struct FMovieSceneTimecodeSource | ? check w/ help(unreal.X) |
| UMoviePipelineOutputSetting::FrameNumberOffset UPROPERTY | `Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineCore/Public/MoviePipelineOutputSetting.h:109` — UPROPERTY(EditAnywhere, BlueprintReadWrite, AdvancedDisplay, Category = "File Output") ↵ 	int32 FrameNumberOffset | ✓ likely (Blueprint markers nearby) |
| MRQ FileNameFormat token expansion 含 frame_number | `Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineCore/Public/MovieRenderPipelineDataTypes.h:897` — {frame_number} | ✓ likely (Blueprint markers nearby) |
| UMoviePipelineEditorLibrary::CreateJobFromSequence UFUNCTION | `Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineEditor/Public/MoviePipelineEditorBlueprintLibrary.h:47` — UFUNCTION(BlueprintCallable, Category = "Movie Render Pipeline") ↵ 	static UE_API UMoviePipelineExecutorJob* CreateJobFromSequence | ✓ likely (Blueprint markers nearby) |

## Python verification (run inside lanPC UE Editor Python console)

```python
# Section.TimecodeSource:
help(unreal.MovieSceneSection)               # 找 TimecodeSource / SetTimecodeSource
# Or via reflection:
print('TimecodeSource' in dir(unreal.MovieSceneSection))

# MRQ FrameNumberOffset:
help(unreal.MoviePipelineOutputSetting)      # 找 frame_number_offset
print('frame_number_offset' in dir(unreal.MoviePipelineOutputSetting))

# Timecode struct exposure:
help(unreal.MovieSceneTimecodeSource)
help(unreal.Timecode)
```

填入实测结果后,本 report 即可指导 Task 4/5/6/7 是否走 C++ wrapper 兜底。

## 静态分析结论 (基于上表 + UE source + PyGenUtil.cpp)

### Python 可见性的两条路径 (Codex review 纠正)

UE 5.7 `PyGenUtil.cpp` 暴露 UPROPERTY 给 Python 有两条独立路径:

- **`IsScriptExposedProperty` (line 1611)** — 看 `CPF_BlueprintVisible | CPF_BlueprintAssignable`。`BlueprintReadOnly` / `BlueprintReadWrite` / `BlueprintCallable` 走这条
- **`ShouldExportEditorOnlyProperty` (line 1813)** — 在 Editor 模式下,看 `CPF_Edit` (即 `EditAnywhere` / `EditInstanceOnly` / `EditDefaultsOnly`)。**单独 `EditAnywhere` 也能让 Python `set_editor_property` 看到字段**

### Task 4 `SetSectionTimecodeSource` — wrapper 可选,不是必须

- `MovieSceneSection.h:792` `TimecodeSource` UPROPERTY 标记 `EditAnywhere` → 走 `CPF_Edit` 分支 → Python **原生可见**
- `FMovieSceneTimecodeSource` USTRUCT `BlueprintType` (line 180) → Python 可构造
- Python 路径理论上工作:
  ```python
  src = unreal.MovieSceneTimecodeSource()
  src.timecode = unreal.Timecode(hours, minutes, seconds, frames, drop)
  section.set_editor_property("timecode_source", src)
  ```
- **决策**:Task 4 改成 "lanPC 实测 Python 原生路径 → 通就跳过 wrapper / 不通才做 C++ wrapper"。wrapper 仅作鲁棒性保底,不是默认实现。

### Task 7 `FrameNumberOffset` — 走 Python 原生 (确认)

- `MoviePipelineOutputSetting.h:109` `UPROPERTY(EditAnywhere, BlueprintReadWrite, ...)` 两条路径都通
- `output_setting.set_editor_property("frame_number_offset", N)` 直接用

### 待 lanPC verification 的兜底点

- `unreal.MovieSceneTimecodeSource` USTRUCT 是否能 `()` 实例化 + 字段是否可写
- `unreal.Timecode` USTRUCT (FTimecode 暴露) 是否可用
- `set_editor_property("timecode_source", ...)` 实际写入是否生效 (落盘后 reload 资产看 TimecodeSource 是否持久化)

跑 `scripts/probe_ue_timecode_api_lanpc.py` 在 lanPC UE Editor 实测确认。

## lanPC 实测结果 (2026-05-14)

### dir() visibility check (`probe_ue_timecode_api_lanpc.py`)

| API | dir() visible? |
|---|---|
| MovieSceneSection class | yes |
| MovieSceneSection.timecode_source attr | NO (但 set_editor_property 可绕过 — 见下) |
| MovieSceneTimecodeSource struct | yes |
| Timecode struct | yes |
| MoviePipelineOutputSetting class | yes |
| MoviePipelineOutputSetting.frame_number_offset | yes |
| MoviePipelineOutputSetting.zero_pad_frame_numbers | yes |
| MoviePipelineOutputSetting.file_name_format | yes |
| MoviePipelineEditorLibrary.create_job_from_sequence | yes |
| MoviePipelineQueueSubsystem | yes |
| PostRenderToolBuildHelper (plugin) | yes |

### Roundtrip 实测 (`probe_ue_timecode_roundtrip.py`)

`unreal.Timecode` dir(): `hours, minutes, seconds, frames, drop_frame_format, subframe, ...`
`unreal.MovieSceneTimecodeSource` dir(): `timecode, ...`

完整 round-trip 通过:
```
tc = unreal.Timecode()
tc.set_editor_property("hours", 10)
tc.set_editor_property("minutes", 30)
tc.set_editor_property("seconds", 45)
tc.set_editor_property("frames", 22)
tc.set_editor_property("drop_frame_format", False)

src = unreal.MovieSceneTimecodeSource()
src.set_editor_property("timecode", tc)

section.set_editor_property("timecode_source", src)
got = section.get_editor_property("timecode_source").get_editor_property("timecode")
# → H=10 M=30 S=45 F=22 (exactly matches set)
```

### 最终结论

**Task 4 C++ UFUNCTION wrapper:跳过(SKIPPED)**

- `Section.set_editor_property("timecode_source", ...)` 走 UE 反射,工作正常
- 通过 Codex review (PyGenUtil.cpp:1813 `ShouldExportEditorOnlyProperty` 路径) +
  实测 round-trip 双重证明
- Python native 4 行注入足够,无需 C++ wrapper / UBT 重编

**Task 7 `FrameNumberOffset`:Python native(确认)**
- `MoviePipelineOutputSetting.frame_number_offset` Python 可见,
  `output_setting.set_editor_property("frame_number_offset", N)` 即可

**Task 5 `UPostRenderCameraSamples.StartTimecode`:仍然需要做**
- 跟 wrapper 是两件事:Task 5 加 DataAsset schema(canonical 数据存储),
  让 P1 EXR patcher / OTIO exporter 不需要从 Section.TimecodeSource 反向读
- 仍需 UBT 重编(UPROPERTY 改 schema)

## 下一步

1. ~~Task 4 C++ wrapper~~ SKIPPED
2. Task 5: UPostRenderCameraSamples 加 StartTimecode UPROPERTY
3. Task 6: sequence_builder Step 4a/6a 直接 Python set_editor_property
