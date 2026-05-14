"""Companion to probe_ue_timecode_api.py — runs INSIDE lanPC UE 5.7 Editor.

Pipes Python visibility of the timecode-sync API points back as a single
markdown table that can be appended to scripts/ue_timecode_api_probe.md.

Usage (from Mac):
    scp scripts/probe_ue_timecode_api_lanpc.py \\
        lanpc:C:/temp/ue-remote/probe_tc.py
    ssh lanpc '"D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/probe_tc.py'

(Requires UE 5.7 Editor running on lanPC with Python Remote Execution enabled —
see CLAUDE.md "UE Python Remote Execution" section.)
"""
import unreal  # type: ignore


def _has(cls_name: str, attr: str) -> bool:
    cls = getattr(unreal, cls_name, None)
    if cls is None:
        return False
    return attr in dir(cls)


def _cls_exists(cls_name: str) -> bool:
    return getattr(unreal, cls_name, None) is not None


def main() -> None:
    rows = [
        # (API description, check expr, result)
        ("MovieSceneSection class exposed",
         _cls_exists("MovieSceneSection")),
        ("MovieSceneSection.timecode_source attr",
         _has("MovieSceneSection", "timecode_source")),
        ("MovieSceneSection.set_editor_property('timecode_source', ...) — assumed",
         _cls_exists("MovieSceneSection")),
        ("MovieSceneTimecodeSource struct exposed",
         _cls_exists("MovieSceneTimecodeSource")),
        ("Timecode struct exposed",
         _cls_exists("Timecode")),
        ("MoviePipelineOutputSetting class exposed",
         _cls_exists("MoviePipelineOutputSetting")),
        ("MoviePipelineOutputSetting.frame_number_offset",
         _has("MoviePipelineOutputSetting", "frame_number_offset")),
        ("MoviePipelineOutputSetting.zero_pad_frame_numbers",
         _has("MoviePipelineOutputSetting", "zero_pad_frame_numbers")),
        ("MoviePipelineOutputSetting.file_name_format",
         _has("MoviePipelineOutputSetting", "file_name_format")),
        ("MoviePipelineEditorLibrary.create_job_from_sequence (already in use)",
         _has("MoviePipelineEditorLibrary", "create_job_from_sequence")),
        ("MoviePipelineQueueSubsystem (already in use)",
         _cls_exists("MoviePipelineQueueSubsystem")),
        ("PostRenderToolBuildHelper (plugin, sanity check)",
         _cls_exists("PostRenderToolBuildHelper")),
    ]

    unreal.log("\n=== UE 5.7 Python Visibility Verification ===")
    unreal.log("| API | Visible? |")
    unreal.log("|---|---|")
    # ASCII only — Windows GBK locale chokes on ✓ / ✗ when bridge prints back.
    for desc, ok in rows:
        verdict = "yes" if ok else "NO"
        unreal.log(f"| {desc} | {verdict} |")
    unreal.log("=== end ===\n")


if __name__ == "__main__":
    main()
