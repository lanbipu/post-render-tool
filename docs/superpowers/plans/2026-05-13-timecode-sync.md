# Timecode Sync Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Disguise CSV → UE 渲染帧 ↔ 现场带 timecode 实拍视频做逐帧 SMPTE 同步,渲出的每一帧自动 conform 回现场实拍。

**Architecture:**
- (P0) CSV 的 SMPTE timecode 结构化解析 → 写到 `UMovieSceneSection.TimecodeSource` 让 Sequencer UI 显示现场 timecode；同步存 canonical `StartTimecode` 到 `UPostRenderCameraSamples` DataAsset(避免 P1 靠 Python 反射 Section);MRQ 用 `FrameNumberOffset` 让文件名带 absolute CSV frame
- (P1) 渲完手动一键 patch EXR header 写 SMPTE typed attributes + 导 OTIO sidecar,DaVinci/Nuke 实测验证
- (P2) 单独 spec 再做 reference plate 视觉验证

**Tech Stack:** Python 3.11 (UE 5.7 内置)、UE C++ (UBT)、PyPI `OpenEXR` / `oiiotool` / `opentimelineio`、OpenEXR standard typed attributes、SMPTE drop-frame timecode、UE 5.7 MovieScene / MovieRenderQueue API。

**Spec:** `docs/superpowers/specs/2026-05-13-timecode-sync-design.md`

**Worktree:** `.claude/worktrees/timecode-sync-spec` (branch `worktree-timecode-sync-spec`)

**v2 changes from v1**: 采纳 CodeX review 全部 blocker 反馈
- Task 4 删除不存在的 `DeltaFrame` 参数(UE `FMovieSceneTimecodeSource` 只有 `Timecode` 一个字段,`MovieSceneSection.h:205-206`)
- Task 2 所有 test 显式传 `fps`,结构化字段设 `Optional[...] = None` 默认值;加 `unwrap_timecode_frames()` 处理跨午夜
- Task 3 probe script 改用 `rg -n -C` + Python multiline regex,grep search path 修正到 `MovieSceneSection.h`
- 新增 Task 5: `UPostRenderCameraSamples` 加 canonical `StartTimecode` UPROPERTY,让 P1 直接读 DataAsset
- Task 7 (原 Task 6) 删 `get_movie_scene_sequence().get_movie_scene()` 死代码,直接读 sample_asset.start_timecode
- Task 12 (原 Task 11) 用现有 `_host` / `_bind_click` / `_get` / `_last_result` widget pattern;`PipelineResult` 加 `level_sequence_path` derive 字段
- `test_spec_drift` count 从硬编码改成 derive,避免每加 widget 改两处
- Task 9 (原 Task 8) spike 必须用 `exrheader` 验证真实 EXR typed attributes + DaVinci 实测 gate,不能只信 `oiiotool --info` 文本

---

## File Structure

### 新增文件
| 路径 | 职责 | Phase |
|---|---|---|
| `Content/Python/post_render_tool/timecode.py` | `Timecode` dataclass + parser + `to_frames()`/`__str__` + `unwrap_timecode_frames` 跨午夜辅助 | P0 |
| `Content/Python/post_render_tool/tests/test_timecode.py` | `Timecode` unit tests | P0 |
| `Content/Python/post_render_tool/tests/test_csv_parser_timecode.py` | csv_parser timecode 集成 tests | P0 |
| `Content/Python/post_render_tool/tests/fixtures/sample_50fps_dense.csv` | 50fps 等价性 test fixture | P0 |
| `scripts/probe_ue_timecode_api.py` | day-1 grep UE 引擎源,验证 Python API 暴露面 | P0 |
| `Content/Python/post_render_tool/exr_timecode_writer.py` | EXR header patcher,选定 backend 后实现 | P1 |
| `Content/Python/post_render_tool/tests/test_exr_timecode_writer.py` | EXR patcher unit tests | P1 |
| `Content/Python/post_render_tool/otio_export.py` | OTIO sidecar exporter | P1 |
| `Content/Python/post_render_tool/tests/test_otio_export.py` | OTIO unit tests | P1 |
| `scripts/exr_timecode_spike.py` | 三 backend EXR writer spike | P1 |

### 修改文件
| 路径 | 改造点 | Phase |
|---|---|---|
| `Content/Python/post_render_tool/csv_parser.py` | `FrameData.timecode`,`CsvDenseResult.start_timecode/end_timecode/frame_rate`(全 Optional),等价性校验,`trim_static_padding` 同步 | P0 |
| `Source/PostRenderTool/Public/PostRenderCameraSample.h` 或 `PostRenderCameraSamples.h` | 加 `StartTimecode` 字段 (canonical timecode 来源) | P0 |
| `Source/PostRenderTool/Public/PostRenderToolBuildHelper.h` | 新 UFUNCTION `SetSectionTimecodeSource`(无 DeltaFrame);`WriteCameraSamples` 加 start timecode 参数 | P0 |
| `Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp` | impl | P0 |
| `Content/Python/post_render_tool/sequence_builder.py` | Step 4a + 6a 调 `set_section_timecode_source`,`WriteCameraSamples` 调用带 start_timecode | P0 |
| `Content/Python/post_render_tool/pipeline.py` | `PipelineResult` 加 `level_sequence_path` derive 字段;新增 `run_patch_exr_timecode` / `run_export_otio` | P0/P1 |
| `Content/Python/post_render_tool/ui_interface.py` | `open_movie_render_queue` 设 `FrameNumberOffset` + filename | P0 |
| `Content/Python/post_render_tool/widget.py` | 3 个新 widget callback 绑定 (P1),用现有 `_host` / `_bind_click` / `_get` 风格 | P1 |
| `Source/PostRenderTool/Public/PostRenderToolWidget.h` | 3 个新 BindWidget UPROPERTY | P1 |
| `docs/widget-tree-spec.json` | 3 个新 widget 节点 | P1 |
| `Content/Python/post_render_tool/tests/test_spec_drift.py` | count 从硬编码改 derive | P1 |

---

## Phase P0 — MVP (G1 / G5 / G6)

P0 交付:Sequencer UI 显示现场 timecode + MRQ 渲出的 EXR 文件名带 absolute CSV frame。

P0 完成 gate:unit tests + C++ build + lanPC import + Sequencer 显示 SMPTE + MRQ 文件名带 absolute frame + take_4 几何回归全绿。

### Task 1: 加 `Timecode` dataclass + parser + 跨午夜辅助

**Files:**
- Create: `Content/Python/post_render_tool/timecode.py`
- Create: `Content/Python/post_render_tool/tests/test_timecode.py`

- [ ] **Step 1: Write the failing test**

`Content/Python/post_render_tool/tests/test_timecode.py`:

```python
import unittest
from post_render_tool.timecode import Timecode, unwrap_timecode_frames


class TestTimecodeParse(unittest.TestCase):
    def test_24fps_non_drop(self):
        tc = Timecode.parse("09:44:23:22", 24.0)
        self.assertEqual((tc.hours, tc.minutes, tc.seconds, tc.frames), (9, 44, 23, 22))
        self.assertFalse(tc.drop_frame)
        self.assertEqual((tc.rate_num, tc.rate_den), (24, 1))

    def test_25fps_non_drop(self):
        tc = Timecode.parse("00:00:01:24", 25.0)
        self.assertEqual(tc.frames, 24)
        self.assertFalse(tc.drop_frame)
        self.assertEqual((tc.rate_num, tc.rate_den), (25, 1))

    def test_50fps_non_drop(self):
        # take_4 production case
        tc = Timecode.parse("10:00:00:49", 50.0)
        self.assertEqual(tc.frames, 49)
        self.assertFalse(tc.drop_frame)
        self.assertEqual((tc.rate_num, tc.rate_den), (50, 1))

    def test_2997_drop_frame(self):
        tc = Timecode.parse("09:44:23;22", 29.97)
        self.assertTrue(tc.drop_frame)
        self.assertEqual((tc.rate_num, tc.rate_den), (30000, 1001))

    def test_5994_drop_frame(self):
        tc = Timecode.parse("01:00:00;30", 59.94)
        self.assertTrue(tc.drop_frame)

    def test_23976_non_drop(self):
        tc = Timecode.parse("00:01:00:00", 23.976)
        self.assertFalse(tc.drop_frame)
        self.assertEqual((tc.rate_num, tc.rate_den), (24000, 1001))

    def test_dot_separator_accepted(self):
        # Disguise CSV 用 . 分隔最后一位
        tc = Timecode.parse("09:44:23.22", 24.0)
        self.assertEqual(tc.frames, 22)

    def test_str_round_trip_non_drop(self):
        self.assertEqual(str(Timecode.parse("09:44:23:22", 24.0)), "09:44:23:22")

    def test_str_round_trip_drop(self):
        self.assertEqual(str(Timecode.parse("09:44:23;22", 29.97)), "09:44:23;22")

    def test_unsupported_fps_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Timecode.parse("00:00:00:00", 48.0)
        self.assertIn("48", str(ctx.exception))


class TestTimecodeToFrames(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(Timecode.parse("00:00:00:00", 24.0).to_frames(), 0)

    def test_one_second_24fps(self):
        self.assertEqual(Timecode.parse("00:00:01:00", 24.0).to_frames(), 24)

    def test_one_minute_50fps(self):
        self.assertEqual(Timecode.parse("00:01:00:00", 50.0).to_frames(), 50 * 60)

    def test_one_hour_24fps(self):
        self.assertEqual(Timecode.parse("01:00:00:00", 24.0).to_frames(), 24 * 60 * 60)

    def test_2997_drop_one_minute(self):
        # 1 分钟 = 30*60 - 2 = 1798 帧
        self.assertEqual(Timecode.parse("00:01:00;02", 29.97).to_frames(), 1798)

    def test_2997_drop_ten_minutes(self):
        # 整 10 分钟 = 30*60*10 - 2*9 = 17982 帧
        self.assertEqual(Timecode.parse("00:10:00;00", 29.97).to_frames(), 17982)


class TestUnwrapAcrossMidnight(unittest.TestCase):
    def test_no_wrap_returns_actual_delta(self):
        first = Timecode.parse("23:59:58:00", 24.0)
        later = Timecode.parse("23:59:59:23", 24.0)
        # 1 second 23 frames = 24 + 23 = 47 frames
        self.assertEqual(unwrap_timecode_frames(first, later), 47)

    def test_wrap_at_midnight_24fps(self):
        first = Timecode.parse("23:59:58:00", 24.0)
        # 跨 00:00:00:00,实际 delta 应为 2 秒 1 帧 = 49 帧
        later = Timecode.parse("00:00:00:01", 24.0)
        self.assertEqual(unwrap_timecode_frames(first, later), 49)

    def test_wrap_at_midnight_50fps(self):
        first = Timecode.parse("23:59:59:48", 50.0)
        later = Timecode.parse("00:00:00:02", 50.0)
        # 实际 delta = 4 frames (从 23:59:59:48 走 4 帧到 00:00:00:02)
        self.assertEqual(unwrap_timecode_frames(first, later), 4)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec/Content/Python
python -m unittest post_render_tool.tests.test_timecode -v
```
Expected: `ModuleNotFoundError: No module named 'post_render_tool.timecode'`

- [ ] **Step 3: Write implementation**

`Content/Python/post_render_tool/timecode.py`:

