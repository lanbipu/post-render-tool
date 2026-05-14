"""csv_parser timecode integration tests.

All structured-timecode tests pass `fps=...` explicitly. `fps=None` (default)
keeps the legacy behavior so the rest of the codebase doesn't break.
"""
import io
import os
import tempfile
import unittest

from post_render_tool.csv_parser import (
    parse_csv_dense, trim_static_padding,
    CsvParseError, CsvTimecodeMismatch,
)
from post_render_tool.timecode import Timecode


def _write_csv(rows: list[str]) -> str:
    """Write CSV rows to a temp file and return path. Caller deletes."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tf:
        tf.write("\n".join(rows) + "\n")
        return tf.name


_HEADER_50FPS = open(os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_50fps_dense.csv"
)).readline().strip()


_FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_50fps_dense.csv"
)


class TestCsvParserTimecodeWithFps(unittest.TestCase):
    """When fps is given, structured timecode fields are populated."""

    def test_50fps_each_frame_has_timecode(self):
        result = parse_csv_dense(_FIXTURE, fps=50.0)
        self.assertEqual(len(result.frames), 3)
        self.assertIsInstance(result.frames[0].timecode, Timecode)
        self.assertEqual(str(result.frames[0].timecode), "10:00:00:00")
        self.assertEqual(str(result.frames[1].timecode), "10:00:00:01")
        self.assertEqual(str(result.frames[2].timecode), "10:00:00:02")

    def test_50fps_result_has_start_end_and_rate(self):
        result = parse_csv_dense(_FIXTURE, fps=50.0)
        self.assertIsInstance(result.start_timecode, Timecode)
        self.assertEqual(str(result.start_timecode), "10:00:00:00")
        self.assertEqual(str(result.end_timecode), "10:00:00:02")
        self.assertEqual(result.frame_rate, (50, 1))

    def test_legacy_string_fields_still_populated(self):
        result = parse_csv_dense(_FIXTURE, fps=50.0)
        self.assertEqual(result.timecode_start, "10:00:00:00")
        self.assertEqual(result.timecode_end, "10:00:00:02")

    def test_smpte_equivalence_failure_raises_when_strict(self):
        # Inject a frame where frame_number drifts away from the timestamp.
        # strict_timecode=True (opt-in) is required for fail-fast; default mode
        # tolerates this (Disguise dual-stream exports often drift legitimately).
        with open(_FIXTURE, "r") as f:
            content = f.read()
        broken = content.replace("10:00:00:02,500002,", "10:00:00:02,500003,")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as tf:
            tf.write(broken)
            broken_path = tf.name
        try:
            with self.assertRaises(CsvTimecodeMismatch):
                parse_csv_dense(broken_path, fps=50.0, strict_timecode=True)
        finally:
            os.unlink(broken_path)

    def test_smpte_drift_warns_but_does_not_raise_by_default(self):
        # take_4 production CSV has natural Disguise dual-stream drift; we
        # must not block import — only warn.
        with open(_FIXTURE, "r") as f:
            content = f.read()
        broken = content.replace("10:00:00:02,500002,", "10:00:00:02,500003,")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as tf:
            tf.write(broken)
            broken_path = tf.name
        try:
            # Should NOT raise — strict default is False
            result = parse_csv_dense(broken_path, fps=50.0)
            self.assertEqual(result.frame_count, 3)
        finally:
            os.unlink(broken_path)


class TestCsvParserBackwardsCompat(unittest.TestCase):
    """fps=None (the default) leaves structured fields as None."""

    def test_no_fps_skips_structured_fields(self):
        result = parse_csv_dense(_FIXTURE)
        self.assertIsNone(result.start_timecode)
        self.assertIsNone(result.end_timecode)
        self.assertIsNone(result.frame_rate)
        # Legacy string fields are still populated.
        self.assertEqual(result.timecode_start, "10:00:00:00")
        # FrameData.timecode is None as well.
        self.assertIsNone(result.frames[0].timecode)


class TestTrimStaticPaddingSyncsTimecode(unittest.TestCase):
    def test_trim_updates_structured_timecodes(self):
        # Build a head+tail-static round-trip take so trim_static_padding fires.
        with open(_FIXTURE) as fh:
            rows = fh.read().splitlines()
        # tail row pos back to 0.5,1.0,-2.0 so head == tail (round-trip)
        last = rows[-1].split(",")
        last[3] = "0.5"
        rows[-1] = ",".join(last)
        # Insert a static head row at 09:59:59:48 (one frame before sequence).
        head_static = rows[1].split(",")
        head_static[0] = "09:59:59:48"
        head_static[1] = "499998"
        rows.insert(1, ",".join(head_static))
        # Need at least one moving frame between head and tail; we already have
        # 0.6 mid-frame from the fixture. Renumber to keep absolute frames
        # strictly +1 (no SMPTE drift, since unwrap relies on equivalence).
        # New ordering: 09:59:59:48 / 499998 (head static), 10:00:00:00 / 499999 (head static),
        # 10:00:00:01 / 500000 (head static), 10:00:00:02 / 500001 (moving), 10:00:00:03 / 500002 (tail static).
        # Easiest: rewrite frame numbers in lock-step starting at 499998.
        out_rows = [rows[0]]  # header
        base_frame = 499998
        # New timecodes ascending by 1 each row.
        # Frame 499998 → 09:59:59:48, 499999 → 09:59:59:49, 500000 → 10:00:00:00,
        # 500001 → 10:00:00:01, 500002 → 10:00:00:02.
        tcs = ["09:59:59:48", "09:59:59:49", "10:00:00:00", "10:00:00:01", "10:00:00:02"]
        # We have 5 data rows now (1 inserted static + original 3 + the tail
        # rewrite is in slot 3). Strip extras.
        body = rows[1:]
        while len(body) < 5:
            body.append(body[-1])
        body = body[:5]
        # Set tail pos back to 0.5 to ensure round-trip
        tail = body[-1].split(",")
        tail[3] = "0.5"
        body[-1] = ",".join(tail)
        # Mid frame at slot 3 keeps 0.6 (moving)
        mid = body[3].split(",")
        mid[3] = "0.6"
        body[3] = ",".join(mid)
        for i, b in enumerate(body):
            parts = b.split(",")
            parts[0] = tcs[i]
            parts[1] = str(base_frame + i)
            out_rows.append(",".join(parts))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as tf:
            tf.write("\n".join(out_rows) + "\n")
            path = tf.name
        try:
            result = parse_csv_dense(path, fps=50.0)
            trimmed = trim_static_padding(result)
            # Trim should remove leading static head rows; structured timecode
            # tracks frames[0] / frames[-1].
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
        result = parse_csv_dense(_FIXTURE)
        trimmed = trim_static_padding(result)
        self.assertIsNone(trimmed.start_timecode)


class TestCsvParserTimecodeEdgeCases(unittest.TestCase):
    """Edge cases covering tracker-drop / single-frame / cross-midnight / >24h."""

    def _make_csv(self, body_rows: list[str]) -> str:
        return _write_csv([_HEADER_50FPS] + body_rows)

    def _data_row(self, timestamp: str, frame: int, x: float = 0.5) -> str:
        return (
            f"{timestamp},{frame},objects/camera/cam.apx,{x},1.0,-2.0,350,340,340,"
            "1920,1080,35.99,60.0,1.33,1.33,2496,1404,1.77,43.0,25.0,"
            "0.005,0.005,0.0,0.0,0.0"
        )

    def test_single_frame_csv_no_equivalence_check(self):
        path = self._make_csv([self._data_row("10:00:00:00", 500000)])
        try:
            result = parse_csv_dense(path, fps=50.0)
            self.assertEqual(result.frame_count, 1)
            self.assertEqual(str(result.start_timecode), "10:00:00:00")
            # end == start when there's only one frame
            self.assertEqual(str(result.end_timecode), "10:00:00:00")
        finally:
            os.unlink(path)

    def test_tracker_drop_frame_gap_does_not_false_positive(self):
        # 现场常见: tracker 偶尔丢帧导致 CSV 第 i 行的 frame_number 跳一格,
        # 但 timestamp 跟 frame_number 仍然一一对应。等价检查不应误报。
        path = self._make_csv([
            self._data_row("10:00:00:00", 500000, 0.5),
            # row 500001 跳过 — 模拟 tracker drop (在 _EmptyFieldError path 之外,
            # 实际 CSV 是 row 没出现; equivalence check 只看 retained frames)
            self._data_row("10:00:00:02", 500002, 0.6),
            self._data_row("10:00:00:05", 500005, 0.7),
        ])
        try:
            result = parse_csv_dense(path, fps=50.0)
            self.assertEqual(result.frame_count, 3)
            # delta_frame == delta_timecode 对每一行都成立 → 不抛
            self.assertEqual(str(result.start_timecode), "10:00:00:00")
            self.assertEqual(str(result.end_timecode), "10:00:00:05")
        finally:
            os.unlink(path)

    def test_cross_midnight_take_50fps(self):
        # 跨 00:00:00:00, unwrap_timecode_frames 走 24h wrap 分支
        path = self._make_csv([
            self._data_row("23:59:59:48", 500000, 0.5),
            self._data_row("23:59:59:49", 500001, 0.6),
            self._data_row("00:00:00:00", 500002, 0.7),
            self._data_row("00:00:00:01", 500003, 0.8),
        ])
        try:
            result = parse_csv_dense(path, fps=50.0)
            self.assertEqual(result.frame_count, 4)
            self.assertEqual(str(result.start_timecode), "23:59:59:48")
            self.assertEqual(str(result.end_timecode), "00:00:00:01")
        finally:
            os.unlink(path)

    def test_over_24h_span_fails_fast_when_strict(self):
        # frame_number 跨度 > 24h frames @ 50fps = 50 * 86400 = 4_320_000
        path = self._make_csv([
            self._data_row("00:00:00:00", 0, 0.5),
            self._data_row("00:00:00:01", 5_000_000, 0.6),
        ])
        try:
            with self.assertRaises(CsvTimecodeMismatch) as ctx:
                parse_csv_dense(path, fps=50.0, strict_timecode=True)
            self.assertIn("24h", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_invalid_timestamp_format_raises_csvparseerror_with_context(self):
        # 一个 frame 的 timestamp 不合法应该 raise CsvParseError 并带 frame 号
        path = self._make_csv([
            self._data_row("10:00:00:00", 500000, 0.5),
            self._data_row("BAD_FORMAT", 500001, 0.6),
        ])
        try:
            with self.assertRaises(CsvParseError) as ctx:
                parse_csv_dense(path, fps=50.0)
            self.assertIn("500001", str(ctx.exception))
            self.assertIn("BAD_FORMAT", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_over_24h_span_strict_only(self):
        # over-24h check is part of the strict envelope and only fires under
        # strict_timecode=True (consistent with the rest of fail-fast SMPTE checks).
        path = self._make_csv([
            self._data_row("00:00:00:00", 0, 0.5),
            self._data_row("00:00:00:01", 5_000_000, 0.6),
        ])
        try:
            # default tolerant mode: parse succeeds (24h check is part of strict)
            result = parse_csv_dense(path, fps=50.0)
            self.assertEqual(result.frame_count, 2)
        finally:
            os.unlink(path)

    def test_csv_timecode_mismatch_is_csvparseerror(self):
        # CsvTimecodeMismatch 必须继承 CsvParseError,这样 pipeline 的
        # `except CsvParseError` 分支能捕到
        self.assertTrue(issubclass(CsvTimecodeMismatch, CsvParseError))


if __name__ == "__main__":
    unittest.main()
