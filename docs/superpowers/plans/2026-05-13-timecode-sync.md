# Timecode Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Disguise CSV → UE 渲染帧 ↔ 现场带 timecode 实拍视频做逐帧 SMPTE 同步,渲出的每一帧自动 conform 回现场实拍。

**Architecture:** CSV 的 SMPTE timecode 结构化解析后,(P0) 注入 `UMovieSceneSection.TimecodeSource` 让 Sequencer UI 显示现场 timecode + MRQ 用 `FrameNumberOffset` 让文件名带 absolute CSV frame;(P1) 渲完手动一键 patch EXR header 写 SMPTE `timeCode` + 导 OTIO sidecar;(P2) 单独 spec 再做 reference plate 视觉验证。

**Tech Stack:** Python 3.11 (UE 5.7 内置)、UE C++ (UBT)、PyPI `OpenEXR` / `oiiotool` / `opentimelineio`、OpenEXR standard attributes、SMPTE drop-frame timecode、UE 5.7 MovieScene / MovieRenderQueue API。

**Spec:** `docs/superpowers/specs/2026-05-13-timecode-sync-design.md`

**Worktree:** `.claude/worktrees/timecode-sync-spec` (branch `worktree-timecode-sync-spec`)

---

## File Structure

### 新增文件
| 路径 | 职责 | Phase |
|---|---|---|
| `Content/Python/post_render_tool/timecode.py` | `Timecode` dataclass + parser + `to_frames()`/`__str__`,纯 Python | P0 |
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
| `Content/Python/post_render_tool/csv_parser.py` | `FrameData.timecode`,`CsvDenseResult.start_timecode/end_timecode/frame_rate`,等价性校验,`trim_static_padding` 同步 | P0 |
| `Source/PostRenderTool/Public/PostRenderToolBuildHelper.h` | 新 UFUNCTION `SetSectionTimecodeSource` | P0 |
| `Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp` | impl | P0 |
| `Content/Python/post_render_tool/sequence_builder.py` | Step 4a + 6a 调 `set_section_timecode_source` | P0 |
| `Content/Python/post_render_tool/ui_interface.py` | `open_movie_render_queue` 设 `FrameNumberOffset` + filename | P0 |
| `Content/Python/post_render_tool/pipeline.py` | 新增 `run_patch_exr_timecode` / `run_export_otio` | P1 |
| `Content/Python/post_render_tool/widget.py` | 5 个新 widget callback 绑定 (P1 三个 + P2 两个) | P1 |
| `Source/PostRenderTool/Public/PostRenderToolWidget.h` | 5 个新 BindWidget UPROPERTY | P1 |
| `docs/widget-tree-spec.json` | 5 个新 widget 节点 | P1 |
| `Content/Python/post_render_tool/tests/test_spec_drift.py` | drift list 加 5 个新名字 | P1 |

---

## Phase P0 — MVP (G1 / G5 / G6)

P0 交付:Sequencer UI 显示现场 timecode + MRQ 渲出的 EXR 文件名带 absolute CSV frame。

### Task 1: 加 `Timecode` dataclass + parser (纯 Python)

**Files:**
- Create: `Content/Python/post_render_tool/timecode.py`
- Test: `Content/Python/post_render_tool/tests/test_timecode.py`

- [ ] **Step 1: Write the failing test**

`Content/Python/post_render_tool/tests/test_timecode.py`:

```python
import unittest
from post_render_tool.timecode import Timecode


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
        # drop-frame 分隔符 ;
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
        # Disguise CSV 用 . 分隔最后一位 (09:44:23.22)
        tc = Timecode.parse("09:44:23.22", 24.0)
        self.assertEqual(tc.frames, 22)

    def test_str_round_trip_non_drop(self):
        tc = Timecode.parse("09:44:23:22", 24.0)
        self.assertEqual(str(tc), "09:44:23:22")

    def test_str_round_trip_drop(self):
        tc = Timecode.parse("09:44:23;22", 29.97)
        self.assertEqual(str(tc), "09:44:23;22")

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
        # NTSC drop-frame: 每分钟丢 2 帧 (整 10 分钟例外)
        # 1 分钟 = 30*60 - 2 = 1798 帧
        self.assertEqual(Timecode.parse("00:01:00;02", 29.97).to_frames(), 1798)

    def test_2997_drop_ten_minutes(self):
        # 整 10 分钟 = 30*60*10 - 2*9 = 17982 帧 (前 9 个 minute 各丢 2 帧)
        self.assertEqual(Timecode.parse("00:10:00;00", 29.97).to_frames(), 17982)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec/Content/Python
python -m unittest post_render_tool.tests.test_timecode -v
```
Expected: `ModuleNotFoundError: No module named 'post_render_tool.timecode'`

- [ ] **Step 3: Write minimal implementation**

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

# Integer-rate FPS values we accept.
_INTEGER_FPS = (24, 25, 30, 50, 60)

# Drop-frame 仅在 NTSC 系 (29.97, 59.94).
_DROP_FRAME_FPS = (29.97, 59.94)

# 分隔符: 头三段 : / 最后一段 : 或 ; 或 .
_TC_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})([:;.])(\d{2,3})$")


