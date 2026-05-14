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

## 下一步

1. lanPC UE Editor 开了之后, 执行:
   ```
   scp scripts/probe_ue_timecode_api_lanpc.py lanpc:C:/temp/ue-remote/probe_tc.py
   ssh lanpc '"D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/probe_tc.py'
   ```
2. 实测结果回填 → 决定 Task 4 走 Python 原生还是写 wrapper
3. 进入 Task 4 实施