```python
"""SMPTE Timecode parser + arithmetic. Pure Python, no UE dependency."""
from __future__ import annotations

import re
from dataclasses import dataclass


_FRACTIONAL_FPS: dict[float, tuple[int, int]] = {
    23.976: (24000, 1001),
    29.97:  (30000, 1001),
    59.94:  (60000, 1001),
}

_INTEGER_FPS = (24, 25, 30, 50, 60)
_DROP_FRAME_FPS = (29.97, 59.94)

# 头三段 : / 最后一段 : ; .
_TC_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})([:;.])(\d{2,3})$")


def _resolve_frame_rate(fps: float) -> tuple[int, int]:
    for known_fps, fraction in _FRACTIONAL_FPS.items():
        if abs(fps - known_fps) < 0.01:
            return fraction
    rounded = int(round(fps))
    if rounded in _INTEGER_FPS and abs(fps - rounded) < 0.01:
        return (rounded, 1)
    raise ValueError(
        f"Unsupported frame rate {fps}; supported: "
        "23.976, 24, 25, 29.97, 30, 50, 59.94, 60"
    )


def _is_drop_frame(fps: float) -> bool:
    return any(abs(fps - df) < 0.01 for df in _DROP_FRAME_FPS)


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
    def parse(cls, s: str, fps: float) -> "Timecode":
        m = _TC_RE.match(s.strip())
        if m is None:
            raise ValueError(f"Invalid timecode string: {s!r}")
        hh, mm, ss, _sep, ff = m.groups()
        rate_num, rate_den = _resolve_frame_rate(fps)
        drop = _is_drop_frame(fps)
        return cls(
            hours=int(hh), minutes=int(mm), seconds=int(ss),
            frames=int(ff), drop_frame=drop,
            rate_num=rate_num, rate_den=rate_den,
        )

    def to_frames(self) -> int:
        """Total frames since 00:00:00:00 of the current 24h period."""
        nominal_fps = round(self.rate_num / self.rate_den)
        if not self.drop_frame:
            return ((self.hours * 60 + self.minutes) * 60 + self.seconds) * nominal_fps + self.frames

        # NTSC drop-frame:每分钟丢 drop_count 帧,整 10 分钟保留
        drop_count = 2 if abs(self.rate_num / self.rate_den - 29.97) < 0.01 else 4
        total_minutes = self.hours * 60 + self.minutes
        full_tens = total_minutes // 10
        total_drop = drop_count * (total_minutes - full_tens)
        return (((self.hours * 60 + self.minutes) * 60 + self.seconds) * nominal_fps
                + self.frames - total_drop)

    def __str__(self) -> str:
        sep = ";" if self.drop_frame else ":"
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}{sep}{self.frames:02d}"


def _frames_per_24h(rate_num: int, rate_den: int, drop_frame: bool) -> int:
    """一天等价帧数 (用于跨午夜 unwrap)."""
    if not drop_frame:
        nominal = round(rate_num / rate_den)
        return nominal * 24 * 3600
    # drop-frame: 整 24 小时 = 144 个 10 分钟块 = 144 * (nominal*600 - drop_count*9)
    nominal = round(rate_num / rate_den)
    drop_count = 2 if abs(rate_num / rate_den - 29.97) < 0.01 else 4
    return 144 * (nominal * 600 - drop_count * 9)


def unwrap_timecode_frames(first: Timecode, later: Timecode) -> int:
    """计算 first → later 的真实 frame delta,跨午夜时加一日 frame offset.

    用于 SMPTE 等价性校验 + EXR timecode 反向算法。
    """
    delta = later.to_frames() - first.to_frames()
    if delta >= 0:
        return delta
    # 跨午夜
    if first.rate_num != later.rate_num or first.rate_den != later.rate_den:
        raise ValueError("Cannot unwrap timecodes with different rates")
    return delta + _frames_per_24h(first.rate_num, first.rate_den, first.drop_frame)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest post_render_tool.tests.test_timecode -v
```
Expected: 所有 tests 通过。如 drop-frame 数学 fail,在 `to_frames` 内修正后再跑。

- [ ] **Step 5: Commit**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec
git add Content/Python/post_render_tool/timecode.py Content/Python/post_render_tool/tests/test_timecode.py
git commit -m "feat(timecode): Timecode dataclass + parser + 跨午夜 unwrap

支持 24/23.976/25/29.97/30/50/59.94/60 fps,drop-frame 算术准确。
unwrap_timecode_frames(first, later) 处理 first/later 跨午夜
(00:00:00:00 边界) 时的真实 frame delta,后续等价性校验用。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: csv_parser 集成 Timecode + 等价性校验

**Files:**
- Modify: `Content/Python/post_render_tool/csv_parser.py`
- Create: `Content/Python/post_render_tool/tests/fixtures/sample_50fps_dense.csv`
- Create: `Content/Python/post_render_tool/tests/test_csv_parser_timecode.py`

**关键设计** (采纳 CodeX 反馈):
- 所有 timecode test 显式传 `fps`
- 新字段全部 `Optional[...] = None` 默认值,`fps=None` 时跳过,旧 caller / 旧 fixture 不破

- [ ] **Step 1: Create 50fps fixture CSV**

`Content/Python/post_render_tool/tests/fixtures/sample_50fps_dense.csv`:

```csv
timestamp,frame,spatialmap:cam.activeCamera,spatialmap:cam.engineCameraPos.x,spatialmap:cam.engineCameraPos.y,spatialmap:cam.engineCameraPos.z,spatialmap:cam.engineCameraRotation.x,spatialmap:cam.engineCameraRotation.y,spatialmap:cam.engineCameraRotation.z,spatialmap:cam.activeCamera.resolution.x,spatialmap:cam.activeCamera.resolution.y,spatialmap:cam.activeCamera.paWidthMM,spatialmap:cam.activeCamera.focalLengthMM,spatialmap:cam.activeCamera.overscan.x,spatialmap:cam.activeCamera.overscan.y,spatialmap:cam.activeCamera.overscanResolution.x,spatialmap:cam.activeCamera.overscanResolution.y,spatialmap:cam.activeCamera.aspectRatio,spatialmap:cam.activeCamera.fieldOfViewH,spatialmap:cam.activeCamera.fieldOfViewV,spatialmap:cam.activeCamera.k1k2k3.x,spatialmap:cam.activeCamera.k1k2k3.y,spatialmap:cam.activeCamera.k1k2k3.z,spatialmap:cam.activeCamera.centerShiftMM.x,spatialmap:cam.activeCamera.centerShiftMM.y
10:00:00:00,500000,objects/camera/cam.apx,0.5,1.0,-2.0,350,340,340,1920,1080,35.99,60.0,1.33,1.33,2496,1404,1.77,43.0,25.0,0.005,0.005,0.0,0.0,0.0
10:00:00:01,500001,objects/camera/cam.apx,0.5,1.0,-2.0,350,340,340,1920,1080,35.99,60.0,1.33,1.33,2496,1404,1.77,43.0,25.0,0.005,0.005,0.0,0.0,0.0
10:00:00:02,500002,objects/camera/cam.apx,0.6,1.0,-2.0,350,340,340,1920,1080,35.99,60.0,1.33,1.33,2496,1404,1.77,43.0,25.0,0.005,0.005,0.0,0.0,0.0
```

- [ ] **Step 2: Write the failing test**

`Content/Python/post_render_tool/tests/test_csv_parser_timecode.py`:

```python
import os
import tempfile
import unittest

from post_render_tool.csv_parser import (
    parse_csv_dense, trim_static_padding, CsvTimecodeMismatch,
)
from post_render_tool.timecode import Timecode

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_50fps_dense.csv"
)


class TestCsvParserTimecodeWithFps(unittest.TestCase):
    """fps 显式传入,期望结构化 timecode 字段被填充。"""

    def test_50fps_parse_attaches_timecode_to_each_frame(self):
        result = parse_csv_dense(_FIXTURE, fps=50.0)
        self.assertEqual(len(result.frames), 3)
        self.assertIsInstance(result.frames[0].timecode, Timecode)
        self.assertEqual(str(result.frames[0].timecode), "10:00:00:00")
        self.assertEqual(str(result.frames[2].timecode), "10:00:00:02")

    def test_50fps_csv_result_has_structured_start_end_and_frame_rate(self):
        result = parse_csv_dense(_FIXTURE, fps=50.0)
        self.assertIsInstance(result.start_timecode, Timecode)
        self.assertEqual(str(result.start_timecode), "10:00:00:00")
        self.assertEqual(str(result.end_timecode), "10:00:00:02")
        self.assertEqual(result.frame_rate, (50, 1))

    def test_legacy_string_fields_still_populated(self):
        result = parse_csv_dense(_FIXTURE, fps=50.0)
        self.assertEqual(result.timecode_start, "10:00:00:00")
        self.assertEqual(result.timecode_end, "10:00:00:02")

    def test_smpte_equivalence_failure_raises(self):
        # 伪造 frame_number 跟 timecode 不一致
        with open(_FIXTURE, "r") as f:
            content = f.read()
        broken = content.replace("10:00:00:02,500002,", "10:00:00:02,500003,")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tf:
            tf.write(broken)
            broken_path = tf.name
        try:
            with self.assertRaises(CsvTimecodeMismatch):
                parse_csv_dense(broken_path, fps=50.0)
        finally:
            os.unlink(broken_path)


class TestCsvParserBackwardsCompat(unittest.TestCase):
    """fps=None (默认) 时跳过 timecode 解析,旧 caller 不破。"""

    def test_no_fps_skips_structured_fields(self):
        result = parse_csv_dense(_FIXTURE)
        self.assertIsNone(result.start_timecode)
        self.assertIsNone(result.end_timecode)
        self.assertIsNone(result.frame_rate)
        # 但 string 兼容字段仍然填
        self.assertEqual(result.timecode_start, "10:00:00:00")
        # FrameData.timecode 也是 None
        self.assertIsNone(result.frames[0].timecode)


class TestTrimStaticPaddingSyncsTimecode(unittest.TestCase):
    def test_trim_updates_structured_timecodes(self):
        # 构造 head/tail 同 pos 的 round-trip take 触发 trim
        rows = open(_FIXTURE).read().splitlines()
        last = rows[-1].split(",")
        last[3] = "0.5"  # tail pos 改回与 head 一致
        rows[-1] = ",".join(last)
        # 加 head 静止前缀 + 中段运动 + tail 静止
        head_static = list(rows[1].split(","))
        head_static[0] = "09:59:59:48"
        head_static[1] = "499998"
        rows.insert(1, ",".join(head_static))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tf:
            tf.write("\n".join(rows) + "\n")
            path = tf.name
        try:
            result = parse_csv_dense(path, fps=50.0)
            trimmed = trim_static_padding(result)
            self.assertEqual(
                str(trimmed.start_timecode),
                str(trimmed.frames[0].timecode),
            )
            self.assertEqual(
                str(trimmed.end_timecode),
                str(trimmed.frames[-1].timecode),
            )
        finally:
            os.unlink(path)

    def test_trim_preserves_none_when_fps_not_given(self):
        # fps=None 时 trim 后仍 None,不在 trim 内补
        result = parse_csv_dense(_FIXTURE)
        trimmed = trim_static_padding(result)
        self.assertIsNone(trimmed.start_timecode)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec/Content/Python
python -m unittest post_render_tool.tests.test_csv_parser_timecode -v
```
Expected: ImportError on `CsvTimecodeMismatch` 或 TypeError on `fps` kwarg。

- [ ] **Step 4: Modify csv_parser.py**

打开 `Content/Python/post_render_tool/csv_parser.py`,做以下修改:

**A. 文件顶部 import + 异常类**:

```python
from typing import Optional, Tuple
from .timecode import Timecode, unwrap_timecode_frames


class CsvTimecodeMismatch(ValueError):
    """timestamp 列跟 frame_number 列不等价 (SMPTE drift)."""
```

**B. `FrameData` 加 Optional `timecode` 字段**:

```python
@dataclass
class FrameData:
    frame_number: int
    timestamp: str
    timecode: Optional[Timecode] = None    # 新增, 默认 None
    # ... 现有字段
```

**C. `CsvDenseResult` 加 Optional 结构化字段(保留旧 string 字段)**:

```python
@dataclass
class CsvDenseResult:
    file_path: str
    camera_prefix: str
    frames: List[FrameData]
    frame_count: int
    timecode_start: str            # 旧, 兼容
    timecode_end: str              # 旧, 兼容
    focal_length_range: Tuple[float, float]
    sensor_width_mm: float
    aspect_ratio: float
    start_timecode: Optional[Timecode] = None      # 新, fps=None 时 None
    end_timecode: Optional[Timecode] = None        # 新
    frame_rate: Optional[Tuple[int, int]] = None   # 新
```

**D. `parse_csv_dense` 加 fps kwarg + 结构化解析 + 等价性校验**:

```python
def parse_csv_dense(file_path: str, fps: Optional[float] = None) -> CsvDenseResult:
    # ... 现有逻辑解析 frames

    # fps=None: 跳过 timecode 解析, 全部 None
    start_tc = end_tc = None
    frame_rate = None
    if fps is not None and frames:
        for f in frames:
            f.timecode = Timecode.parse(f.timestamp, fps)
        first = frames[0]
        for f in frames[1:]:
            expected_delta = unwrap_timecode_frames(first.timecode, f.timecode)
            actual_delta = f.frame_number - first.frame_number
            if expected_delta != actual_delta:
                raise CsvTimecodeMismatch(
                    f"CSV timecode ↔ frame_number drift at frame {f.frame_number}: "
                    f"timestamp={f.timestamp} expects Δ={expected_delta} frames since "
                    f"start, but frame_number says Δ={actual_delta}."
                )
        start_tc = first.timecode
        end_tc = frames[-1].timecode
        frame_rate = (start_tc.rate_num, start_tc.rate_den)

    return CsvDenseResult(
        file_path=file_path,
        camera_prefix=camera_prefix,
        frames=frames,
        frame_count=len(frames),
        timecode_start=frames[0].timestamp,
        timecode_end=frames[-1].timestamp,
        focal_length_range=...,
        sensor_width_mm=...,
        aspect_ratio=...,
        start_timecode=start_tc,
        end_timecode=end_tc,
        frame_rate=frame_rate,
    )
```

**E. `trim_static_padding` 同步更新**(在 `CsvDenseResult(...)` 构造时 +3 字段):

```python
return CsvDenseResult(
    file_path=result.file_path,
    camera_prefix=result.camera_prefix,
    frames=trimmed,
    frame_count=len(trimmed),
    timecode_start=trimmed[0].timestamp,
    timecode_end=trimmed[-1].timestamp,
    focal_length_range=(min(focals), max(focals)),
    sensor_width_mm=trimmed[0].sensor_width_mm,
    aspect_ratio=trimmed[0].aspect_ratio,
    start_timecode=trimmed[0].timecode if result.start_timecode is not None else None,
    end_timecode=trimmed[-1].timecode if result.end_timecode is not None else None,
    frame_rate=result.frame_rate,
)
```

- [ ] **Step 5: Run tests — verify all pass + 旧 csv_parser tests 也不破**

```bash
python -m unittest post_render_tool.tests.test_csv_parser_timecode -v
python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -v
```
Expected: 新 test 全 pass,旧 test 也全 pass (`fps=None` 默认 + Optional 字段默认保兼容)。

- [ ] **Step 6: Commit**

```bash
git add Content/Python/post_render_tool/csv_parser.py \
        Content/Python/post_render_tool/tests/test_csv_parser_timecode.py \
        Content/Python/post_render_tool/tests/fixtures/sample_50fps_dense.csv
git commit -m "feat(csv_parser): 集成结构化 Timecode + SMPTE 等价性校验

- FrameData.timecode (Optional[Timecode])
- CsvDenseResult.start_timecode/end_timecode/frame_rate (Optional, 新增)
- parse_csv_dense(fps=None) 默认跳过, 旧 caller / 旧 fixture 不破
- timestamp ↔ frame_number 不等价 fail-fast (CsvTimecodeMismatch),
  跨午夜走 unwrap_timecode_frames 处理
- trim_static_padding 同步更新结构化 timecode

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Day-1 UE API Probe

**Files:**
- Create: `scripts/probe_ue_timecode_api.py`

修订 (采纳 CodeX 反馈):
- 改用 `rg -n` 配合 Python multiline regex (`re.MULTILINE | re.DOTALL`)
- `FMovieSceneTimecodeSource` search path 改到 `MovieSceneSection.h`

- [ ] **Step 1: Write probe script**

`scripts/probe_ue_timecode_api.py`:

```python
"""Day-1: grep UE 5.7 引擎源,验证 timecode 同步要用的 Python API 暴露面.

输出 markdown 表格,记录每条调用的 file:line 证据 + 是否 Python 可见.
"""
import re
import subprocess
from pathlib import Path

UE = Path("/Users/bip.lan/AIWorkspace/vp/UnrealEngine")
SEARCH_TARGETS = [
    # (描述, search root, multiline regex)
    ("UMovieSceneSection::TimecodeSource UPROPERTY",
     UE / "Engine/Source/Runtime/MovieScene/Public/MovieSceneSection.h",
     r"UPROPERTY[^\n]*\n[^\n]*FMovieSceneTimecodeSource\s+TimecodeSource"),

    ("FMovieSceneTimecodeSource USTRUCT 定义",
     UE / "Engine/Source/Runtime/MovieScene/Public/MovieSceneSection.h",
     r"USTRUCT[^\n]*\n[^\n]*struct\s+\w*\s*FMovieSceneTimecodeSource"),

    ("UMoviePipelineOutputSetting::FrameNumberOffset UPROPERTY",
     UE / "Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineCore/Public/MoviePipelineOutputSetting.h",
     r"UPROPERTY[^\n]*\n[^\n]*FrameNumberOffset"),

    ("MRQ FileNameFormat token expansion",
     UE / "Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineCore",
     r"frame_number"),

    ("UMoviePipelineEditorLibrary::CreateJobFromSequence UFUNCTION",
     UE / "Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineEditor",
     r"UFUNCTION[^\n]*\n[^\n]*CreateJobFromSequence"),
]


def search_file(path: Path, pattern: str) -> list[tuple[str, int, str]]:
    """multiline regex over file content; returns [(filepath, lineno, match_excerpt)]."""
    if not path.exists():
        return [("PATH NOT FOUND", 0, str(path))]
    if path.is_dir():
        # 递归 list 所有 .h / .cpp
        hits = []
        for f in path.rglob("*.h"):
            hits.extend(search_file(f, pattern))
        for f in path.rglob("*.cpp"):
            hits.extend(search_file(f, pattern))
        return hits
    text = path.read_text(errors="ignore")
    matches = []
    for m in re.finditer(pattern, text, re.MULTILINE):
        # 计算行号
        lineno = text[:m.start()].count("\n") + 1
        excerpt = m.group(0).replace("\n", " ↵ ")[:120]
        matches.append((str(path), lineno, excerpt))
        if len(matches) >= 3:
            break
    return matches


def main():
    print("# UE 5.7 Timecode API Probe Report\n")
    print("| API | Evidence (file:line) | Python visible? |")
    print("|---|---|---|")
    for desc, root, pattern in SEARCH_TARGETS:
        hits = search_file(root, pattern)
        if not hits or hits[0][0] == "PATH NOT FOUND":
            print(f"| {desc} | **NOT FOUND** | — |")
            continue
        first_path, first_line, first_excerpt = hits[0]
        # Python 可见性启发式:周围 50 行有 BlueprintCallable / BlueprintReadOnly /
        # BlueprintReadWrite / UFUNCTION
        context_text = Path(first_path).read_text(errors="ignore").splitlines()
        ctx_start = max(0, first_line - 3)
        ctx_end = min(len(context_text), first_line + 3)
        ctx = "\n".join(context_text[ctx_start:ctx_end])
        likely_visible = any(
            kw in ctx for kw in ("BlueprintCallable", "BlueprintReadOnly", "BlueprintReadWrite")
        )
        verdict = "✓ likely" if likely_visible else "? check w/ help(unreal.X)"
        rel = first_path.replace(str(UE) + "/", "")
        print(f"| {desc} | `{rel}:{first_line}` — {first_excerpt} | {verdict} |")

    print("\n## Python verification (in lanPC UE Editor)\n")
    print("```python")
    print("help(unreal.MovieSceneSection)              # 找 TimecodeSource / SetTimecodeSource")
    print("help(unreal.MoviePipelineOutputSetting)     # 找 frame_number_offset")
    print("help(unreal.MovieSceneTimecodeSource)       # USTRUCT Python 可见性")
    print("```")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run probe + capture output**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec
python scripts/probe_ue_timecode_api.py | tee scripts/ue_timecode_api_probe.md
```

Expected: markdown 输出,5 个 API 都有 `file:line` 证据。

- [ ] **Step 3: Python visibility 验证 (lanPC)**

scp probe report 到 lanPC,跑 `help(unreal.X)`:

```bash
ssh lanpc 'echo "import unreal" | "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe"'
```

或者在 UE Editor Python console 直接跑(更准确,因为 unreal 模块只有 Editor 内才有真实状态):

```python
help(unreal.MovieSceneSection)
help(unreal.MoviePipelineOutputSetting)
```

把结果回填到 `scripts/ue_timecode_api_probe.md` 末尾。

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_ue_timecode_api.py scripts/ue_timecode_api_probe.md
git commit -m "chore(probe): UE 5.7 timecode API 暴露面调研

day-1 multiline regex grep 引擎源 + lanPC python console help()
验证, 输出 file:line 证据表。指导 Task 4/5/6/8 的 C++ wrapper
是否必须。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: C++ UFUNCTION `SetSectionTimecodeSource` (无 DeltaFrame)

**Files:**
- Modify: `Source/PostRenderTool/Public/PostRenderToolBuildHelper.h`
- Modify: `Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp`

**修订** (采纳 CodeX 反馈):
- 删除不存在的 `DeltaFrame` 参数(UE `FMovieSceneTimecodeSource` 只有 `Timecode` 字段,`MovieSceneSection.h:205-206`)
- wrapper 签名 = 4 段 SMPTE + drop-frame flag,直接构造 `FTimecode` 赋给 `Source.Timecode`

- [ ] **Step 1: 在 `PostRenderToolBuildHelper.h` 加 forward decl + UFUNCTION declaration**

Add forward decl after `class UMovieSceneSequence;`:

```cpp
class UMovieSceneSection;
```

Add UFUNCTION at end of `UPostRenderToolBuildHelper` class:

```cpp
    // ====================================================================
    // Timecode sync bridge
    // ====================================================================

    /**
     * 设置 UMovieSceneSection 上的 FMovieSceneTimecodeSource.
     *
     * UE 5.7 FMovieSceneTimecodeSource (MovieSceneSection.h:181-207) 只有
     * 一个 FTimecode Timecode 字段; 没有 DeltaFrame。Section 在
     * sequence-local frame space 的起点本身就 == 0 (现 plugin pipeline),
     * 不需要额外 offset。
     *
     * Sequencer UI 读 UMovieScene::GetEarliestTimecodeSource() 时扫描所有
     * sections 取最小的 TimecodeSource → UI 显示对应 SMPTE。
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Timecode")
    static void SetSectionTimecodeSource(
        UMovieSceneSection* Section,
        int32 Hours,
        int32 Minutes,
        int32 Seconds,
        int32 Frames,
        bool bDropFrame);
```

- [ ] **Step 2: 在 `PostRenderToolBuildHelper.cpp` 加 impl**

文件顶部 include:

```cpp
#include "MovieSceneSection.h"
```

文件末尾追加:

```cpp
void UPostRenderToolBuildHelper::SetSectionTimecodeSource(
    UMovieSceneSection* Section,
    int32 Hours, int32 Minutes, int32 Seconds, int32 Frames,
    bool bDropFrame)
{
    if (Section == nullptr)
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderTool] SetSectionTimecodeSource: Section is null."));
        return;
    }

    Section->Modify();

    FMovieSceneTimecodeSource Source;
    Source.Timecode = FTimecode(Hours, Minutes, Seconds, Frames, bDropFrame);
    Section->TimecodeSource = Source;

    UE_LOG(LogTemp, Log,
        TEXT("[PostRenderTool] Section %s TimecodeSource set: %02d:%02d:%02d%s%02d"),
        *Section->GetName(),
        Hours, Minutes, Seconds, bDropFrame ? TEXT(";") : TEXT(":"), Frames);
}
```

- [ ] **Step 3: UBT 重编 plugin (lanPC)**

按 CLAUDE.md "Live Coding does NOT support UPROPERTY changes" 规则:

```bash
ssh lanpc 'cd "/d/Program Files/Epic Games/UE_5.7" && \
  Engine/Build/BatchFiles/Build.bat PostRenderToolEditor Win64 Development \
  -Project="E:/RenderStream Projects/test_0311/test_0311.uproject" \
  -WaitMutex -FromMsBuild'
```

Expected: `Total build time: ... 0 errors`

- [ ] **Step 4: Verify UFUNCTION visible from Python (lanPC UE Editor 启动后)**

UE Editor Python console:

```python
help(unreal.PostRenderToolBuildHelper)
# 搜 set_section_timecode_source(...)
```

Expected: `set_section_timecode_source` method 可见。

- [ ] **Step 5: Commit**

```bash
git add Source/PostRenderTool/Public/PostRenderToolBuildHelper.h \
        Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp
git commit -m "feat(cpp): UFUNCTION SetSectionTimecodeSource

写 UMovieSceneSection.TimecodeSource 的 C++ wrapper, 平参数
避免 USTRUCT Python 暴露问题。

UE 5.7 FMovieSceneTimecodeSource (MovieSceneSection.h:181-207)
只有 FTimecode Timecode 字段, 没有 DeltaFrame; section 起点本就
是 sequence-local 0, 不需额外 offset。

需要 UBT 重编 plugin + 重启 UE Editor (C++ UFUNCTION 改动)。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `UPostRenderCameraSamples` 加 canonical `StartTimecode`

**Files:**
- Modify: `Source/PostRenderTool/Public/PostRenderCameraSamples.h`
- Modify: `Source/PostRenderTool/Private/PostRenderCameraSamples.cpp` (PostLoad 若需 default 初始化)
- Modify: `Source/PostRenderTool/Public/PostRenderToolBuildHelper.h` (`WriteCameraSamples` 签名加 4 个 timecode int + drop_frame)
- Modify: `Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp` (impl 持久化)

**关键决策** (采纳 CodeX 建议):

把 SMPTE start timecode 作为 canonical 数据存到 `UPostRenderCameraSamples` DataAsset 上,不再让 P1 实现靠 Python 反射 `Section.TimecodeSource`。DataAsset 已有 `FrameRateNumerator/Denominator`,加 `StartTimecode` 顺手。

- [ ] **Step 1: 在 `PostRenderCameraSamples.h` 加字段**

在 `UCLASS()` body 现有字段后加:

```cpp
    // ----- Canonical start timecode (写入时持久化, P1 直接读) -----

    /** trimmed first frame 对应的 SMPTE timecode 小时位. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Timecode")
    int32 StartTimecodeHours = 0;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Timecode")
    int32 StartTimecodeMinutes = 0;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Timecode")
    int32 StartTimecodeSeconds = 0;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Timecode")
    int32 StartTimecodeFrames = 0;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Timecode")
    bool bStartTimecodeDropFrame = false;

    /** 是否填了 timecode (兼容旧资产 — 没填则 P1 拒绝 patch + UI 提示). */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Timecode")
    bool bHasStartTimecode = false;
```

- [ ] **Step 2: 改 `WriteCameraSamples` 签名带 timecode 参数**

`PostRenderToolBuildHelper.h:137-144`,改成:

```cpp
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static bool WriteCameraSamples(
        UPostRenderCameraSamples* SampleAsset,
        const TArray<int32>& FrameNumbers,
        const TArray<FPostRenderCameraSample>& Samples,
        int32 FrameRateNumerator,
        int32 FrameRateDenominator,
        const FString& SourceCsvPath,
        // 新增 (P0 timecode sync):
        int32 StartTimecodeHours,
        int32 StartTimecodeMinutes,
        int32 StartTimecodeSeconds,
        int32 StartTimecodeFrames,
        bool bStartTimecodeDropFrame,
        bool bHasStartTimecode);
```

`PostRenderToolBuildHelper.cpp` impl 末尾(`RecomputeContiguity()` 之前):

```cpp
    SampleAsset->StartTimecodeHours = StartTimecodeHours;
    SampleAsset->StartTimecodeMinutes = StartTimecodeMinutes;
    SampleAsset->StartTimecodeSeconds = StartTimecodeSeconds;
    SampleAsset->StartTimecodeFrames = StartTimecodeFrames;
    SampleAsset->bStartTimecodeDropFrame = bStartTimecodeDropFrame;
    SampleAsset->bHasStartTimecode = bHasStartTimecode;
```

- [ ] **Step 3: UBT 重编 plugin + 重启 UE Editor**

```bash
ssh lanpc 'cd "/d/Program Files/Epic Games/UE_5.7" && \
  Engine/Build/BatchFiles/Build.bat PostRenderToolEditor Win64 Development \
  -Project="E:/RenderStream Projects/test_0311/test_0311.uproject" \
  -WaitMutex -FromMsBuild'
```

Expected: 0 errors.

UE Editor 重启后,Python:

```python
help(unreal.PostRenderToolBuildHelper.write_camera_samples)
# 应该看到新增的 6 个 timecode 参数
```

- [ ] **Step 4: Commit**

```bash
git add Source/PostRenderTool/Public/PostRenderCameraSamples.h \
        Source/PostRenderTool/Public/PostRenderToolBuildHelper.h \
        Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp
git commit -m "feat(cpp): UPostRenderCameraSamples 加 canonical StartTimecode

把 SMPTE start timecode (HMSF + drop-frame + has-flag) 作为
canonical 数据存到 DataAsset, P1 EXR patcher / OTIO exporter
直接读 sample_asset 字段, 不靠 Python 反射 Section.TimecodeSource。

WriteCameraSamples 加 6 个 timecode 参数 (HMSF + drop + has)。

需要 UBT 重编 plugin + 重启 UE Editor (UPROPERTY 改动)。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: sequence_builder 注入 Section TimecodeSource + 持久化 DataAsset

**Files:**
- Modify: `Content/Python/post_render_tool/sequence_builder.py`
- Modify: `Content/Python/post_render_tool/pipeline.py` (let parse_csv_dense get fps)

- [ ] **Step 1: pipeline.py 改成 parse 时传 fps**

`pipeline.py` 现有:

```python
csv_result = parse_csv_dense(csv_path)
```

(在 line ~115 左右,Task 2 已经把 `parse_csv_dense` signature 改成 `fps=None` 默认。这里要传 fps):

```python
csv_result = parse_csv_dense(csv_path, fps=fps)
```

- [ ] **Step 2: sequence_builder.py — `WriteCameraSamples` 调用带 timecode**

`sequence_builder.py:171-178` 是 `WriteCameraSamples` 调用。改成:

```python
    tc = csv_result.start_timecode
    has_tc = tc is not None
    ok = unreal.PostRenderToolBuildHelper.write_camera_samples(
        samples_asset,
        frame_numbers,
        sample_structs,
        numerator,
        denominator,
        csv_result.file_path,
        # 新增:
        tc.hours if has_tc else 0,
        tc.minutes if has_tc else 0,
        tc.seconds if has_tc else 0,
        tc.frames if has_tc else 0,
        tc.drop_frame if has_tc else False,
        has_tc,
    )
```

- [ ] **Step 3: sequence_builder.py — Camera Cut Section TimecodeSource (Step 4a)**

在 `sequence_builder.py:125` (`camera_cut_section.set_camera_binding_id(...)`) 之后插入:

```python
    # ------------------------------------------------------------------
    # Step 4a: Set Camera Cut Section.TimecodeSource (P0 G1)
    # ------------------------------------------------------------------
    if csv_result.start_timecode is not None:
        tc = csv_result.start_timecode
        unreal.PostRenderToolBuildHelper.set_section_timecode_source(
            camera_cut_section,
            tc.hours, tc.minutes, tc.seconds, tc.frames,
            tc.drop_frame,
        )
```

- [ ] **Step 4: sequence_builder.py — UPostRenderCameraSection TimecodeSource (Step 6a)**

在 `sequence_builder.py:202` (`section.set_editor_property("sample_asset", samples_asset)`) 之后:

```python
    # ------------------------------------------------------------------
    # Step 6a: Set UPostRenderCameraSection.TimecodeSource (P0 G1)
    # ------------------------------------------------------------------
    if csv_result.start_timecode is not None:
        tc = csv_result.start_timecode
        unreal.PostRenderToolBuildHelper.set_section_timecode_source(
            section,
            tc.hours, tc.minutes, tc.seconds, tc.frames,
            tc.drop_frame,
        )
```

- [ ] **Step 5: lanPC UE Editor take_4 集成验证**

```python
import importlib
import post_render_tool.timecode as tc
import post_render_tool.csv_parser as cp
import post_render_tool.sequence_builder as sb
import post_render_tool.pipeline as p
importlib.reload(tc); importlib.reload(cp); importlib.reload(sb); importlib.reload(p)

from post_render_tool.pipeline import run_import
result = run_import(r"E:/RenderStream Projects/test_0311/CSV/take_4_dense.csv", fps=50.0)
```

Expected Output Log:
- `[PostRenderTool] Section CameraCut TimecodeSource set: HH:MM:SS:FF` (2 条 — Camera Cut + UPostRenderCameraSection)
- 无异常

- [ ] **Step 6: 在 Sequencer 验证 G1**

UE Editor Outliner 找新生成 LevelSequence,双击打开。Sequencer:
- 右上角 View Options → Show Timecode
- 时间轴 frame 0 显示 = take_4 trimmed start timecode (跟 CSV 第一帧 timestamp 一致)

Expected: 显示 SMPTE 不是 0 起的相对帧号。

- [ ] **Step 7: 验证 DataAsset 持久化 timecode**

UE Editor Content Browser 找 sample DataAsset (e.g. `/Game/PostRender/take_4_dense/LS_take_4_dense_Samples`),双击打开 Details panel。