def _resolve_frame_rate(fps: float) -> tuple[int, int]:
    """Return (numerator, denominator) for a supported FPS."""
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
    """SMPTE Timecode. Supports 24/23.976/25/29.97/30/50/59.94/60 fps."""

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
        hh, mm, ss, sep, ff = m.groups()
        rate_num, rate_den = _resolve_frame_rate(fps)
        drop = _is_drop_frame(fps)
        # 分隔符语义检查 (drop -> ';' 强制, non-drop -> ':' / '.' 都接受)
        if drop and sep == ":":
            # Disguise 实际上 drop fps 也用 ":" 输出, 不能强制 ';' 才能 parse,
            # 但 __str__ 输出统一用 ';'.
            pass
        return cls(
            hours=int(hh), minutes=int(mm), seconds=int(ss),
            frames=int(ff), drop_frame=drop,
            rate_num=rate_num, rate_den=rate_den,
        )

    def to_frames(self) -> int:
        """Total frames since 00:00:00:00. Drop-frame aware."""
        nominal_fps = round(self.rate_num / self.rate_den)
        if not self.drop_frame:
            return ((self.hours * 60 + self.minutes) * 60 + self.seconds) * nominal_fps + self.frames

        # NTSC drop-frame 公式 (29.97 / 59.94):
        # 每分钟丢 (fps == 29.97 ? 2 : 4) 帧, 但整 10 分钟保留
        drop_count = 2 if abs(self.rate_num / self.rate_den - 29.97) < 0.01 else 4
        total_minutes = self.hours * 60 + self.minutes
        # 10-minute blocks: 整 10 分钟不丢
        full_tens = total_minutes // 10
        remainder_minutes = total_minutes - full_tens
        total_drop = drop_count * (total_minutes - full_tens)
        return (((self.hours * 60 + self.minutes) * 60 + self.seconds) * nominal_fps
                + self.frames - total_drop)

    def __str__(self) -> str:
        sep = ";" if self.drop_frame else ":"
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}{sep}{self.frames:02d}"
```

- [ ] **Step 4: Run test to verify it passes**

Run same command. Expected: all tests pass.

If `test_2997_drop_one_minute` or `test_2997_drop_ten_minutes` fails, the drop-frame math is wrong — fix `to_frames()` before commit.

- [ ] **Step 5: Commit**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec
git add Content/Python/post_render_tool/timecode.py Content/Python/post_render_tool/tests/test_timecode.py
git commit -m "feat(timecode): 加 Timecode dataclass + SMPTE parser

支持 24/23.976/25/29.97/30/50/59.94/60 fps,drop-frame 算术准确。
take_4 production 是 50 fps,本 Timecode 是后续所有 timecode
同步功能的基础。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: csv_parser 集成 Timecode + 等价性校验

**Files:**
- Modify: `Content/Python/post_render_tool/csv_parser.py` (FrameData, CsvDenseResult, parse_csv_dense, trim_static_padding)
- Create: `Content/Python/post_render_tool/tests/fixtures/sample_50fps_dense.csv`
- Create: `Content/Python/post_render_tool/tests/test_csv_parser_timecode.py`

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
import unittest
from post_render_tool.csv_parser import (
    parse_csv_dense, trim_static_padding, CsvTimecodeMismatch,
)
from post_render_tool.timecode import Timecode

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_50fps_dense.csv"
)


class TestCsvParserTimecode(unittest.TestCase):
    def test_50fps_parse_attaches_timecode_to_each_frame(self):
        result = parse_csv_dense(_FIXTURE)
        self.assertEqual(len(result.frames), 3)
        self.assertIsInstance(result.frames[0].timecode, Timecode)
        self.assertEqual(
            str(result.frames[0].timecode), "10:00:00:00"
        )
        self.assertEqual(
            str(result.frames[2].timecode), "10:00:00:02"
        )

    def test_50fps_csv_result_has_structured_start_end_and_frame_rate(self):
        result = parse_csv_dense(_FIXTURE)
        self.assertIsInstance(result.start_timecode, Timecode)
        self.assertEqual(str(result.start_timecode), "10:00:00:00")
        self.assertEqual(str(result.end_timecode), "10:00:00:02")
        self.assertEqual(result.frame_rate, (50, 1))

    def test_legacy_string_fields_still_populated(self):
        # 向后兼容: timecode_start/end: str 仍存在
        result = parse_csv_dense(_FIXTURE)
        self.assertEqual(result.timecode_start, "10:00:00:00")
        self.assertEqual(result.timecode_end, "10:00:00:02")

    def test_smpte_equivalence_check_passes_for_valid_csv(self):
        # 不抛 = OK (fixture 是合法的)
        parse_csv_dense(_FIXTURE)

    def test_smpte_equivalence_failure_raises(self):
        # 伪造一个 frame_number 和 timecode 不一致的 CSV (frame=500003 但 tc=10:00:00:02 期望 500002)
        import tempfile
        with open(_FIXTURE, "r") as f:
            content = f.read()
        broken = content.replace("10:00:00:02,500002,", "10:00:00:02,500003,")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tf:
            tf.write(broken)
            broken_path = tf.name
        try:
            with self.assertRaises(CsvTimecodeMismatch):
                parse_csv_dense(broken_path)
        finally:
            os.unlink(broken_path)

    def test_trim_static_padding_updates_structured_timecodes(self):
        # fixture 前 2 帧 head pos 一致,trim 应该把 start_timecode 推到 frame[1] (10:00:00:01)
        # 注意: fixture 末尾 tail 跟 head pos 不同 (0.6 vs 0.5),trim 默认不动
        # 改造 fixture 让 head == tail
        import tempfile
        rows = open(_FIXTURE).read().splitlines()
        # 把最后一行的 pos 改回跟首帧一致, 触发 trim
        last = rows[-1].split(",")
        last[3] = "0.5"   # offset_x 改回 0.5
        rows[-1] = ",".join(last)
        # 再加一行变动 + 一行尾部静止
        moving = list(rows[1].split(","))
        moving[0] = "10:00:00:03"
        moving[1] = "500003"
        moving[3] = "0.7"
        rows.append(",".join(moving))
        # tail 静止帧
        tail = list(moving)
        tail[0] = "10:00:00:04"
        tail[1] = "500004"
        tail[3] = "0.5"
        rows.append(",".join(tail))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tf:
            tf.write("\n".join(rows) + "\n")
            path = tf.name
        try:
            result = parse_csv_dense(path)
            trimmed = trim_static_padding(result)
            # trim 之后 start_timecode 应该指向 trimmed.frames[0]
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run:
```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec/Content/Python
python -m unittest post_render_tool.tests.test_csv_parser_timecode -v
```
Expected: ImportError on `CsvTimecodeMismatch` 或 AttributeError on `.timecode` / `.start_timecode` / `.frame_rate`.

- [ ] **Step 4: Modify csv_parser.py — add `Timecode` integration**

打开 `Content/Python/post_render_tool/csv_parser.py`,做四处修改:

**A. 文件顶部 import + 异常类**:

```python
from .timecode import Timecode

class CsvTimecodeMismatch(ValueError):
    """timestamp 列跟 frame_number 列不等价 (SMPTE drift)."""
```

**B. `FrameData` 加 `timecode` 字段** (line ~40):

```python
@dataclass
class FrameData:
    frame_number: int
    timestamp: str
    timecode: Timecode      # 新增
    # ... 现有字段
```

**C. `CsvDenseResult` 加结构化字段** (line ~78-89,保留旧 string 字段):

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
    start_timecode: Timecode       # 新
    end_timecode: Timecode         # 新
    frame_rate: Tuple[int, int]    # 新
```

**D. `parse_csv_dense` 末尾构造 result 时填充新字段 + 等价性校验** (在构造 `CsvDenseResult(...)` 之前):

```python
# 给每个 frame 解析 timecode
for f in frames:
    f.timecode = Timecode.parse(f.timestamp, fps)

# SMPTE 等价性校验
first = frames[0]
for f in frames[1:]:
    expected_delta = f.timecode.to_frames() - first.timecode.to_frames()
    actual_delta = f.frame_number - first.frame_number
    if expected_delta != actual_delta:
        raise CsvTimecodeMismatch(
            f"CSV timecode ↔ frame_number drift at frame {f.frame_number}: "
            f"timestamp={f.timestamp} expects Δ={expected_delta} frames since "
            f"start, but frame_number says Δ={actual_delta}."
        )
```

**注意**:`fps` 参数需要从 caller 传进 `parse_csv_dense`,或者从 CSV inference。当前 `parse_csv_dense(file_path: str)` 只接路径。最小侵入做法:加 `fps: float` kwarg。修改 `parse_csv_dense` signature:

```python
def parse_csv_dense(file_path: str, fps: Optional[float] = None) -> CsvDenseResult:
```

`fps=None` 时跳过 timecode 解析(向后兼容现有 caller),`fps` 给值时解析 + 校验。`pipeline.py` 在 P0 task 6 改成传 fps。

构造 result:

```python
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
    start_timecode=frames[0].timecode if fps is not None else None,
    end_timecode=frames[-1].timecode if fps is not None else None,
    frame_rate=(...) if fps is not None else None,
)
```

`fps=None` 时新字段都是 None,旧 caller 不受影响。Task 6 (sequence_builder) 之前 caller 都升级,可以把 fps 改成必填,但本 task 不做。

**E. `trim_static_padding` 同步更新** (line 388-399):

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
    # 新增:
    start_timecode=trimmed[0].timecode if result.start_timecode is not None else None,
    end_timecode=trimmed[-1].timecode if result.end_timecode is not None else None,
    frame_rate=result.frame_rate,
)
```

- [ ] **Step 5: Run tests — verify all pass + existing csv_parser tests don't regress**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec/Content/Python
python -m unittest post_render_tool.tests.test_csv_parser_timecode -v
python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -v
```
Expected: 新 test 全 pass,旧 csv_parser 测试也全 pass (`fps=None` 默认值保兼容)。

- [ ] **Step 6: Commit**

```bash
git add Content/Python/post_render_tool/csv_parser.py \
        Content/Python/post_render_tool/tests/test_csv_parser_timecode.py \
        Content/Python/post_render_tool/tests/fixtures/sample_50fps_dense.csv
git commit -m "feat(csv_parser): 集成结构化 Timecode + SMPTE 等价性校验

- FrameData.timecode (Timecode struct)
- CsvDenseResult.start_timecode/end_timecode/frame_rate (新), 旧 string 字段保留
- parse_csv_dense(fps=None) 时跳过解析 (向后兼容)
- timestamp ↔ frame_number 不等价时 fail-fast (CsvTimecodeMismatch)
- trim_static_padding 同步更新结构化 timecode

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Day-1 UE API Probe

**Files:**
- Create: `scripts/probe_ue_timecode_api.py`

- [ ] **Step 1: Write probe script**

`scripts/probe_ue_timecode_api.py`:

```python
"""Day-1: grep UE 5.7 引擎源,验证 timecode 同步要用的 Python API 暴露面.

输出 markdown 表格,记录每条调用的 file:line 证据 + 是否 Python 可见.
"""
import re
import subprocess
import sys
from pathlib import Path

