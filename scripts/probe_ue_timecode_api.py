"""Day-1 UE 5.7 timecode API probe.

Greps the local UE 5.7 engine source for the Python-exposed API points the
timecode-sync plan relies on, and emits a markdown report with `file:line`
evidence plus a heuristic on Python visibility (BlueprintCallable /
BlueprintReadOnly / UFUNCTION nearby).

Run from worktree root:
    python scripts/probe_ue_timecode_api.py | tee scripts/ue_timecode_api_probe.md

Heuristic only — final ground truth must come from `help(unreal.X)` inside
the actual UE 5.7 Editor Python console (lanPC). See trailing "Python
verification" section in the output.
"""
from __future__ import annotations

import re
from pathlib import Path


UE = Path("/Users/bip.lan/AIWorkspace/vp/UnrealEngine")

# Each target: (description, search_root, multiline regex pattern)
SEARCH_TARGETS: list[tuple[str, Path, str]] = [
    (
        "UMovieSceneSection::TimecodeSource UPROPERTY",
        UE / "Engine/Source/Runtime/MovieScene/Public/MovieSceneSection.h",
        r"UPROPERTY[^\n]*\n[^\n]*FMovieSceneTimecodeSource\s+TimecodeSource",
    ),
    (
        "FMovieSceneTimecodeSource USTRUCT 定义",
        UE / "Engine/Source/Runtime/MovieScene/Public/MovieSceneSection.h",
        r"USTRUCT[^\n]*\n[^\n]*struct\s+\w*\s*FMovieSceneTimecodeSource",
    ),
    (
        "UMoviePipelineOutputSetting::FrameNumberOffset UPROPERTY",
        UE / "Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineCore/Public/MoviePipelineOutputSetting.h",
        r"UPROPERTY[^\n]*\n[^\n]*FrameNumberOffset",
    ),
    (
        "MRQ FileNameFormat token expansion 含 frame_number",
        UE / "Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineCore",
        r"\{frame_number\}",
    ),
    (
        "UMoviePipelineEditorLibrary::CreateJobFromSequence UFUNCTION",
        UE / "Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineEditor",
        r"UFUNCTION[^\n]*\n[^\n]*CreateJobFromSequence",
    ),
]


def _search_in_file(path: Path, pattern: str, max_hits: int = 3) -> list[tuple[Path, int, str]]:
    text = path.read_text(errors="ignore")
    hits: list[tuple[Path, int, str]] = []
    for m in re.finditer(pattern, text, re.MULTILINE):
        lineno = text[: m.start()].count("\n") + 1
        excerpt = m.group(0).replace("\n", " ↵ ")[:140]
        hits.append((path, lineno, excerpt))
        if len(hits) >= max_hits:
            break
    return hits


def _search_target(root: Path, pattern: str) -> list[tuple[Path, int, str]]:
    if not root.exists():
        return []
    if root.is_file():
        return _search_in_file(root, pattern)
    out: list[tuple[Path, int, str]] = []
    for ext in ("*.h", "*.cpp"):
        for f in root.rglob(ext):
            out.extend(_search_in_file(f, pattern, max_hits=1))
            if len(out) >= 3:
                return out[:3]
    return out


# Two independent paths can expose a UPROPERTY to Python (PyGenUtil.cpp):
#   - IsScriptExposedProperty (line 1611): CPF_BlueprintVisible / Assignable
#   - ShouldExportEditorOnlyProperty (line 1813): CPF_Edit in Editor mode
# `EditAnywhere` alone (no Blueprint markers) is enough — set_editor_property
# works.
_BLUEPRINT_KEYWORDS = (
    "BlueprintCallable",
    "BlueprintReadOnly",
    "BlueprintReadWrite",
)
_EDIT_KEYWORDS = (
    "EditAnywhere",
    "EditInstanceOnly",
    "EditDefaultsOnly",
)


def _visibility_verdict(path: Path, lineno: int) -> str:
    """Heuristic: look 3 lines before/after for exposure markers.

    Both Blueprint and Edit markers count — Editor-mode Python sees both
    (PyGenUtil.cpp:1611 + :1813).
    """
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except Exception:
        return "?"
    start = max(0, lineno - 4)
    end = min(len(lines), lineno + 3)
    window = "\n".join(lines[start:end])
    if any(kw in window for kw in _BLUEPRINT_KEYWORDS):
        return "✓ likely (Blueprint markers nearby)"
    if any(kw in window for kw in _EDIT_KEYWORDS):
        return "✓ likely (EditAnywhere → CPF_Edit, ShouldExportEditorOnlyProperty)"
    return "? check w/ help(unreal.X)"


def main() -> None:
    print("# UE 5.7 Timecode API Probe Report\n")
    print("Source root: `" + str(UE) + "`\n")
    print("| API | Evidence (file:line) | Python visible? |")
    print("|---|---|---|")
    for desc, root, pattern in SEARCH_TARGETS:
        hits = _search_target(root, pattern)
        if not hits:
            print(f"| {desc} | **NOT FOUND** in `{root}` | — |")
            continue
        path, lineno, excerpt = hits[0]
        rel = str(path).replace(str(UE) + "/", "")
        verdict = _visibility_verdict(path, lineno)
        # Markdown-safe: replace pipes in excerpt
        safe_excerpt = excerpt.replace("|", r"\|")
        print(f"| {desc} | `{rel}:{lineno}` — {safe_excerpt} | {verdict} |")

    print("\n## Python verification (run inside lanPC UE Editor Python console)\n")
    print("```python")
    print("# Section.TimecodeSource:")
    print("help(unreal.MovieSceneSection)               # 找 TimecodeSource / SetTimecodeSource")
    print("# Or via reflection:")
    print("print('TimecodeSource' in dir(unreal.MovieSceneSection))")
    print("")
    print("# MRQ FrameNumberOffset:")
    print("help(unreal.MoviePipelineOutputSetting)      # 找 frame_number_offset")
    print("print('frame_number_offset' in dir(unreal.MoviePipelineOutputSetting))")
    print("")
    print("# Timecode struct exposure:")
    print("help(unreal.MovieSceneTimecodeSource)")
    print("help(unreal.Timecode)")
    print("```")
    print("\n填入实测结果后,本 report 即可指导 Task 4/5/6/7 是否走 C++ wrapper 兜底。")


if __name__ == "__main__":
    main()