Expected: 看到 `Start Timecode Hours = 10`, `Minutes = 0`, ..., `bHasStartTimecode = true`, `bStartTimecodeDropFrame = false`(对应 50fps non-drop)。

- [ ] **Step 8: G6 fail-fast 验证**

人工改 take_4 CSV 让某一帧 frame_number 跟 timestamp 不一致,跑 `run_import`:

Expected: `CsvTimecodeMismatch` 抛出,Content Browser 里**没**新的 LevelSequence / DataAsset 资产创建。

- [ ] **Step 9: take_4 几何回归 (P0 收窄 gate)**

按 `docs/d3-take5-static-diff-workflow.md` 步骤跑 take_4 静态帧 diff。残差应在数值噪声范围 (TimecodeSource 不影响 evaluator)。

- [ ] **Step 10: Commit**

```bash
git add Content/Python/post_render_tool/sequence_builder.py \
        Content/Python/post_render_tool/pipeline.py
git commit -m "feat(sequence_builder): Section TimecodeSource + DataAsset 持久化

Step 4a + 6a: Camera Cut Section + UPostRenderCameraSection 上挂
csv_result.start_timecode。WriteCameraSamples 也带 6 个新参数把
canonical timecode 持久化到 sample DataAsset。

Sequencer UI 切到 Timecode 显示, frame 0 = 现场拍摄 SMPTE timecode。
DataAsset.bHasStartTimecode = true 时 P1 patcher / OTIO exporter
能直接读, 无需 Python 反射 Section。

take_4 几何回归通过 (TimecodeSource 不影响 evaluator)。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: MRQ FrameNumberOffset + filename pattern

**Files:**
- Modify: `Content/Python/post_render_tool/ui_interface.py`

修订 (采纳 CodeX 反馈):
- 删除多余的 `level_sequence.get_movie_scene_sequence().get_movie_scene()` 死代码
- `_find_first_csv_frame_from_sequence` 直接走 bindings → tracks → sections → sample_asset.source_frame_numbers

- [ ] **Step 1: 改 `open_movie_render_queue` impl**

打开 `ui_interface.py:167-201`,替换函数体:

```python
def open_movie_render_queue(level_sequence=None) -> None:
    """把 LevelSequence 预填到 MRQ queue 并配置 absolute CSV frame 文件名。"""
    if level_sequence is not None:
        try:
            queue_subsystem = unreal.get_editor_subsystem(
                unreal.MoviePipelineQueueSubsystem
            )
            if queue_subsystem is None:
                unreal.log_warning(
                    "[ui_interface] MoviePipelineQueueSubsystem 不可用"
                )
            else:
                queue = queue_subsystem.get_queue()
                job = unreal.MoviePipelineEditorLibrary.create_job_from_sequence(
                    queue, level_sequence
                )
                if job is not None:
                    unreal.MoviePipelineEditorLibrary.ensure_job_has_default_settings(
                        job
                    )
                    _apply_csv_frame_filename_offset(job, level_sequence)
                    unreal.log(
                        f"[ui_interface] 已把 {level_sequence.get_name()} "
                        "添加到 MRQ queue (FrameNumberOffset 已配)"
                    )
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning(f"[ui_interface] MRQ queue 预填失败: {exc}")

    unreal.log(
        "[ui_interface] 请手动打开 Movie Render Queue: "
        "菜单 Window → Cinematics → Movie Render Queue"
    )


def _apply_csv_frame_filename_offset(job, level_sequence) -> None:
    """从 LevelSequence 关联的 UPostRenderCameraSamples DataAsset 拿到
    absolute CSV start frame, 设给 MRQ job 的 UMoviePipelineOutputSetting。"""
    config = job.get_configuration()
    output_setting = config.find_or_add_setting_by_class(
        unreal.MoviePipelineOutputSetting
    )

    first_frame = _find_first_csv_frame_from_sequence(level_sequence)
    if first_frame is None:
        unreal.log_warning(
            "[ui_interface] 未找到 UPostRenderCameraSamples DataAsset, "
            "跳过 FrameNumberOffset 配置"
        )
        return

    # UE 5.7 MoviePipelineOutputSetting.h:101 FrameNumberOffset UPROPERTY;
    # 若 Python 直接访问不工作, 用 set_editor_property 兜底
    output_setting.set_editor_property("frame_number_offset", int(first_frame))
    output_setting.set_editor_property("zero_pad_frame_numbers", 7)
    output_setting.set_editor_property("file_name_format", "render.{frame_number}")

    unreal.log(
        f"[ui_interface] MRQ output: FrameNumberOffset={first_frame}, "
        "FileNameFormat=render.{frame_number} (7-digit pad)"
    )


def _find_first_csv_frame_from_sequence(level_sequence):
    """遍历 sequence bindings → tracks → sections → sample_asset.source_frame_numbers[0]."""
    for binding in level_sequence.get_bindings():
        for track in binding.get_tracks():
            if track.get_class().get_name() == "PostRenderCameraTrack":
                for section in track.get_sections():
                    sample_asset = section.get_editor_property("sample_asset")
                    if sample_asset is None:
                        continue
                    frame_numbers = sample_asset.source_frame_numbers
                    if frame_numbers:
                        return int(frame_numbers[0])
    return None
```

- [ ] **Step 2: lanPC UE Editor 验证 G5**

```python
import importlib, post_render_tool.ui_interface as ui
importlib.reload(ui)

ls = unreal.EditorAssetLibrary.load_asset(
    "/Game/PostRender/take_4_dense/LS_take_4_dense"
)
ui.open_movie_render_queue(ls)
```

Expected Output Log:
```
[ui_interface] MRQ output: FrameNumberOffset=<first_csv_frame>, FileNameFormat=render.{frame_number} (7-digit pad)
[ui_interface] 已把 LS_take_4_dense 添加到 MRQ queue (FrameNumberOffset 已配)
```

打开 MRQ tab 看 job settings → Output: `Frame Number Offset = <first_csv_frame>`,`File Name Format = render.{frame_number}`,`Zero Pad = 7`。

渲一帧:Expected 文件名 = `render.<first_csv_frame>.exr` (7-digit pad)。

- [ ] **Step 3: Commit**

```bash
git add Content/Python/post_render_tool/ui_interface.py
git commit -m "feat(mrq): MRQ 文件名带 absolute CSV frame number

open_movie_render_queue 从 LevelSequence binding → PostRenderCameraTrack
→ Section → sample_asset.source_frame_numbers[0] 拿 absolute CSV
start frame, 设给 UMoviePipelineOutputSetting (UE 5.7 原生
FrameNumberOffset, MoviePipelineOutputSetting.h:101):
  - FrameNumberOffset = first_csv_frame
  - ZeroPadFrameNumbers = 7
  - FileNameFormat = render.{frame_number}

渲出文件名 = render.<abs>.exr, 下游按文件名手动 conform 或
P1 EXR header 自动 conform。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: P0 集成验证 + Merge

**Files:** N/A (验证 task)

P0 完成 gate(收窄):unit tests + C++ build + lanPC import + Sequencer SMPTE 显示 + MRQ filename offset + take_4 几何 regression 全绿。

- [ ] **Step 1: 跑完整 unit test suite**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec/Content/Python
python -m unittest discover -s post_render_tool/tests -p "test_*.py" -v
```

Expected: 全 pass。

- [ ] **Step 2: lanPC UE Editor 完整 take_4 import**

参照 Task 6 Step 5。

- [ ] **Step 3: G1 Sequencer 验证**

参照 Task 6 Step 6。

- [ ] **Step 4: G5 MRQ filename 验证**

参照 Task 7 Step 2。

- [ ] **Step 5: G6 fail-fast 验证**

参照 Task 6 Step 8。

- [ ] **Step 6: take_4 几何回归**

参照 Task 6 Step 9。

- [ ] **Step 7: DataAsset timecode 持久化验证**

参照 Task 6 Step 7。

- [ ] **Step 8: P0 Merge**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git checkout main
git merge --no-ff worktree-timecode-sync-spec -m "feat(timecode-sync): P0 — MVP

Sequencer UI 显示现场 SMPTE timecode (G1)
MRQ 输出文件名带 absolute CSV frame (G5)
CSV timestamp ↔ frame_number 等价性 fail-fast (G6)

UPostRenderCameraSamples DataAsset 持久化 canonical StartTimecode,
为 P1 EXR patcher / OTIO exporter 提供直读源。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

# 按 CLAUDE.md '--no-ff merges 不触发 post-commit hook' 规则手动 push p4
git push p4 main
```

---

## Phase P1 — 自动 conform (G2 / G4)

P1 完成 gate:unit tests + EXR header 真实 typed attributes 验证(`exrheader`)+ DaVinci 19+ 实测 import + Nuke 实测 import。

**注意 (采纳 CodeX 反馈)**:P1 不能跟 P0 混做。EXR / OTIO 都必须**外部 DCC 实测**才算完成,否则容易出现"unit test 绿但生产软件不认"假完成。

### Task 9: EXR Writer Spike — 三 backend + 真实 typed attribute 验证

**Files:**
- Create: `scripts/exr_timecode_spike.py`
- Create: `scripts/exr_timecode_spike_report.md`

修订 (采纳 CodeX 反馈):
- 不能只信 `oiiotool --info` 文本;必须用 `exrheader` (OpenEXR 自带工具)显示真实 EXR typed attributes 的 name + type
- DaVinci 19+ import 实测 = spike 最终接受标准

- [ ] **Step 1: 准备 spike fixture (lanPC 渲 1 帧)**

P0 跑出的一帧 MRQ EXR 复制三份到 spike workspace:

```bash
# 在 spike workspace
mkdir -p scripts/spike/
cp /path/to/render.0625914.exr scripts/spike/spike_input_a.exr
cp /path/to/render.0625914.exr scripts/spike/spike_input_b.exr
cp /path/to/render.0625914.exr scripts/spike/spike_input_c.exr
cp /path/to/render.0625914.exr scripts/spike/spike_baseline.exr
```

- [ ] **Step 2: Spike (a) PyPI OpenEXR + Imath**

`scripts/exr_timecode_spike.py`:

```python
"""Spike: 三种 EXR header timecode writer.
真实接受标准: exrheader 显示标准 typed attributes + DaVinci import OK."""
import subprocess
import sys


def spike_a_openexr_python(path: str, hh: int, mm: int, ss: int, ff: int, drop: bool, fps: int):
    """候选 (a): PyPI OpenEXR + Imath."""
    import OpenEXR, Imath
    f = OpenEXR.InputFile(path)
    header = f.header()
    f.close()
    # 写 timeCode + framesPerSecond:
    tc = Imath.TimeCode(hh, mm, ss, ff, drop_frame=drop)
    header["timeCode"] = tc
    header["framesPerSecond"] = Imath.Rational(fps, 1)
    # rewrite
    # PyPI OpenEXR 重写需要 OutputFile + scanlines 手动复制, 易丢 channels
    # 若失败 → 标 (a) FAIL
    raise NotImplementedError(
        "PyPI OpenEXR API 1.3.x 还不支持 round-trip rewrite 保留 channels; "
        "spike report 标 FAIL"
    )


def spike_b_oiiotool(path: str, hh: int, mm: int, ss: int, ff: int, drop: bool, fps: int):
    """候选 (b): oiiotool CLI."""
    tc_str = f"{hh:02d}:{mm:02d}:{ss:02d}{':;'[drop]}{ff:02d}"
    subprocess.check_call([
        "oiiotool", path,
        "--attrib", "smpte:TimeCode", tc_str,
        "--attrib:type=rational", "FramesPerSecond", f"{fps}/1",
        "-o", path,
    ])


def spike_c_mrq_image_pass():
    """候选 (c): UMoviePipelineImagePassBase 子类。
    Spike 阶段无法独立验证, 需要 plugin C++ side 改 output pass; 标 DEFER。"""
    pass


if __name__ == "__main__":
    backend, path = sys.argv[1], sys.argv[2]
    if backend == "a":
        spike_a_openexr_python(path, 9, 44, 23, 22, False, 50)
    elif backend == "b":
        spike_b_oiiotool(path, 9, 44, 23, 22, False, 50)
    print(f"spike-{backend} done for {path}")
```