UE = Path("/Users/bip.lan/AIWorkspace/vp/UnrealEngine")
TARGETS = [
    # (描述, regex 或子字符串, search root)
    ("UMovieSceneSection::TimecodeSource UPROPERTY",
     r"UPROPERTY.*\n.*FMovieSceneTimecodeSource\s+TimecodeSource",
     "Engine/Source/Runtime/MovieScene/Public/MovieSceneSection.h"),

    ("FMovieSceneTimecodeSource USTRUCT",
     r"USTRUCT.*\n.*struct\s+(MOVIESCENE_API\s+)?FMovieSceneTimecodeSource",
     "Engine/Source/Runtime/MovieScene/Public/MovieScene.h"),

    ("UMoviePipelineOutputSetting::FrameNumberOffset UPROPERTY",
     r"FrameNumberOffset",
     "Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineCore/Public/MoviePipelineOutputSetting.h"),

    ("MRQ FileNameFormat token expansion 含 frame_number",
     r"\{frame_number\}",
     "Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineCore"),

    ("UMoviePipelineEditorLibrary::create_job_from_sequence UFUNCTION",
     r"UFUNCTION.*\n.*CreateJobFromSequence",
     "Engine/Plugins/MovieScene/MovieRenderPipeline/Source/MovieRenderPipelineEditor"),
]


def grep(pattern: str, root: Path) -> list[str]:
    if root.is_file():
        cmd = ["grep", "-n", "-E", pattern, str(root)]
    else:
        cmd = ["grep", "-rn", "-E", pattern, str(root)]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
        return out.strip().splitlines()
    except subprocess.CalledProcessError:
        return []


def main():
    print("# UE 5.7 Timecode API Probe Report\n")
    print("| API | Evidence | Python visible? |")
    print("|---|---|---|")
    for desc, pattern, rel in TARGETS:
        root = UE / rel
        if not root.exists():
            print(f"| {desc} | **PATH NOT FOUND** `{rel}` | — |")
            continue
        hits = grep(pattern, root)
        if not hits:
            print(f"| {desc} | not found | UNKNOWN |")
            continue
        # show first hit only
        first = hits[0]
        # Python visibility heuristic: 邻近行有 `BlueprintCallable` / `BlueprintReadOnly` /
        # `BlueprintReadWrite` / UFUNCTION
        likely_visible = (
            "BlueprintCallable" in "\n".join(hits[:3]) or
            "BlueprintReadOnly" in "\n".join(hits[:3]) or
            "BlueprintReadWrite" in "\n".join(hits[:3]) or
            "UFUNCTION" in "\n".join(hits[:3])
        )
        verdict = "✓ likely" if likely_visible else "? check w/ help(unreal.X)"
        print(f"| {desc} | `{first}` | {verdict} |")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run probe + capture output**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec
python scripts/probe_ue_timecode_api.py | tee scripts/ue_timecode_api_probe.md
```

Expected: markdown 表格输出,所有 5 个 API 都有 `file:line` 证据。

- [ ] **Step 3: Decide fallback strategy based on probe output**

对每条标了 `? check w/ help(unreal.X)` 的 API,在 lanPC UE 5.7 Python console 跑 `help(unreal.<Class>)` 确认:

```bash
# 在 lanPC UE Editor Python console:
help(unreal.MovieSceneSection)               # 找 TimecodeSource 是否在
help(unreal.MoviePipelineOutputSetting)      # 找 frame_number_offset
```

文档结果回填到 `scripts/ue_timecode_api_probe.md` 末尾 (Python verification 章节)。

如果 `MoviePipelineOutputSetting.frame_number_offset` Python 不可见 → Task 7 走 `set_editor_property("frame_number_offset", value)` 兜底。
如果 `MovieSceneSection.TimecodeSource` 是 USTRUCT 但 Python 不可见 → Task 4/5 已经规划了 C++ wrapper,直接走 wrapper。

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_ue_timecode_api.py scripts/ue_timecode_api_probe.md
git commit -m "chore(probe): UE 5.7 timecode API 暴露面调研

day-1 grep 引擎源 + lanPC python console help() 验证, 输出
file:line 证据表。指导 Task 4/5/7 是否需要 C++ wrapper 兜底。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: C++ UFUNCTION `SetSectionTimecodeSource`

**Files:**
- Modify: `Source/PostRenderTool/Public/PostRenderToolBuildHelper.h` (加 declaration 后)
- Modify: `Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp` (加 impl)

- [ ] **Step 1: 在 `PostRenderToolBuildHelper.h` 加 forward decl + UFUNCTION declaration**

Add forward decl after line 15 (`class UMovieSceneSequence;`):

```cpp
class UMovieSceneSection;
```

Add UFUNCTION at end of `UPostRenderToolBuildHelper` class (after `CreateOrLoadCameraSamplesAsset`):

```cpp
    // ====================================================================
    // Timecode sync bridge
    // ====================================================================

    /**
     * 设置 UMovieSceneSection 上的 FMovieSceneTimecodeSource.
     *
     * UE 5.7 Section.TimecodeSource (MovieSceneSection.h:790-793) 是 USTRUCT
     * UPROPERTY, Python 直接访问 USTRUCT 字段的暴露面不稳定;走 wrapper 接平
     * 参数避免 struct 暴露问题。
     *
     * Sequencer UI 读 UMovieScene::GetEarliestTimecodeSource() 时会扫描所有
     * sections 取最小的 TimecodeSource → UI 显示对应 SMPTE timecode。
     *
     * @param Section       目标 section (Camera Cut Section / UPostRenderCameraSection 等)
     * @param Hours/Minutes/Seconds/Frames  SMPTE 四段
     * @param bDropFrame    NTSC 系 (29.97/59.94) 为 true
     * @param DeltaFrame    section 在 sequence-local frame space 的起始 offset,
     *                      通常 = section.GetInclusiveStartFrame()
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Timecode")
    static void SetSectionTimecodeSource(
        UMovieSceneSection* Section,
        int32 Hours,
        int32 Minutes,
        int32 Seconds,
        int32 Frames,
        bool bDropFrame,
        int32 DeltaFrame);
```

- [ ] **Step 2: 在 `PostRenderToolBuildHelper.cpp` 加 impl**

文件顶部 include:

```cpp
#include "MovieSceneSection.h"
#include "MovieScene.h"   // FMovieSceneTimecodeSource, FTimecode
```

文件末尾追加:

```cpp
void UPostRenderToolBuildHelper::SetSectionTimecodeSource(
    UMovieSceneSection* Section,
    int32 Hours, int32 Minutes, int32 Seconds, int32 Frames,
    bool bDropFrame,
    int32 DeltaFrame)
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
    Source.DeltaFrame = FFrameNumber(DeltaFrame);

    Section->TimecodeSource = Source;

    UE_LOG(LogTemp, Log,
        TEXT("[PostRenderTool] Section %s TimecodeSource set: "
             "%02d:%02d:%02d%s%02d Δ=%d"),
        *Section->GetName(),
        Hours, Minutes, Seconds, bDropFrame ? TEXT(";") : TEXT(":"), Frames,
        DeltaFrame);
}
```

- [ ] **Step 3: UBT 重编 plugin (lanPC)**

按 CLAUDE.md "Live Coding does NOT support UPROPERTY changes" 规则,改了 C++ UFUNCTION 必须 UBT 全量重编 + Editor 重启:

```bash
# 从 Mac 触发 lanPC 重编. 加 -WaitMutex 避免 Editor 在跑时编译失败.
ssh lanpc 'cd "/d/Program Files/Epic Games/UE_5.7" && \
  Engine/Build/BatchFiles/Build.bat PostRenderToolEditor Win64 Development \
  -Project="E:/RenderStream Projects/test_0311/test_0311.uproject" \
  -WaitMutex -FromMsBuild'
```

Expected: `Building PostRenderToolEditor for Win64 Development ... Total build time: ... 0 errors`

- [ ] **Step 4: Verify UFUNCTION visible from Python (lanPC UE Editor 启动后)**

在 lanPC UE 5.7 Editor Python console:

```python
help(unreal.PostRenderToolBuildHelper)
# 搜索输出里有没有 set_section_timecode_source(...)
```

Expected: 看到 `set_section_timecode_source` method。

- [ ] **Step 5: Commit**

```bash
git add Source/PostRenderTool/Public/PostRenderToolBuildHelper.h \
        Source/PostRenderTool/Private/PostRenderToolBuildHelper.cpp
git commit -m "feat(cpp): UFUNCTION SetSectionTimecodeSource

写 UMovieSceneSection.TimecodeSource (UE 5.7 MovieSceneSection.h:
790-793) 的 C++ wrapper, 平参数避免 USTRUCT Python 暴露问题。
配合 Python 端 sequence_builder Step 4a/6a 注入 timecode。

需要 UBT 重编 plugin + 重启 UE Editor (C++ UFUNCTION 改动)。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: sequence_builder 注入 Section TimecodeSource

**Files:**
- Modify: `Content/Python/post_render_tool/sequence_builder.py` (Step 4 后 + Step 6 后)

- [ ] **Step 1: 在 Step 4 (Camera Cut Section 创建) 后加 Step 4a**

`sequence_builder.py:117-125` 是 Step 4 创建 Camera Cut Section 的段落。在 line 125 (`camera_cut_section.set_camera_binding_id(...)`) 之后,插入 Step 4a:

```python
    # ------------------------------------------------------------------
    # Step 4a: Set Camera Cut Section.TimecodeSource (P0 timecode sync)
    # Sequencer UI 读 GetEarliestTimecodeSource() 时聚合 sections 上的
    # TimecodeSource. 让 frame 0 显示 = csv_result.start_timecode。
    # ------------------------------------------------------------------
    if csv_result.start_timecode is not None:
        tc = csv_result.start_timecode
        unreal.PostRenderToolBuildHelper.set_section_timecode_source(
            camera_cut_section,
            tc.hours, tc.minutes, tc.seconds, tc.frames,
            tc.drop_frame,
            0,  # Camera Cut Section 在 sequence-local 起点 = 0
        )
```

- [ ] **Step 2: 在 Step 6 (UPostRenderCameraSection 创建) 后加 Step 6a**

`sequence_builder.py:192-202` 是 Step 6 拿到 `section` 的段落。在 line 202 (`section.set_editor_property("sample_asset", samples_asset)`) 之后:

```python
    # ------------------------------------------------------------------
    # Step 6a: Set UPostRenderCameraSection.TimecodeSource (P0)
    # ------------------------------------------------------------------
    if csv_result.start_timecode is not None:
        tc = csv_result.start_timecode
        unreal.PostRenderToolBuildHelper.set_section_timecode_source(
            section,
            tc.hours, tc.minutes, tc.seconds, tc.frames,
            tc.drop_frame,
            0,  # UPostRenderCameraSection 也起在 0
        )
```

- [ ] **Step 3: 让 caller (pipeline.py) 传 fps 到 csv_parser**

`pipeline.py:115-129` 是 parse + trim 段。改成:

```python
    csv_result = parse_csv_dense(csv_path, fps=fps)
    # ...
    csv_result = trim_static_padding(csv_result)
```

`parse_csv_dense` 接 fps 后,csv_result.start_timecode 就被填充,sequence_builder 才能拿到 timecode。

- [ ] **Step 4: 在 lanPC UE Editor 跑 take_4 import 集成验证**

预备:确认 lanPC UE Editor 已 launch + plugin 已重编(Task 4)。

在 UE Editor Python console:

```python
import importlib, post_render_tool.pipeline as p, post_render_tool.sequence_builder as sb, post_render_tool.csv_parser as cp
importlib.reload(cp); importlib.reload(sb); importlib.reload(p)

from post_render_tool.pipeline import run_import
result = run_import(
    r"E:/RenderStream Projects/test_0311/CSV/take_4_dense.csv",
    fps=50.0,
)
```

Expected:
- Output Log 里看到 `[PostRenderTool] Section CameraCut TimecodeSource set: HH:MM:SS:FF Δ=0` (两条 — Camera Cut + UPostRenderCameraSection)
- 无异常

- [ ] **Step 5: 在 Sequencer 验证 G1**

UE Editor Outliner 找新生成的 LevelSequence 双击打开。Sequencer:
- 右上角 View Options → Show Timecode
- 时间轴 frame 0 显示 = take_4 的 trimmed start timecode (跟 CSV 第一帧 timestamp 一致)

Expected: 时间轴显示 SMPTE 而不是 0 起的相对帧号。

- [ ] **Step 6: 回归验证 (G6 fail-fast + 几何不变)**

把 take_4 CSV 复制一份,人工把某一帧的 frame_number 字段 +1 (制造 SMPTE drift)。再跑 `run_import`:

Expected: `CsvTimecodeMismatch` 在 asset mutation 之前抛出,LevelSequence 资产没被改 / 创建。

回归几何不变 — 用现有 take_4 静态帧 diff workflow 跑一次:
```
按 docs/d3-take5-static-diff-workflow.md 步骤,渲一帧 + 跟 baseline diff,
残差应在数值噪声范围 (TimecodeSource 不影响 evaluator)。
```

- [ ] **Step 7: Commit**

```bash
git add Content/Python/post_render_tool/sequence_builder.py \
        Content/Python/post_render_tool/pipeline.py
git commit -m "feat(sequence_builder): 给 Section 注入 TimecodeSource

Step 4a + 6a: Camera Cut Section + UPostRenderCameraSection 上挂
csv_result.start_timecode (trimmed)。Sequencer UI 切到 Timecode
显示时, frame 0 = 现场拍摄 SMPTE timecode。

pipeline.run_import 改成 parse_csv_dense(fps=fps), 让 csv_result
带结构化 start_timecode。

evaluator 行为不变, take_4 静态帧 diff 回归通过。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: MRQ FrameNumberOffset + filename pattern

**Files:**
- Modify: `Content/Python/post_render_tool/ui_interface.py` (`open_movie_render_queue` 函数,line 167+)

- [ ] **Step 1: 改 `open_movie_render_queue` 签名 + impl**

`ui_interface.py:167` 是 `open_movie_render_queue` 函数定义。改成:

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
                    # ---- 新增: 配 absolute CSV frame 文件名 ----
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
    absolute CSV start frame, 设给 MRQ job 的 UMoviePipelineOutputSetting:

      - FrameNumberOffset = first_csv_frame  (MRQ 把 {frame_number} 加上 offset)
      - ZeroPadFrameNumbers = 7
      - FileNameFormat = "render.{frame_number}"

    UE 5.7 MoviePipelineOutputSetting.h:101 / MoviePipelineBlueprintLibrary.cpp:1059
    确认 FrameNumberOffset 是 UPROPERTY, {frame_number} token 会加 offset。
    """
    config = job.get_configuration()
    output_setting = config.find_or_add_setting_by_class(
        unreal.MoviePipelineOutputSetting
    )

    # 从 LevelSequence binding → UPostRenderCameraSection → SampleAsset → GetFirstFrame
    first_frame = _find_first_csv_frame_from_sequence(level_sequence)
    if first_frame is None:
        unreal.log_warning(
            "[ui_interface] 未找到 UPostRenderCameraSamples DataAsset, "
            "跳过 FrameNumberOffset 配置"
        )
        return

    # set_editor_property 是 Python 暴露 fallback (probe Task 3 决定)
    output_setting.set_editor_property("frame_number_offset", int(first_frame))
    output_setting.set_editor_property("zero_pad_frame_numbers", 7)
    output_setting.set_editor_property("file_name_format", "render.{frame_number}")

    unreal.log(
        f"[ui_interface] MRQ output: FrameNumberOffset={first_frame}, "
        "FileNameFormat=render.{frame_number} (7-digit pad)"
    )


def _find_first_csv_frame_from_sequence(level_sequence) -> int | None:
    """遍历 sequence 找 UPostRenderCameraSection → SampleAsset → GetFirstFrame."""
    movie_scene = level_sequence.get_movie_scene_sequence().get_movie_scene()
    # 找所有 binding 上的 tracks 中的 UPostRenderCameraTrack
    bindings = level_sequence.get_bindings()
    for binding in bindings:
        for track in binding.get_tracks():
            if track.get_class().get_name() == "PostRenderCameraTrack":
                for section in track.get_sections():
                    sample_asset = section.get_editor_property("sample_asset")
                    if sample_asset is not None:
                        # UPostRenderCameraSamples.SourceFrameNumbers 已暴露
                        # (PostRenderCameraSamples.h:32: BlueprintReadOnly)
                        frame_numbers = sample_asset.source_frame_numbers
                        if frame_numbers:
                            return int(frame_numbers[0])
    return None
```

- [ ] **Step 2: lanPC UE Editor 验证 G5**

UE Editor Python console:

```python
import importlib, post_render_tool.ui_interface as ui
importlib.reload(ui)

# 假设 Task 5 已经 import 过 take_4
ls = unreal.EditorAssetLibrary.load_asset(
    "/Game/PostRender/take_4_dense/LS_take_4_dense"
)
ui.open_movie_render_queue(ls)
```

Expected Output Log:
```
[ui_interface] MRQ output: FrameNumberOffset=625914, FileNameFormat=render.{frame_number} (7-digit pad)
[ui_interface] 已把 LS_take_4_dense 添加到 MRQ queue (FrameNumberOffset 已配)
```

打开 MRQ (Window → Cinematics → Movie Render Queue),点 job 的 settings,看 Output > Frame Number Offset = 625914 / File Name Format = `render.{frame_number}` / Zero Pad = 7。

渲一帧:Expected 文件名 = `render.0625914.exr`。

- [ ] **Step 3: Commit**

```bash
git add Content/Python/post_render_tool/ui_interface.py
git commit -m "feat(mrq): MRQ 文件名带 absolute CSV frame number

open_movie_render_queue 现在会从 LevelSequence 关联的
UPostRenderCameraSamples.SourceFrameNumbers[0] 拿到 absolute CSV
start frame, 设给 UMoviePipelineOutputSetting:
  - FrameNumberOffset = first_csv_frame
  - ZeroPadFrameNumbers = 7
  - FileNameFormat = render.{frame_number}

渲出文件名 = render.0625914.exr (absolute CSV frame), 下游
合成/剪辑可按文件名手动对帧, 或后续 P1 EXR header timecode
自动 conform。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: P0 集成验证 + Merge

**Files:** N/A (验证 task,no code change unless regression found)

- [ ] **Step 1: 跑完整 unit test suite**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/.claude/worktrees/timecode-sync-spec/Content/Python
python -m unittest discover -s post_render_tool/tests -p "test_*.py" -v
```

Expected: 全 pass。

- [ ] **Step 2: lanPC UE Editor 完整 take_4 import + Sequencer G1 验证**

UE Editor Python console:
```python
import importlib
for mod in ["post_render_tool.timecode", "post_render_tool.csv_parser",
            "post_render_tool.sequence_builder", "post_render_tool.ui_interface",
            "post_render_tool.pipeline"]:
    importlib.reload(__import__(mod, fromlist=["_"]))

from post_render_tool.pipeline import run_import
result = run_import(r"E:/RenderStream Projects/test_0311/CSV/take_4_dense.csv", fps=50.0)
```

打开生成的 LevelSequence,View → Show Timecode:**frame 0 显示 = take_4 trimmed start timecode**。

- [ ] **Step 3: MRQ G5 验证**

`ui.open_movie_render_queue(level_sequence)`,打开 MRQ,渲 1 帧 EXR。

文件管理器看 output dir:**文件名 = `render.<absolute_csv_frame>.exr`**(零填 7 位)。

- [ ] **Step 4: G6 fail-fast 验证**

手工改一份 take_4 CSV 让某一帧 frame_number 跟 timestamp 不一致,跑 `run_import`:

Expected: `CsvTimecodeMismatch` 抛出,Content Browser 里没有新的 LevelSequence / DataAsset 资产。

- [ ] **Step 5: 几何回归 (take_4 静态帧 diff)**

按 `docs/d3-take5-static-diff-workflow.md` 跑 take_4 静态帧 diff。残差应跟最近一次 baseline (commit `5f2fa2b` 之前的 take_4 production diff) 差不多,数值噪声级别。

- [ ] **Step 6: P0 Merge**

P0 全部验证通过 → merge 到 main:

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git checkout main
git merge --no-ff worktree-timecode-sync-spec -m "feat(timecode-sync): P0 — MVP

Sequencer UI 显示现场 SMPTE timecode (G1)
MRQ 输出文件名带 absolute CSV frame (G5)
CSV timestamp ↔ frame_number 等价性 fail-fast (G6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

# 按 CLAUDE.md '--no-ff merges 不触发 post-commit hook' 规则手动 push p4
git push p4 main
```

---

## Phase P1 — 自动 conform (G2 / G4)

### Task 8: EXR Writer Spike — 三 backend 选哪个

**Files:**
- Create: `scripts/exr_timecode_spike.py`
- Create: `scripts/exr_timecode_spike_report.md`

- [ ] **Step 1: 准备 spike fixture**

用 P0 跑出来的一帧 MRQ EXR (e.g. `render.0625914.exr`),复制三份:
```bash
cd scripts
cp /path/to/render.0625914.exr spike_input_a.exr
cp /path/to/render.0625914.exr spike_input_b.exr
cp /path/to/render.0625914.exr spike_input_c.exr
```

- [ ] **Step 2: Spike (a) PyPI OpenEXR**

`scripts/exr_timecode_spike.py`:

```python
"""Spike: 三种 EXR header timecode writer 哪个能保留 MRQ 写的所有 attributes."""
import subprocess
import sys


def spike_a_openexr_python(path: str, hh: int, mm: int, ss: int, ff: int, drop: bool):
    """候选 (a): PyPI OpenEXR 包."""
    import OpenEXR, Imath
    # ...具体 API 写 timeCode + framesPerSecond 属性
    # 略 — 实施时按 OpenEXR python doc 写
    # 关键:保留原 channels / compression / multipart
    raise NotImplementedError("fill in based on OpenEXR python bindings version")


def spike_b_oiiotool(path: str, hh: int, mm: int, ss: int, ff: int, drop: bool, fps: int):
    """候选 (b): oiiotool CLI."""
    tc_str = f"{hh:02d}:{mm:02d}:{ss:02d}{':;'[drop]}{ff:02d}"
    subprocess.check_call([
        "oiiotool", path,
        "--attrib", "smpte:TimeCode", tc_str,
        "--attrib:type=rational", "FramesPerSecond", f"{fps}/1",
        "-o", path,
    ])


def spike_c_mrq_output_pass():
    """候选 (c): UMoviePipelineImagePassBase 子类。
    无法在 spike 阶段单独验证,只能后续真做 plugin C++ side。"""
    pass


if __name__ == "__main__":
    backend = sys.argv[1]   # "a" or "b"
    path = sys.argv[2]
    if backend == "a":
        spike_a_openexr_python(path, 9, 44, 23, 22, False)
    elif backend == "b":
        spike_b_oiiotool(path, 9, 44, 23, 22, False, 50)
    print(f"spike-{backend} done for {path}")
```

- [ ] **Step 3: 跑 spike + 对比 EXR header**

```bash
# Install backends
pip install OpenEXR Imath
brew install openimageio  # macOS; lanPC 用 choco install / scoop

# 运行
python scripts/exr_timecode_spike.py a scripts/spike_input_a.exr 2>&1 | tee scripts/spike_a.log
python scripts/exr_timecode_spike.py b scripts/spike_input_b.exr 2>&1 | tee scripts/spike_b.log

# 对比 header
oiiotool --info -v scripts/spike_input_a.exr > scripts/header_a.txt
oiiotool --info -v scripts/spike_input_b.exr > scripts/header_b.txt
oiiotool --info -v scripts/spike_input_c.exr > scripts/header_baseline.txt   # 未修改的 baseline

diff scripts/header_a.txt scripts/header_baseline.txt > scripts/diff_a.txt
diff scripts/header_b.txt scripts/header_baseline.txt > scripts/diff_b.txt
```

- [ ] **Step 4: 写 spike report 选 backend**

`scripts/exr_timecode_spike_report.md`,记录:
- (a) PyPI OpenEXR:有没有丢 channels / compression / multipart?是否能写 SMPTE timeCode?
- (b) oiiotool:同上
- 决策:哪个 backend 进 Task 9 实现

如果两个都有缺陷,补充候选 (c) — UE 端写 `UMoviePipelineImagePassBase`。在 plan 这里加 follow-up task。

- [ ] **Step 5: Commit**

```bash
git add scripts/exr_timecode_spike.py scripts/exr_timecode_spike_report.md \
        scripts/spike_*.log scripts/header_*.txt scripts/diff_*.txt
git commit -m "chore(spike): EXR header timecode writer backend 选型

跑 PyPI OpenEXR vs oiiotool 对真实 MRQ EXR 加 timeCode +
framesPerSecond attributes, 对比 channels / compression /
multipart 保留情况, 选定 Task 9 用 <backend>。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: `exr_timecode_writer.py` 实现 + unit test

**Files:**
- Create: `Content/Python/post_render_tool/exr_timecode_writer.py`
- Create: `Content/Python/post_render_tool/tests/test_exr_timecode_writer.py`

**前置**:Task 8 spike 选出 backend (假设是 oiiotool)。

- [ ] **Step 1: Write failing test**

`Content/Python/post_render_tool/tests/test_exr_timecode_writer.py`:

```python
"""离线 EXR patcher 测试. 不依赖 unreal."""
import os
import shutil
import subprocess
import tempfile
import unittest

from post_render_tool.exr_timecode_writer import patch_exr_timecode_in_dir
from post_render_tool.timecode import Timecode


def _gen_test_exr(path: str) -> None:
    """用 oiiotool 生成一张灰 EXR (4x4 像素)."""
    subprocess.check_call([
        "oiiotool",
        "--create", "4x4", "3",
        "--fill:color=0.5,0.5,0.5", "4x4",
        "-o", path,
    ])


def _read_attribute(path: str, attr: str) -> str:
    """oiiotool --info -v 读单个 attribute."""
    out = subprocess.check_output(
        ["oiiotool", "--info", "-v", path], text=True, stderr=subprocess.STDOUT
    )
    for line in out.splitlines():
        if attr in line:
            return line.strip()
    return ""


class TestPatchExrTimecode(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # 生成 3 帧
        for i in range(3):
            _gen_test_exr(os.path.join(self.tmpdir, f"render.{625914 + i:07d}.exr"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_50fps_patch_writes_timecode_attribute(self):
        n = patch_exr_timecode_in_dir(
            self.tmpdir,
            "render.{frame:07d}.exr",
            start_csv_frame=625914,
            start_timecode=Timecode.parse("10:00:00:00", 50.0),
            fps=50.0,
        )
        self.assertEqual(n, 3)
        first = os.path.join(self.tmpdir, "render.0625914.exr")
        info = _read_attribute(first, "smpte:TimeCode")
        self.assertIn("10:00:00", info)
        info_fps = _read_attribute(first, "FramesPerSecond")
        self.assertIn("50", info_fps)

    def test_50fps_increments_per_frame(self):
        patch_exr_timecode_in_dir(
            self.tmpdir,
            "render.{frame:07d}.exr",
            start_csv_frame=625914,
            start_timecode=Timecode.parse("10:00:00:00", 50.0),
            fps=50.0,
        )
        # frame 625914 -> 10:00:00:00
        # frame 625915 -> 10:00:00:01
        # frame 625916 -> 10:00:00:02
        for offset, expected in enumerate(["00", "01", "02"]):
            path = os.path.join(self.tmpdir, f"render.{625914 + offset:07d}.exr")
            info = _read_attribute(path, "smpte:TimeCode")
            self.assertIn(f"10:00:00:{expected}", info)

    def test_nonexistent_dir_returns_zero(self):
        n = patch_exr_timecode_in_dir(
            "/no/such/dir", "render.{frame:07d}.exr",
            625914, Timecode.parse("10:00:00:00", 50.0), 50.0,
        )
        self.assertEqual(n, 0)


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
"""EXR header SMPTE timecode patcher. Offline (post-render).

Backend: 选定于 Task 8 spike. 当前实现走 oiiotool CLI:
- 写 smpte:TimeCode (HH:MM:SS:FF or HH:MM:SS;FF) attribute
- 写 FramesPerSecond rational attribute
- 保留 MRQ 写的 channels / compression / multipart 等所有 attributes
  (oiiotool 默认 --o 时 carry over all metadata)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .timecode import Timecode


def _ensure_oiiotool() -> None:
    if shutil.which("oiiotool") is None:
        raise RuntimeError(
            "oiiotool not on PATH. 安装 OpenImageIO: "
            "macOS=`brew install openimageio`, Windows=`scoop install openimageio`."
        )


def _frame_to_timecode(start: Timecode, offset_frames: int) -> Timecode:
    """从 start 起 offset_frames 帧后的 Timecode."""
    total = start.to_frames() + offset_frames
    # 这里需要反向把 total frames → HH:MM:SS:FF
    # drop-frame 需要反向处理
    nominal_fps = round(start.rate_num / start.rate_den)
    if not start.drop_frame:
        ff = total % nominal_fps
        total_seconds = total // nominal_fps
        ss = total_seconds % 60
        mm = (total_seconds // 60) % 60
        hh = total_seconds // 3600
        return Timecode(
            hours=hh, minutes=mm, seconds=ss, frames=ff,
            drop_frame=False, rate_num=start.rate_num, rate_den=start.rate_den,
        )
    # NTSC drop-frame 反向: 每分钟补 drop_count 帧, 整 10 分钟不补
    drop_count = 2 if abs(start.rate_num / start.rate_den - 29.97) < 0.01 else 4
    frames_per_minute = nominal_fps * 60 - drop_count
    frames_per_10min = nominal_fps * 60 * 10 - drop_count * 9
    d = total // frames_per_10min
    m = total - d * frames_per_10min
    if m > drop_count:
        m = m + drop_count * ((m - drop_count) // frames_per_minute)
    total_with_drops = d * (10 * frames_per_minute + drop_count * 9) + m  # rough
    # 用更直接的算法: 反向找 (hh, mm, ss, ff) 使得 to_frames == total
    # 实施时可以 binary search 或直接 brute force; 这里先 placeholder, 后续优化
    raise NotImplementedError("drop-frame 反向算法在 Task 9 step 4 完成")


def patch_exr_timecode_in_dir(
    output_dir: str,
    filename_pattern: str,
    start_csv_frame: int,
    start_timecode: Timecode,
    fps: float,
) -> int:
    """Patch SMPTE timeCode + FramesPerSecond attribute 到目录内所有匹配的 EXR.

    filename_pattern 是 Python format string, 如 "render.{frame:07d}.exr".
    根据 filename 解出 absolute frame, 跟 start_csv_frame 减出 offset, 计算
    timecode 写入 header.

    Returns: 处理成功的文件数.
    """
    out_path = Path(output_dir)
    if not out_path.is_dir():
        return 0

    _ensure_oiiotool()

    # 把 filename_pattern 转成 regex 提取 frame_number
    # "render.{frame:07d}.exr" → regex "render\.(\d{7})\.exr"
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

        subprocess.check_call([
            "oiiotool", str(file),
            "--attrib", "smpte:TimeCode", tc_str,
            "--attrib:type=rational", "FramesPerSecond", f"{nominal_fps}/1",
            "-o", str(file),
        ])
        processed += 1

    return processed
```

- [ ] **Step 4: 实现 drop-frame 反向算法**

填 `_frame_to_timecode` 的 drop-frame 分支。可以用 binary search 或直接公式;先用 binary search:

```python
def _frame_to_timecode(start: Timecode, offset_frames: int) -> Timecode:
    total = start.to_frames() + offset_frames
    nominal_fps = round(start.rate_num / start.rate_den)
    if not start.drop_frame:
        ff = total % nominal_fps
        total_seconds = total // nominal_fps
        ss = total_seconds % 60
        mm = (total_seconds // 60) % 60
        hh = total_seconds // 3600
        return Timecode(
            hours=hh, minutes=mm, seconds=ss, frames=ff,
            drop_frame=False, rate_num=start.rate_num, rate_den=start.rate_den,
        )

    # Drop-frame: binary-search-style direct reverse
    drop_count = 2 if nominal_fps == 30 else 4
    fps_int = nominal_fps  # 30 or 60 nominally; SMPTE timecode 字段用 nominal
    # 每 10 分钟有 fps_int * 60 * 10 - drop_count * 9 帧
    frames_per_10min = fps_int * 600 - drop_count * 9
    # 每分钟 (非整 10) 有 fps_int * 60 - drop_count 帧
    frames_per_minute_minus = fps_int * 60 - drop_count

    d = total // frames_per_10min
    m = total - d * frames_per_10min
    # m 是 10 分钟块内的剩余帧数。第一分钟有 fps_int*60 帧 (整 10 分钟那分钟),
    # 后续 9 分钟每分钟 fps_int*60 - drop_count 帧。
    if m < fps_int * 60:
        # 在第一分钟内 (整 10 分钟那一分钟, 不丢帧)
        minute_in_block = 0
        m_remaining = m
    else:
        m_remaining = m - fps_int * 60
        minute_in_block = 1 + m_remaining // frames_per_minute_minus
        m_remaining = m_remaining % frames_per_minute_minus
        # 后续分钟开头丢 drop_count 帧 (i.e. timecode 跳过 drop_count)
        m_remaining += drop_count

    total_minutes = d * 10 + minute_in_block
    hh = total_minutes // 60
    mm = total_minutes % 60
    ss = m_remaining // fps_int
    ff = m_remaining % fps_int

    return Timecode(
        hours=hh, minutes=mm, seconds=ss, frames=ff,
        drop_frame=True, rate_num=start.rate_num, rate_den=start.rate_den,
    )
```

- [ ] **Step 5: Run tests — verify pass**

```bash
python -m unittest post_render_tool.tests.test_exr_timecode_writer -v
```
Expected: 全 pass。

如果 drop-frame 反向算法 round-trip 有 bug,加 round-trip test:

```python
def test_to_frames_round_trip_drop(self):
    for total in [0, 1797, 1798, 17981, 17982, 17983]:
        # 用 start=00:00:00;00 + offset=total 反向得 tc, 再 to_frames 应该 = total
        from post_render_tool.exr_timecode_writer import _frame_to_timecode
        start = Timecode.parse("00:00:00;00", 29.97)
        tc = _frame_to_timecode(start, total)
        self.assertEqual(tc.to_frames(), total, f"round-trip failed at {total}")
```

- [ ] **Step 6: Commit**

```bash
git add Content/Python/post_render_tool/exr_timecode_writer.py \
        Content/Python/post_render_tool/tests/test_exr_timecode_writer.py
git commit -m "feat(exr): SMPTE timecode patcher (oiiotool backend)

patch_exr_timecode_in_dir 给目录内所有匹配 filename_pattern 的
EXR 文件 header 写 smpte:TimeCode + FramesPerSecond 属性, 保留
MRQ 原有 channels / compression / multipart。

drop-frame round-trip 数学 (29.97 / 59.94 NTSC) 单元测试覆盖。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `otio_export.py` 实现 + unit test

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
            # global_start_time 应该 = 10:00:00:00 @ 50fps
            gst = tl.global_start_time
            self.assertAlmostEqual(gst.rate, 50.0, places=3)
            # to_timecode 应该回 "10:00:00:00"
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
Expected: ImportError on `export_sidecar`.

- [ ] **Step 3: Implement `otio_export.py`**

```python
"""OTIO sidecar exporter. Pure Python, no unreal dependency."""
from __future__ import annotations

import opentimelineio as otio

from .timecode import Timecode


def export_sidecar(
    sidecar_path: str,
    shot_name: str,
    cg_render_dir: str,
    cg_filename_pattern: str,    # e.g. "render.{frame:07d}.exr"
    start_csv_frame: int,
    frame_count: int,
    start_timecode: Timecode,
    fps: float,
) -> None:
    """Dump <shot>.otio sidecar.

    Timeline 结构:
      Timeline (rate=fps, global_start_time=start_timecode 对应 RationalTime)
       └─ Track "CG Render"
            └─ Clip
                  media_reference = ImageSequenceReference
                  source_range = TimeRange(0, frame_count)  # local 时间
    """
    # 解析 filename_pattern -> name_prefix / name_suffix / frame_zero_padding
    # e.g. "render.{frame:07d}.exr" -> prefix="render.", suffix=".exr", padding=7
    import re
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
Expected: 全 pass。

- [ ] **Step 5: DaVinci import 实测**

把 sidecar 文件传到 DaVinci 19+ 跑一遍 import,看 timeline 自动识别 SMPTE timecode 起点是否 = `10:00:00:00`。

(此步骤无 automated test,在 P1 集成验证 Task 12 中跑;若 import 后 timecode 起点错,回到 `source_range` 选另一种 variant — 把 `source_range.start_time` 改成 `RationalTime(start_csv_frame, fps)` 而非 `RationalTime(0, fps)`,再 import 验证。)

- [ ] **Step 6: Commit**

```bash
git add Content/Python/post_render_tool/otio_export.py \
        Content/Python/post_render_tool/tests/test_otio_export.py
git commit -m "feat(otio): OTIO sidecar exporter

export_sidecar 输出 .otio 文件: Timeline + CG Render track + Clip
with ImageSequenceReference (start_frame=absolute_csv_frame).
DaVinci 19+ / Nuke Studio import 后能自动按 SMPTE timecode 对齐。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: pipeline.py 加 P1 API + widget UI

**Files:**
- Modify: `Content/Python/post_render_tool/pipeline.py` (新增 `run_patch_exr_timecode`, `run_export_otio`)
- Modify: `Content/Python/post_render_tool/widget.py` (callback 绑定)
- Modify: `Source/PostRenderTool/Public/PostRenderToolWidget.h` (3 个 BindWidget UPROPERTY)
- Modify: `docs/widget-tree-spec.json` (3 个 widget 节点)
- Modify: `Content/Python/post_render_tool/tests/test_spec_drift.py` (drift list 加 3 个名字)

- [ ] **Step 1: pipeline.py 加两个新公开函数**

文件末尾追加:

```python
def run_patch_exr_timecode(
    level_sequence_asset_path: str,
    output_dir: str,
) -> dict:
    """从 LevelSequence 关联的 sample DataAsset 读 absolute first frame + start tc,
    给 output_dir 里所有匹配 EXR 文件补 SMPTE timecode header。"""
    import unreal
    from .exr_timecode_writer import patch_exr_timecode_in_dir
    from .timecode import Timecode

    ls = unreal.EditorAssetLibrary.load_asset(level_sequence_asset_path)
    if ls is None:
        raise RuntimeError(f"LevelSequence not found: {level_sequence_asset_path}")

    # 找 UPostRenderCameraSamples DataAsset (跟 ls 同 package 路径 + "_Samples" 后缀)
    samples_path = level_sequence_asset_path + "_Samples"
    samples = unreal.EditorAssetLibrary.load_asset(samples_path)
    if samples is None:
        raise RuntimeError(f"Sample DataAsset not found: {samples_path}")

    first_frame = int(samples.source_frame_numbers[0])
    fps_num = samples.frame_rate_numerator
    fps_den = samples.frame_rate_denominator
    fps = fps_num / fps_den

    # 从 first frame 的 CSV timecode 复原 — sample DataAsset 没存 timecode,
    # 但 LevelSequence Section.TimecodeSource 存了; 走 helper 读出。
    start_tc = _read_start_timecode_from_sequence(ls, fps)

    n = patch_exr_timecode_in_dir(
        output_dir=output_dir,
        filename_pattern="render.{frame:07d}.exr",
        start_csv_frame=first_frame,
        start_timecode=start_tc,
        fps=fps,
    )
    return {"patched_count": n, "output_dir": output_dir}


def _read_start_timecode_from_sequence(level_sequence, fps: float):
    """从 Sequence 任意 section.TimecodeSource 读 start tc."""
    import unreal
    from .timecode import Timecode
    for binding in level_sequence.get_bindings():
        for track in binding.get_tracks():
            for section in track.get_sections():
                tc_source = section.get_editor_property("timecode_source")
                if tc_source is None:
                    continue
                tc = tc_source.timecode   # FTimecode struct
                hh = tc.hours
                mm = tc.minutes
                ss = tc.seconds
                ff = tc.frames
                drop = tc.bdrop_frame_format
                sep = ";" if drop else ":"
                return Timecode.parse(f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}", fps)
    raise RuntimeError("No section with TimecodeSource found in sequence")


def run_export_otio(
    level_sequence_asset_path: str,
    output_dir: str,
    sidecar_path: str,
) -> dict:
    """给定 LevelSequence + 渲染输出目录, dump <shot>.otio sidecar."""
    import unreal
    from .otio_export import export_sidecar

    ls = unreal.EditorAssetLibrary.load_asset(level_sequence_asset_path)
    samples_path = level_sequence_asset_path + "_Samples"
    samples = unreal.EditorAssetLibrary.load_asset(samples_path)

    first_frame = int(samples.source_frame_numbers[0])
    frame_count = len(samples.source_frame_numbers)
    fps = samples.frame_rate_numerator / samples.frame_rate_denominator
    start_tc = _read_start_timecode_from_sequence(ls, fps)

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

- [ ] **Step 2: `PostRenderToolWidget.h` 加 3 个新 BindWidget UPROPERTY**

class 末尾加(参照现有 `btn_browse` 的写法):

```cpp
    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    class UEditableTextBox* txt_render_output_dir;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    class UButton* btn_patch_exr_timecode;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    class UButton* btn_export_otio;
```

按 CLAUDE.md "Live Coding does NOT support UPROPERTY changes",改完需 UBT 重编 + Editor 重启。

- [ ] **Step 3: UBT 重编 + Editor 重启**

```bash
ssh lanpc 'cd "/d/Program Files/Epic Games/UE_5.7" && \
  Engine/Build/BatchFiles/Build.bat PostRenderToolEditor Win64 Development \
  -Project="E:/RenderStream Projects/test_0311/test_0311.uproject" \
  -WaitMutex -FromMsBuild'
```

- [ ] **Step 4: `widget-tree-spec.json` 加 3 个 widget 节点**

按现有 `btn_browse` / `txt_path` 结构(看 spec 文件 schema doc:`docs/widget-tree-spec.schema.md`),在合适分组下添加:

```json
{
  "name": "txt_render_output_dir",
  "class": "EditableTextBox",
  "properties": {"hint_text": "渲染输出目录 (P1: EXR timecode patcher)"}
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

- [ ] **Step 5: `widget.py` callback 绑定**

`_REQUIRED_CONTROLS` 末尾加三个名字。在 init 段加 callback:

```python
self.host.btn_patch_exr_timecode.on_clicked.add_callable(self._on_patch_exr_timecode)
self.host.btn_export_otio.on_clicked.add_callable(self._on_export_otio)

def _on_patch_exr_timecode(self):
    from .pipeline import run_patch_exr_timecode
    output_dir = self.host.txt_render_output_dir.get_text()
    ls_path = self._last_imported_sequence_path   # 需要在 import 后记录
    res = run_patch_exr_timecode(ls_path, str(output_dir))
    unreal.log(f"[widget] EXR timecode patched: {res['patched_count']} files")

def _on_export_otio(self):
    from .pipeline import run_export_otio
    output_dir = self.host.txt_render_output_dir.get_text()
    ls_path = self._last_imported_sequence_path
    sidecar = str(output_dir).rstrip("/") + f"/{ls_path.rsplit('/',1)[-1]}.otio"
    res = run_export_otio(ls_path, str(output_dir), sidecar)
    unreal.log(f"[widget] OTIO sidecar: {res['sidecar_path']}")
```

`run_import` 调用后记录 `self._last_imported_sequence_path = result.level_sequence_path`(看 `PipelineResult` schema 决定字段名,从 `pipeline.py` 找)。

- [ ] **Step 6: `test_spec_drift.py` 加 3 个新名字**

打开 `tests/test_spec_drift.py`,找到 `_REQUIRED_CONTROLS` 对应 list,在末尾加:

```python
"txt_render_output_dir",
"btn_patch_exr_timecode",
"btn_export_otio",
```

跑测试:

```bash
python -m unittest post_render_tool.tests.test_spec_drift -v
```

Expected: pass(三处名字一致)。

- [ ] **Step 7: `build_widget_blueprint.run_build()` regen BP**

UE Editor Python console:

```python
from post_render_tool import build_widget_blueprint
build_widget_blueprint.run_build()

from post_render_tool.widget_builder import rebuild_widget
rebuild_widget()
```

Expected: Tool 重新打开,看到三个新控件。

- [ ] **Step 8: Commit**

```bash
git add Content/Python/post_render_tool/pipeline.py \
        Content/Python/post_render_tool/widget.py \
        Content/Python/post_render_tool/tests/test_spec_drift.py \
        Source/PostRenderTool/Public/PostRenderToolWidget.h \
        docs/widget-tree-spec.json
git commit -m "feat(p1): pipeline + UI 加 Patch EXR Timecode / Export OTIO 按钮

- pipeline.run_patch_exr_timecode (从 sequence section.TimecodeSource
  反读 start tc, 跑 EXR patcher)
- pipeline.run_export_otio (dump <shot>.otio sidecar)
- 3 个新 BindWidget UPROPERTY + widget callback + JSON spec 同步
- test_spec_drift 兜底名字一致性

需要 UBT 重编 plugin + 重启 UE Editor + run_build()。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: P1 集成验证 + Merge

**Files:** N/A (验证 task)

- [ ] **Step 1: Patch EXR Timecode 端到端验证 (G2)**

在 lanPC UE Editor:
1. 跑 take_4 `run_import`(P0 流程)
2. 打开 MRQ,渲一帧(P0 ok,文件 = `render.0625914.exr`)
3. 在 Tool widget 填写 `txt_render_output_dir` = MRQ 输出目录,点 "Patch EXR Timecode"
4. 文件管理器找输出 EXR,`oiiotool --info -v render.0625914.exr`

Expected: header 出现 `smpte:TimeCode: "10:00:00:00"`(或 take_4 trimmed start),`FramesPerSecond: 50/1`,其他 channels / compression / multipart 字段不变。

- [ ] **Step 2: OTIO sidecar 验证 (G4)**

点 "Export OTIO Sidecar",拿到 `LS_take_4_dense.otio` 文件。

在 DaVinci 19+:
- Media Pool 右键 → Import → Timeline → 选 `.otio` 文件
- 检查 timeline 起点 timecode = `10:00:00:00`(或 take_4 trimmed start)
- 时间轴上 clip 起止帧符合 frame_count

如果 timecode 不对,回到 `otio_export.py` 调整 `source_range.start_time`(从 `RationalTime(0, fps)` 改成 `RationalTime(start_csv_frame, fps)`),重跑。

- [ ] **Step 3: Cross-system conform 验证(决定性接受标准)**

DaVinci 19+ 同一 timeline:
- import OTIO sidecar(CG render)
- import 现场实拍 ProRes(带 embedded SMPTE timecode)
- **不指定**任何 timecode 起点参数

Expected: 两条 clip 在 timeline 上按 SMPTE timecode **自动对齐**,逐帧 scrub 时 CG 跟 plate 时间码一致。

- [ ] **Step 4: 单元测试全跑**

```bash
cd Content/Python
python -m unittest discover -s post_render_tool/tests -p "test_*.py" -v
```

Expected: 全 pass。

- [ ] **Step 5: P1 Merge**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git checkout main
git merge --no-ff worktree-timecode-sync-spec -m "feat(timecode-sync): P1 — 自动 conform

- EXR header SMPTE timeCode + framesPerSecond patcher (oiiotool)
- OTIO sidecar exporter
- 'Patch EXR Timecode' + 'Export OTIO' widget 按钮
- DaVinci 19+ 不指定 timecode 参数, CG + 现场 ProRes 自动按
  SMPTE 对齐 (cross-system conform 验证通过)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push p4 main
```

---

## Phase P2 — Reference Plate(视觉验证)

P2 单独 spec/plan,不在本 plan 详细展开。前置条件:

- Plugin Build.cs / uplugin 加 `MediaAssets / MediaCompositing / MediaPlate` 依赖
- 决策点(P2 brainstorming 阶段处理):timeline metadata-only vs viewport visual overlay,决定走 `MovieSceneMediaTrack` 还是 `MediaPlate Actor + Composure`
- ffprobe JSON parser 读现场视频 embedded SMPTE timecode
- 现场视频 fps ≠ sequence fps 的对齐策略(warning + 允许,见 spec §8.3)

P2 启动:用 brainstorming skill 起新 spec `docs/superpowers/specs/YYYY-MM-DD-reference-plate-design.md`,再 writing-plans 生成 plan。

---

## 验证不在主流程的几个边角

### 跨午夜 timecode

跨 00:00:00:00 边界(`23:59:58:23` → `00:00:00:01`)在 `to_frames()` 内部不会出问题(纯加减),但 `_frame_to_timecode` 反向时 hh 可能 ≥ 24。SMPTE 习惯 mod 24,本 spec 允许 ≥ 24 + 加 warning(spec §8.2)。

Task 1 + Task 9 unit test 已覆盖单一时间内,跨午夜需单独加 fixture:

```python
def test_cross_midnight(self):
    start = Timecode.parse("23:59:58:23", 24.0)
    from post_render_tool.exr_timecode_writer import _frame_to_timecode
    after_2_seconds = _frame_to_timecode(start, 48)
    # 24:00:00:23 (本 spec 不 mod 24, 允许 hh=24)
    self.assertEqual(after_2_seconds.hours, 24)
```

可在 Task 1 / Task 9 commit 前补上;不影响 plan 主线。

---

## Plan 自检 — 跟 spec 对照

| Spec 章节 | Plan task 覆盖 |
|---|---|
| §6.1 CSV → Timecode | Task 1 + Task 2 |
| §6.2 Section.TimecodeSource | Task 4 + Task 5 |
| §6.3 MRQ FrameNumberOffset | Task 6 |
| §6.4 EXR header patcher | Task 8 (spike) + Task 9 |
| §6.5 OTIO sidecar | Task 10 |
| §6.6 P2 Reference Plate | 标注单独 spec,本 plan 不展开 |
| §6.7 编排 + UI | Task 11 |
| §8.1 UE API probe | Task 3 |
| §8.6 take_4 几何回归 | Task 7 Step 5 |
| §9.1 unit tests | Task 1/2/9/10 都有 |
| §9.2 in-editor 集成 | Task 7 + Task 12 |
| §9.3 DaVinci conform | Task 12 Step 3 |

无遗漏。