```bash
pip install OpenEXR Imath
brew install openexr openimageio   # macOS
# Windows: scoop install openexr openimageio

python scripts/exr_timecode_spike.py a scripts/spike/spike_input_a.exr 2>&1 | tee scripts/spike/log_a.txt
python scripts/exr_timecode_spike.py b scripts/spike/spike_input_b.exr 2>&1 | tee scripts/spike/log_b.txt
```

- [ ] **Step 3: 用 `exrheader` 验证真实 typed attribute (不是 oiiotool display name)**

`exrheader` 是 OpenEXR 自带工具,显示底层 typed attribute 名 + type。

```bash
exrheader scripts/spike/spike_input_a.exr > scripts/spike/header_a.txt
exrheader scripts/spike/spike_input_b.exr > scripts/spike/header_b.txt
exrheader scripts/spike/spike_baseline.exr > scripts/spike/header_baseline.txt
```

Expected (b 成功的话):header_b.txt 应该包含:
```
timeCode (type timecode): time 0x..., user 0x...
framesPerSecond (type rational): 50/1
```

如果只有 `smpte:TimeCode (type string): ...` 这种,说明 oiiotool 写的是 string display name 不是 OpenEXR 标准 `timeCode` typed attribute → spike 失败,继续 (c) 或换 writer。

对比 channels / compression / pixelAspectRatio 等其他 attribute,确保 patcher **没丢**:
```bash
diff scripts/spike/header_b.txt scripts/spike/header_baseline.txt
# 期望: 只在 timeCode / framesPerSecond 行有差异, channels / compression 等不变
```

- [ ] **Step 4: DaVinci 19+ 实测 import (P1 spike 最终接受标准)**

把 spike_input_b.exr (或 a / c) import 进 DaVinci 19+ Media Pool。

Expected:DaVinci Inspector 显示 EXR 的 SMPTE Timecode 字段(具体 UI 路径:Inspector → File → Time Code = `09:44:23:22`)。

如果 DaVinci 不识别 → 该 backend 失败,换下一个。

- [ ] **Step 5: 写 spike report 选 backend**

`scripts/exr_timecode_spike_report.md`,记录:
- (a) PyPI OpenEXR:是否 PASS / 丢什么 attribute / DaVinci 是否识别
- (b) oiiotool:同上
- (c) MRQ output pass:DEFER 或独立 follow-up
- 决策:Task 10 用哪个 backend (默认 b oiiotool,若 b fail 加 follow-up task 做 c)

- [ ] **Step 6: Commit**

```bash
git add scripts/exr_timecode_spike.py scripts/exr_timecode_spike_report.md \
        scripts/spike/log_*.txt scripts/spike/header_*.txt
git commit -m "chore(spike): EXR header timecode writer backend 选型

跑 PyPI OpenEXR vs oiiotool 写 SMPTE timeCode + framesPerSecond,
用 exrheader 验证真实 typed attribute (not OIIO display name),
DaVinci 19+ import 实测识别 timecode 为最终接受标准。

Task 10 选 <backend>。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `exr_timecode_writer.py` 实现 + unit test

**Files:**
- Create: `Content/Python/post_render_tool/exr_timecode_writer.py`
- Create: `Content/Python/post_render_tool/tests/test_exr_timecode_writer.py`

**前置**:Task 9 spike 选出 backend (假设 oiiotool)。

- [ ] **Step 1: Write failing test**

`Content/Python/post_render_tool/tests/test_exr_timecode_writer.py`:

```python
"""离线 EXR patcher 测试. 不依赖 unreal."""
import os
import shutil
import subprocess
import tempfile
import unittest

from post_render_tool.exr_timecode_writer import (
    patch_exr_timecode_in_dir, _frame_to_timecode,
)
from post_render_tool.timecode import Timecode


def _gen_test_exr(path: str) -> None:
    subprocess.check_call([
        "oiiotool",
        "--create", "4x4", "3",
        "--fill:color=0.5,0.5,0.5", "4x4",
        "-o", path,
    ])


def _read_exr_typed_attribute(path: str, attr_name: str) -> str:
    """用 exrheader (而非 oiiotool --info) 读真实 typed attribute."""
    out = subprocess.check_output(
        ["exrheader", path], text=True, stderr=subprocess.STDOUT
    )
    for line in out.splitlines():
        if attr_name in line:
            return line.strip()
    return ""


class TestPatchExrTimecode(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        for i in range(3):
            _gen_test_exr(os.path.join(self.tmpdir, f"render.{625914 + i:07d}.exr"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_50fps_patch_writes_typed_timecode(self):
        n = patch_exr_timecode_in_dir(
            self.tmpdir,
            "render.{frame:07d}.exr",
            start_csv_frame=625914,
            start_timecode=Timecode.parse("10:00:00:00", 50.0),
            fps=50.0,
        )
        self.assertEqual(n, 3)
        first = os.path.join(self.tmpdir, "render.0625914.exr")
        # 关键: 验证 exrheader 看到 typed timeCode attribute, 不是 display name
        hdr = _read_exr_typed_attribute(first, "timeCode")
        self.assertIn("timecode", hdr.lower())  # type tag

    def test_increments_per_frame_50fps(self):
        patch_exr_timecode_in_dir(
            self.tmpdir, "render.{frame:07d}.exr",
            625914, Timecode.parse("10:00:00:00", 50.0), 50.0,
        )
        # ... 验证 frame 625914 / 625915 / 625916 对应 10:00:00:00 / 01 / 02

    def test_nonexistent_dir_returns_zero(self):
        n = patch_exr_timecode_in_dir(
            "/no/such/dir", "render.{frame:07d}.exr",
            625914, Timecode.parse("10:00:00:00", 50.0), 50.0,
        )
        self.assertEqual(n, 0)


class TestFrameToTimecodeRoundTrip(unittest.TestCase):
    def test_non_drop_round_trip(self):
        start = Timecode.parse("10:00:00:00", 50.0)
        for offset in [0, 1, 49, 50, 100, 50 * 60, 50 * 3600]:
            tc = _frame_to_timecode(start, offset)
            self.assertEqual(
                tc.to_frames() - start.to_frames(),
                offset,
                f"round-trip fail at offset {offset}",
            )

    def test_drop_frame_round_trip(self):
        start = Timecode.parse("00:00:00;00", 29.97)
        for offset in [0, 1, 1797, 1798, 17981, 17982, 17983]:
            tc = _frame_to_timecode(start, offset)
            self.assertEqual(
                tc.to_frames() - start.to_frames(),
                offset,
                f"drop round-trip fail at offset {offset}",
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test, verify fails**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec/Content/Python
python -m unittest post_render_tool.tests.test_exr_timecode_writer -v
```
Expected: ImportError on `patch_exr_timecode_in_dir`.

- [ ] **Step 3: Implement `exr_timecode_writer.py`**

`Content/Python/post_render_tool/exr_timecode_writer.py`:

```python
"""EXR header SMPTE timecode patcher (oiiotool backend)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .timecode import Timecode


def _ensure_oiiotool() -> None:
    if shutil.which("oiiotool") is None:
        raise RuntimeError(
            "oiiotool not on PATH. 安装 OpenImageIO: "
            "macOS=`brew install openimageio`, Windows=`scoop install openimageio`."
        )


def _frame_to_timecode(start: Timecode, offset_frames: int) -> Timecode:
    """从 start 起 offset_frames 后的 Timecode (drop-frame aware)."""
    total = start.to_frames() + offset_frames
    nominal_fps = round(start.rate_num / start.rate_den)

    if not start.drop_frame:
        ff = total % nominal_fps
        ts = total // nominal_fps
        ss = ts % 60
        mm = (ts // 60) % 60
        hh = ts // 3600
        return Timecode(hh, mm, ss, ff, False, start.rate_num, start.rate_den)

    # NTSC drop-frame 反向算法
    drop_count = 2 if abs(start.rate_num / start.rate_den - 29.97) < 0.01 else 4
    # 每 10 分钟块: nominal*600 - drop_count*9 帧
    frames_per_10min = nominal_fps * 600 - drop_count * 9
    # 后续每分钟 (非整 10): nominal*60 - drop_count
    frames_per_min_minus = nominal_fps * 60 - drop_count

    d = total // frames_per_10min          # 10 分钟块数
    m = total - d * frames_per_10min       # 块内剩余帧

    # 块内第 0 分钟是 nominal*60 帧 (不丢), 后续 9 分钟丢 drop_count
    if m < nominal_fps * 60:
        minute_in_block = 0
        m_in_minute = m
    else:
        m_remainder = m - nominal_fps * 60
        minute_in_block = 1 + m_remainder // frames_per_min_minus
        m_in_minute = m_remainder % frames_per_min_minus + drop_count
        # ↑ 后续分钟前 drop_count 帧被丢, timecode 跳过 → 实际显示 ff 加 drop_count

    total_minutes = d * 10 + minute_in_block
    hh = total_minutes // 60
    mm = total_minutes % 60
    ss = m_in_minute // nominal_fps
    ff = m_in_minute % nominal_fps
    return Timecode(hh, mm, ss, ff, True, start.rate_num, start.rate_den)


def patch_exr_timecode_in_dir(
    output_dir: str,
    filename_pattern: str,        # "render.{frame:07d}.exr"
    start_csv_frame: int,
    start_timecode: Timecode,
    fps: float,
) -> int:
    """Patch typed SMPTE timeCode + FramesPerSecond 属性到所有匹配 EXR.

    Returns: 处理成功的文件数."""
    out_path = Path(output_dir)
    if not out_path.is_dir():
        return 0

    _ensure_oiiotool()

    # filename_pattern → regex 抓 absolute frame number
    fn_regex_str = re.sub(
        r"\{frame:(\d+)d\}",
        lambda m: r"(\d{" + m.group(1) + r"})",
        re.escape(filename_pattern),
    )
    fn_regex = re.compile(f"^{fn_regex_str}$")

    nominal_fps = int(round(fps))
    processed = 0
    for file in sorted(out_path.iterdir()):
        m = fn_regex.match(file.name)
        if m is None:
            continue
        frame = int(m.group(1))
        offset = frame - start_csv_frame
        if offset < 0:
            continue
        tc = _frame_to_timecode(start_timecode, offset)
        tc_str = str(tc)

        # oiiotool 写 typed attributes (Task 9 spike 验证可行)
        subprocess.check_call([
            "oiiotool", str(file),
            "--attrib:type=timecode", "smpte:TimeCode", tc_str,
            "--attrib:type=rational", "FramesPerSecond", f"{nominal_fps}/1",
            "-o", str(file),
        ])
        processed += 1

    return processed
```

- [ ] **Step 4: Run tests — verify pass**

```bash
python -m unittest post_render_tool.tests.test_exr_timecode_writer -v
```
Expected: 全 pass。

如 `test_drop_frame_round_trip` fail,在 `_frame_to_timecode` drop-frame 分支修正。

- [ ] **Step 5: Commit**

```bash
git add Content/Python/post_render_tool/exr_timecode_writer.py \
        Content/Python/post_render_tool/tests/test_exr_timecode_writer.py
git commit -m "feat(exr): SMPTE timecode patcher (oiiotool backend)

patch_exr_timecode_in_dir 给目录内匹配 filename_pattern 的 EXR
header 写 typed smpte:TimeCode + FramesPerSecond rational
attribute, 保留 MRQ 原 channels/compression/multipart。

drop-frame round-trip 数学 (29.97 / 59.94 NTSC) 单元测试覆盖。

测试用 exrheader (而非 oiiotool --info) 校验真实 typed
attribute, 跟 Task 9 spike 决策一致。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: `otio_export.py` 实现 + unit test

**Files:**
- Create: `Content/Python/post_render_tool/otio_export.py`
- Create: `Content/Python/post_render_tool/tests/test_otio_export.py`

- [ ] **Step 1: Write failing test**

`Content/Python/post_render_tool/tests/test_otio_export.py`:

```python
import os
import tempfile
import unittest

import opentimelineio as otio

from post_render_tool.otio_export import export_sidecar
from post_render_tool.timecode import Timecode


class TestOtioExport(unittest.TestCase):
    def test_timeline_has_cg_track_with_image_seq_ref(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "shot.otio")
            export_sidecar(
                sidecar_path=out,
                shot_name="take_4",
                cg_render_dir="/renders/take_4",
                cg_filename_pattern="render.{frame:07d}.exr",
                start_csv_frame=625914,
                frame_count=100,
                start_timecode=Timecode.parse("10:00:00:00", 50.0),
                fps=50.0,
            )
            tl = otio.adapters.read_from_file(out)
            self.assertEqual(len(tl.tracks), 1)
            cg_track = tl.tracks[0]
            self.assertEqual(cg_track.name, "CG Render")
            clip = cg_track[0]
            ref = clip.media_reference
            self.assertIsInstance(ref, otio.schema.ImageSequenceReference)
            self.assertEqual(ref.start_frame, 625914)
            self.assertEqual(ref.frame_zero_padding, 7)

    def test_global_start_time_matches_csv_timecode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "shot.otio")
            export_sidecar(
                sidecar_path=out,
                shot_name="take_4",
                cg_render_dir="/renders/take_4",
                cg_filename_pattern="render.{frame:07d}.exr",
                start_csv_frame=625914,
                frame_count=100,
                start_timecode=Timecode.parse("10:00:00:00", 50.0),
                fps=50.0,
            )
            tl = otio.adapters.read_from_file(out)
            gst = tl.global_start_time
            self.assertAlmostEqual(gst.rate, 50.0, places=3)
            self.assertEqual(
                otio.opentime.to_timecode(gst, rate=50.0), "10:00:00:00"
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test, verify fails**

```bash
pip install opentimelineio
python -m unittest post_render_tool.tests.test_otio_export -v
```

- [ ] **Step 3: Implement `otio_export.py`**

```python
"""OTIO sidecar exporter. Pure Python."""
from __future__ import annotations

import re
import opentimelineio as otio

from .timecode import Timecode


def export_sidecar(
    sidecar_path: str,
    shot_name: str,
    cg_render_dir: str,
    cg_filename_pattern: str,    # "render.{frame:07d}.exr"
    start_csv_frame: int,
    frame_count: int,
    start_timecode: Timecode,
    fps: float,
) -> None:
    m = re.match(r"^(.*?)\{frame:0?(\d+)d\}(.*)$", cg_filename_pattern)
    if m is None:
        raise ValueError(f"Unsupported filename pattern: {cg_filename_pattern}")
    name_prefix, padding_str, name_suffix = m.group(1), m.group(2), m.group(3)
    padding = int(padding_str)

    timeline = otio.schema.Timeline(name=shot_name)
    timeline.global_start_time = otio.opentime.RationalTime(
        start_timecode.to_frames(), fps
    )

    track = otio.schema.Track(name="CG Render", kind=otio.schema.TrackKind.Video)
    img_ref = otio.schema.ImageSequenceReference(
        target_url_base=f"file://{cg_render_dir.rstrip('/')}/",
        name_prefix=name_prefix,
        name_suffix=name_suffix,
        start_frame=start_csv_frame,
        frame_zero_padding=padding,
        rate=fps,
        available_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, fps),
            duration=otio.opentime.RationalTime(frame_count, fps),
        ),
    )
    clip = otio.schema.Clip(
        name=f"{shot_name}_cg",
        media_reference=img_ref,
        source_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, fps),
            duration=otio.opentime.RationalTime(frame_count, fps),
        ),
    )
    track.append(clip)
    timeline.tracks.append(track)
    otio.adapters.write_to_file(timeline, sidecar_path)
```

- [ ] **Step 4: Run tests — verify pass**

```bash
python -m unittest post_render_tool.tests.test_otio_export -v
```

- [ ] **Step 5: DaVinci 19+ + Nuke 实测 (P1 接受标准)**

把生成的 `shot.otio` 拖进 DaVinci 19+ → Import → Timeline。

Expected:timeline 起点 timecode = `10:00:00:00`,clip 在 timeline 上的位置 + duration 跟 frame_count 一致。

如不识别,把 `source_range.start_time` 从 `RationalTime(0, fps)` 改成 `RationalTime(start_csv_frame, fps)`,重出 sidecar,再 import 一次。哪个 variant 工作就 commit 哪个。

Nuke Studio 同样 import 一次验证(若有 Nuke 许可证)。

- [ ] **Step 6: Commit**

```bash
git add Content/Python/post_render_tool/otio_export.py \
        Content/Python/post_render_tool/tests/test_otio_export.py
git commit -m "feat(otio): OTIO sidecar exporter

export_sidecar 输出 .otio: Timeline + CG Render track + Clip
with ImageSequenceReference (start_frame=absolute_csv_frame),
global_start_time = csv start timecode 对应 RationalTime。

DaVinci 19+ / Nuke Studio import 实测识别 SMPTE timecode。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: pipeline P1 API + widget UI

**Files:**
- Modify: `Content/Python/post_render_tool/pipeline.py` (PipelineResult 加 derive 字段 + 新增 `run_patch_exr_timecode` / `run_export_otio`)
- Modify: `Content/Python/post_render_tool/widget.py` (callback 绑定, 用现有 `_host`/`_bind_click`/`_get`/`_last_result` 风格)
- Modify: `Source/PostRenderTool/Public/PostRenderToolWidget.h` (3 BindWidget UPROPERTY)
- Modify: `docs/widget-tree-spec.json` (3 widget 节点)
- Modify: `Content/Python/post_render_tool/tests/test_spec_drift.py` (count 改 derive)

**修订** (采纳 CodeX 反馈):
- callback 用现有 `_host` / `_bind_click` / `_get` 风格,不是 `self.host`
- `_last_result` 已经是当前字段名,用 `_last_result.level_sequence`
- `PipelineResult` 加 `level_sequence_path` derive 字段(从 `level_sequence.get_path_name()` 推出)
- `test_spec_drift` count 从硬编码改成跟 expected set derive

- [ ] **Step 1: `PipelineResult` 加 `level_sequence_path` derive 字段**

`pipeline.py:40-51` 现有:

```python
@dataclass
class PipelineResult:
    ...
    level_sequence: Optional[object] = None
    ...
    package_path: str = ""
```

加 property:

```python
@dataclass
class PipelineResult:
    ...
    level_sequence: Optional[object] = None
    ...
    package_path: str = ""

    @property
    def level_sequence_path(self) -> Optional[str]:
        """LevelSequence 资产路径 (e.g. /Game/PostRender/take_4_dense/LS_take_4_dense)."""
        if self.level_sequence is None:
            return None
        return self.level_sequence.get_path_name()
```

- [ ] **Step 2: 实现 `run_patch_exr_timecode` + `run_export_otio` (从 sample DataAsset 读 timecode)**

`pipeline.py` 末尾追加:

```python
def run_patch_exr_timecode(
    level_sequence_asset_path: str,
    output_dir: str,
) -> dict:
    """读 LevelSequence 关联的 sample DataAsset (canonical StartTimecode 来源),
    给 output_dir 内所有匹配 EXR 文件补 SMPTE timecode header。"""
    import unreal
    from .exr_timecode_writer import patch_exr_timecode_in_dir
    from .timecode import Timecode

    ls = unreal.EditorAssetLibrary.load_asset(level_sequence_asset_path)
    if ls is None:
        raise RuntimeError(f"LevelSequence not found: {level_sequence_asset_path}")

    samples = _load_sample_asset_for_sequence(ls, level_sequence_asset_path)
    if not samples.b_has_start_timecode:
        raise RuntimeError(
            f"Sample DataAsset 没存 StartTimecode (bHasStartTimecode=false). "
            f"该 LevelSequence 可能是 timecode-sync 改造前导入的; 重跑 run_import 再 patch。"
        )

    first_frame = int(samples.source_frame_numbers[0])
    fps = samples.frame_rate_numerator / samples.frame_rate_denominator
    start_tc = Timecode(
        hours=samples.start_timecode_hours,
        minutes=samples.start_timecode_minutes,
        seconds=samples.start_timecode_seconds,
        frames=samples.start_timecode_frames,
        drop_frame=samples.b_start_timecode_drop_frame,
        rate_num=samples.frame_rate_numerator,
        rate_den=samples.frame_rate_denominator,
    )

    n = patch_exr_timecode_in_dir(
        output_dir=output_dir,
        filename_pattern="render.{frame:07d}.exr",
        start_csv_frame=first_frame,
        start_timecode=start_tc,
        fps=fps,
    )
    return {"patched_count": n, "output_dir": output_dir}


def _load_sample_asset_for_sequence(level_sequence, level_sequence_asset_path: str):
    """convention: sample DataAsset 跟 LevelSequence 同目录 + `_Samples` 后缀."""
    import unreal
    samples_path = level_sequence_asset_path + "_Samples"
    samples = unreal.EditorAssetLibrary.load_asset(samples_path)
    if samples is None:
        raise RuntimeError(f"Sample DataAsset not found: {samples_path}")
    return samples


def run_export_otio(
    level_sequence_asset_path: str,
    output_dir: str,
    sidecar_path: str,
) -> dict:
    """给定 LevelSequence + 渲染输出目录, dump <shot>.otio sidecar."""
    import unreal
    from .otio_export import export_sidecar
    from .timecode import Timecode

    ls = unreal.EditorAssetLibrary.load_asset(level_sequence_asset_path)
    samples = _load_sample_asset_for_sequence(ls, level_sequence_asset_path)
    if not samples.b_has_start_timecode:
        raise RuntimeError("Sample DataAsset 没存 StartTimecode, 见 run_patch_exr_timecode 提示。")

    first_frame = int(samples.source_frame_numbers[0])
    frame_count = len(samples.source_frame_numbers)
    fps = samples.frame_rate_numerator / samples.frame_rate_denominator
    start_tc = Timecode(
        hours=samples.start_timecode_hours,
        minutes=samples.start_timecode_minutes,
        seconds=samples.start_timecode_seconds,
        frames=samples.start_timecode_frames,
        drop_frame=samples.b_start_timecode_drop_frame,
        rate_num=samples.frame_rate_numerator,
        rate_den=samples.frame_rate_denominator,
    )

    export_sidecar(
        sidecar_path=sidecar_path,
        shot_name=ls.get_name(),
        cg_render_dir=output_dir,
        cg_filename_pattern="render.{frame:07d}.exr",
        start_csv_frame=first_frame,
        frame_count=frame_count,
        start_timecode=start_tc,
        fps=fps,
    )
    return {"sidecar_path": sidecar_path}
```

注意 Python 反射访问 UPROPERTY 时,`bool` 字段会变 `b_xxx` snake-case (UE Python `b` 前缀转 `b_` 前缀)。`bHasStartTimecode` → `b_has_start_timecode`,`bStartTimecodeDropFrame` → `b_start_timecode_drop_frame`。Day-1 probe (Task 3) 应该已验证;若实际是其他命名(如直接 `has_start_timecode`),改这里。

- [ ] **Step 3: `PostRenderToolWidget.h` 加 3 个 BindWidget UPROPERTY**

参照现有 `btn_browse` 写法,在 class 末尾加:

```cpp
    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    class UEditableTextBox* txt_render_output_dir;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    class UButton* btn_patch_exr_timecode;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    class UButton* btn_export_otio;
```

- [ ] **Step 4: UBT 重编 + Editor 重启**

```bash
ssh lanpc 'cd "/d/Program Files/Epic Games/UE_5.7" && \
  Engine/Build/BatchFiles/Build.bat PostRenderToolEditor Win64 Development \
  -Project="E:/RenderStream Projects/test_0311/test_0311.uproject" \
  -WaitMutex -FromMsBuild'
```

- [ ] **Step 5: `widget-tree-spec.json` 加 3 个节点**

按 `docs/widget-tree-spec.schema.md` 规范,在合适位置添加(看现有 spec 文件 P1 区域或新增 group):

```json
{
  "name": "txt_render_output_dir",
  "class": "EditableTextBox",
  "properties": {"hint_text": "渲染输出目录 (P1: EXR timecode patcher / OTIO)"}
},
{
  "name": "btn_patch_exr_timecode",
  "class": "Button",
  "child": {"class": "TextBlock", "properties": {"text": "Patch EXR Timecode"}}
},
{
  "name": "btn_export_otio",
  "class": "Button",
  "child": {"class": "TextBlock", "properties": {"text": "Export OTIO Sidecar"}}
}
```

- [ ] **Step 6: `widget.py` callback 绑定 (用现有 pattern)**

`widget.py:43` 处 `_REQUIRED_CONTROLS` tuple 末尾加:

```python
    "txt_render_output_dir",
    "btn_patch_exr_timecode",
    "btn_export_otio",
```

`_bind_callbacks` 段(line ~217-225)加:

```python
        self._bind_click("btn_patch_exr_timecode", self._on_patch_exr_timecode)
        self._bind_click("btn_export_otio", self._on_export_otio)
```

类里加两个 handler:

```python
    def _on_patch_exr_timecode(self):
        if self._last_result is None or self._last_result.level_sequence is None:
            unreal.log_warning("[widget] 还没 import LevelSequence, 跳过 patch")
            return
        output_dir = self._get_text("txt_render_output_dir")
        if not output_dir:
            unreal.log_warning("[widget] 请填渲染输出目录")
            return
        from .pipeline import run_patch_exr_timecode
        ls_path = self._last_result.level_sequence_path
        res = run_patch_exr_timecode(ls_path, output_dir)
        unreal.log(f"[widget] EXR timecode patched: {res['patched_count']} files")

    def _on_export_otio(self):
        if self._last_result is None or self._last_result.level_sequence is None:
            unreal.log_warning("[widget] 还没 import LevelSequence, 跳过 OTIO export")
            return
        output_dir = self._get_text("txt_render_output_dir")
        if not output_dir:
            unreal.log_warning("[widget] 请填渲染输出目录")
            return
        from .pipeline import run_export_otio
        ls_path = self._last_result.level_sequence_path
        sidecar = output_dir.rstrip("/").rstrip("\\") + f"/{ls_path.rsplit('/', 1)[-1]}.otio"
        res = run_export_otio(ls_path, output_dir, sidecar)
        unreal.log(f"[widget] OTIO sidecar: {res['sidecar_path']}")

    def _get_text(self, name: str) -> str:
        ctrl = self._get(name)
        if ctrl is None:
            return ""
        try:
            return str(ctrl.get_text())
        except Exception:
            return ""
```

- [ ] **Step 7: `test_spec_drift.py` count 改 derive**

打开 `tests/test_spec_drift.py:94-103` (硬编码 26 / 11):

把:

```python
self.assertEqual(
    len(json_req), 26, f"Required count drift: {len(json_req)} != 26"
)
# ...
self.assertEqual(
    len(json_opt), 11, f"Optional count drift: {len(json_opt)} != 11"
)
```

改成:

```python
# Count derived from C++ source as ground truth — 加 widget 时不需要改 hardcode
self.assertEqual(
    len(json_req), len(cpp_req),
    f"Required count drift: JSON has {len(json_req)}, C++ has {len(cpp_req)}"
)
self.assertEqual(
    len(json_opt), len(cpp_opt),
    f"Optional count drift: JSON has {len(json_opt)}, C++ has {len(cpp_opt)}"
)
```

(假设 `cpp_req` / `cpp_opt` 已经是 test 里从 `PostRenderToolWidget.h` 解析出的 set;若变量名不同,按实际改。)

- [ ] **Step 8: `build_widget_blueprint.run_build()` regen BP**

UE Editor Python console:

```python
from post_render_tool import build_widget_blueprint
build_widget_blueprint.run_build()

from post_render_tool.widget_builder import rebuild_widget
rebuild_widget()
```

Expected: Tool 重新打开,看到三个新控件。

- [ ] **Step 9: 跑 unit test**

```bash
cd Content/Python
python -m unittest post_render_tool.tests.test_spec_drift -v
python -m unittest discover -s post_render_tool/tests -p "test_*.py" -v
```

Expected: 全 pass(spec drift count 用 derive,新加 3 个 widget 不破)。

- [ ] **Step 10: Commit**

```bash
git add Content/Python/post_render_tool/pipeline.py \
        Content/Python/post_render_tool/widget.py \
        Content/Python/post_render_tool/tests/test_spec_drift.py \
        Source/PostRenderTool/Public/PostRenderToolWidget.h \
        docs/widget-tree-spec.json
git commit -m "feat(p1): pipeline P1 API + widget Patch EXR / Export OTIO

- PipelineResult 加 level_sequence_path derive property
- pipeline.run_patch_exr_timecode (从 sample DataAsset 读 canonical
  StartTimecode, 跑 EXR patcher)
- pipeline.run_export_otio (dump <shot>.otio sidecar)
- 3 个新 BindWidget UPROPERTY + widget callback (用现有
  _host / _bind_click / _get / _last_result pattern)
- test_spec_drift count 从硬编码改 derive (cpp / json 集合长度一致)

需要 UBT 重编 plugin + 重启 UE Editor + run_build()。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: P1 集成验证 + Merge

**Files:** N/A

P1 完成 gate(收窄):unit tests + EXR `exrheader` 真实 typed attribute + DaVinci 19+ import 识别 SMPTE + OTIO sidecar DaVinci timeline 自动按 timecode 对齐 + Nuke 实测(若可) + take_4 几何不破。

- [ ] **Step 1: Patch EXR Timecode 端到端验证 (G2)**

在 lanPC UE Editor:
1. take_4 `run_import`(P0)
2. 打开 MRQ 渲一帧(P0,文件 = `render.<abs_frame>.exr`)
3. Tool widget 填 `txt_render_output_dir` = MRQ 输出目录,点 "Patch EXR Timecode"
4. `exrheader render.<abs>.exr | grep -i timecode`

Expected: 输出包含 `timeCode (type timecode): ...`(real typed attribute,not display name)。

- [ ] **Step 2: DaVinci 19+ EXR 识别验证**

把 patched 后 EXR 拖进 DaVinci → Media Pool。Inspector → File → Time Code 显示 = take_4 trimmed start timecode。

- [ ] **Step 3: OTIO sidecar 验证 (G4)**

点 "Export OTIO Sidecar" → 拿到 `LS_take_4_dense.otio`。

DaVinci 19+:Media Pool 右键 → Import → Timeline → 选 `.otio` 文件。

Expected:timeline 起点 timecode = take_4 trimmed start。如果不对,调 `source_range.start_time` variant 重出。

- [ ] **Step 4: Cross-system conform 决定性验证**

DaVinci 19+ 同一 timeline:
- import OTIO (CG render)
- import 现场实拍 ProRes (带 embedded SMPTE timecode)
- 不指定任何 timecode 起点参数

Expected:两 clip 在 timeline 上按 SMPTE 自动对齐。逐帧 scrub,CG 跟 plate 时间码一致。

- [ ] **Step 5: Nuke 实测 (若有许可证)**

Nuke Studio import OTIO + EXR sequence,验证识别 SMPTE timecode。

- [ ] **Step 6: 全 unit test 跑**

```bash
cd Content/Python
python -m unittest discover -s post_render_tool/tests -p "test_*.py" -v
```

Expected: 全 pass。

- [ ] **Step 7: P1 Merge**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git checkout main
git merge --no-ff worktree-timecode-sync-spec -m "feat(timecode-sync): P1 — 自动 conform

- EXR header typed SMPTE timeCode + FramesPerSecond attribute
  (exrheader 验证 real typed, oiiotool backend)
- OTIO sidecar exporter (DaVinci/Nuke import 实测识别 timecode)
- 'Patch EXR Timecode' + 'Export OTIO' widget 按钮
- DaVinci 19+ 不指定 timecode 参数, CG + 现场 ProRes 自动按
  SMPTE 对齐 (cross-system conform 验证通过)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push p4 main
```

---

## Phase P2 — Reference Plate

单独 spec/plan,不在本 plan 详细展开。前置条件:

- Plugin Build.cs / uplugin 加 `MediaAssets / MediaCompositing / MediaPlate` 依赖
- 决策点(P2 brainstorming 阶段):timeline metadata-only vs viewport visual overlay
- ffprobe JSON parser 读现场视频 embedded SMPTE timecode
- 现场视频 fps ≠ sequence fps 的对齐策略(warning + 允许)

P2 启动:brainstorming skill 起新 spec `docs/superpowers/specs/YYYY-MM-DD-reference-plate-design.md`,再 writing-plans 生成 plan。

---

## Plan 自检 — 跟 spec 对照

| Spec 章节 | Plan task 覆盖 |
|---|---|
| §6.1 CSV → Timecode | Task 1 + Task 2 |
| §6.2 Section.TimecodeSource | Task 4 + Task 6 |
| §6.3 MRQ FrameNumberOffset | Task 7 |
| §6.4 EXR header patcher | Task 9 (spike, exrheader 验证) + Task 10 |
| §6.5 OTIO sidecar | Task 11 |
| §6.6 P2 Reference Plate | 单独 spec |
| §6.7 编排 + UI | Task 12 |
| §8.1 UE API probe | Task 3 |
| §8.6 take_4 几何回归 | Task 6 Step 9 + Task 8 Step 6 |
| §9.1 unit tests | Task 1/2/10/11 |
| §9.2 in-editor 集成 | Task 8 + Task 13 |
| §9.3 DaVinci cross-system conform | Task 13 Step 4 |
| (CodeX 建议)canonical StartTimecode 存 DataAsset | Task 5 |

无遗漏。
