"""EXR header SMPTE timecode patcher tests.

Offline (no `unreal` dependency); shells out to `oiiotool` + `exrheader`
which need to be installed (`brew install openimageio` on macOS).

The tests skip themselves if either CLI is missing — keeps CI lean and lets
contributors without OpenImageIO still run the rest of the suite.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest


_HAVE_OIIOTOOL = shutil.which("oiiotool") is not None
_HAVE_EXRHEADER = shutil.which("exrheader") is not None


def _gen_test_exr(path: str) -> None:
    """Create a 4x4 RGB EXR via oiiotool."""
    subprocess.check_call([
        "oiiotool",
        "--create", "4x4", "3",
        "--fill:color=0.5,0.5,0.5", "4x4",
        "-o", path,
    ])


def _read_exr_attribute_line(path: str, attr_name: str) -> str:
    """Return the exrheader line containing `attr_name`, lower-cased."""
    if not _HAVE_EXRHEADER:
        return ""
    out = subprocess.check_output(
        ["exrheader", path], text=True, stderr=subprocess.STDOUT
    )
    for line in out.splitlines():
        if attr_name.lower() in line.lower():
            return line.strip()
    return ""


@unittest.skipUnless(_HAVE_OIIOTOOL, "oiiotool not on PATH")
class TestPatchExrTimecode(unittest.TestCase):
    def setUp(self):
        # Late import — the module triggers an oiiotool availability check
        # at call time, but we only want to import once tests can run.
        from post_render_tool.exr_timecode_writer import (
            patch_exr_timecode_in_dir,
        )
        self.patch = patch_exr_timecode_in_dir

        self.tmpdir = tempfile.mkdtemp(prefix="exr_test_")
        # Generate 3 frames with absolute frame numbers 625914..625916
        for i in range(3):
            _gen_test_exr(os.path.join(
                self.tmpdir, f"render.{625914 + i:07d}.exr"
            ))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_50fps_patch_writes_typed_attributes(self):
        from post_render_tool.timecode import Timecode
        n = self.patch(
            output_dir=self.tmpdir,
            filename_pattern="render.{frame:07d}.exr",
            start_csv_frame=625914,
            start_timecode=Timecode.parse("10:00:00:00", 50.0),
            fps=50.0,
        )
        self.assertEqual(n, 3)
        first = os.path.join(self.tmpdir, "render.0625914.exr")
        if _HAVE_EXRHEADER:
            tc_line = _read_exr_attribute_line(first, "timecode")
            self.assertIn("type timecode", tc_line.lower(),
                          f"expected typed timecode, got: {tc_line!r}")
            fps_line = _read_exr_attribute_line(first, "framesPerSecond")
            self.assertIn("rational", fps_line.lower(),
                          f"expected rational FramesPerSecond, got: {fps_line!r}")

    def test_increments_per_frame_50fps(self):
        from post_render_tool.timecode import Timecode
        self.patch(
            self.tmpdir,
            "render.{frame:07d}.exr",
            625914,
            Timecode.parse("10:00:00:00", 50.0),
            50.0,
        )
        if not _HAVE_EXRHEADER:
            self.skipTest("exrheader missing — can't verify per-frame increment")
        # Frame 625914 -> 10:00:00:00, 625915 -> 10:00:00:01, etc.
        # exrheader prints raw bit-packed values, but oiiotool --info -v
        # decodes them. We use oiiotool for the value check.
        for offset, expected_ff in enumerate([0, 1, 2]):
            path = os.path.join(self.tmpdir, f"render.{625914 + offset:07d}.exr")
            info = subprocess.check_output(
                ["oiiotool", "--info", "-v", path], text=True,
                stderr=subprocess.STDOUT,
            )
            self.assertIn(f"10:00:00:{expected_ff:02d}", info,
                          f"frame {offset}: expected '10:00:00:{expected_ff:02d}' "
                          f"in oiiotool info, got: {info[-200:]}")

    def test_nonexistent_dir_returns_zero(self):
        from post_render_tool.timecode import Timecode
        n = self.patch(
            "/no/such/dir",
            "render.{frame:07d}.exr",
            625914,
            Timecode.parse("10:00:00:00", 50.0),
            50.0,
        )
        self.assertEqual(n, 0)

    def test_skips_files_below_start_frame(self):
        from post_render_tool.timecode import Timecode
        # Add a file with absolute frame BELOW start_csv_frame; patcher
        # should leave it alone.
        below = os.path.join(self.tmpdir, "render.0625900.exr")
        _gen_test_exr(below)
        n = self.patch(
            self.tmpdir,
            "render.{frame:07d}.exr",
            625914,
            Timecode.parse("10:00:00:00", 50.0),
            50.0,
        )
        # 3 in-range + 1 out-of-range — only 3 patched
        self.assertEqual(n, 3)


class TestFrameToTimecodeRoundTrip(unittest.TestCase):
    """Pure Python — drop-frame inverse algorithm round-trip."""

    def test_non_drop_round_trip_50fps(self):
        from post_render_tool.exr_timecode_writer import _frame_to_timecode
        from post_render_tool.timecode import Timecode
        start = Timecode.parse("10:00:00:00", 50.0)
        for offset in [0, 1, 49, 50, 100, 50 * 60, 50 * 3600]:
            tc = _frame_to_timecode(start, offset)
            self.assertEqual(
                tc.to_frames() - start.to_frames(),
                offset,
                f"round-trip fail at offset {offset}: got {tc}",
            )

    def test_non_drop_round_trip_24fps(self):
        from post_render_tool.exr_timecode_writer import _frame_to_timecode
        from post_render_tool.timecode import Timecode
        start = Timecode.parse("00:00:00:00", 24.0)
        for offset in [0, 23, 24, 100, 24 * 60, 24 * 3600 * 5]:
            tc = _frame_to_timecode(start, offset)
            self.assertEqual(
                tc.to_frames() - start.to_frames(),
                offset,
                f"round-trip fail at offset {offset}: got {tc}",
            )

    def test_drop_frame_round_trip_2997(self):
        from post_render_tool.exr_timecode_writer import _frame_to_timecode
        from post_render_tool.timecode import Timecode
        start = Timecode.parse("00:00:00;00", 29.97)
        # SMPTE-significant offsets: minute boundary, 10-min boundary, hour.
        for offset in [0, 1, 1797, 1798, 1799, 1800, 17981, 17982, 17983, 107891, 107892]:
            tc = _frame_to_timecode(start, offset)
            self.assertEqual(
                tc.to_frames() - start.to_frames(),
                offset,
                f"drop-frame round-trip fail at offset {offset}: got {tc}",
            )

    def test_drop_frame_round_trip_5994(self):
        from post_render_tool.exr_timecode_writer import _frame_to_timecode
        from post_render_tool.timecode import Timecode
        start = Timecode.parse("00:00:00;00", 59.94)
        for offset in [0, 1, 3595, 3596, 3597, 3599, 3600, 215783, 215784]:
            tc = _frame_to_timecode(start, offset)
            self.assertEqual(
                tc.to_frames() - start.to_frames(),
                offset,
                f"drop-frame 59.94 round-trip fail at offset {offset}: got {tc}",
            )

    def test_cross_midnight_does_not_raise(self):
        """offset that pushes total past 24h gets wrapped, not rejected."""
        from post_render_tool.exr_timecode_writer import _frame_to_timecode
        from post_render_tool.timecode import Timecode, _frames_per_24h
        start = Timecode.parse("23:59:59:48", 50.0)
        # 5 frames after 23:59:59:48 → wraps to 00:00:00:03
        tc = _frame_to_timecode(start, 5)
        self.assertEqual((tc.hours, tc.minutes, tc.seconds, tc.frames),
                         (0, 0, 0, 3))

    def test_cross_midnight_dropframe_does_not_raise(self):
        from post_render_tool.exr_timecode_writer import _frame_to_timecode
        from post_render_tool.timecode import Timecode
        # 29.97 DF: 23:59:59;29 + 1 frame should wrap to 00:00:00;00
        # (top-of-hour: 10-min boundary at H 24:00 wraps to 0)
        start = Timecode.parse("23:59:59;29", 29.97)
        tc = _frame_to_timecode(start, 1)
        # After wrap, hours must be 0..23
        self.assertLess(tc.hours, 24)


@unittest.skipUnless(_HAVE_OIIOTOOL and _HAVE_EXRHEADER,
                     "oiiotool + exrheader needed")
class TestFractionalFpsRationalMetadata(unittest.TestCase):
    """FramesPerSecond must keep the exact NTSC rational (24000/1001 etc.),
    not get rounded to integer 24/1. Otherwise EXR readers drift over long
    takes."""

    def setUp(self):
        from post_render_tool.exr_timecode_writer import (
            patch_exr_timecode_in_dir,
        )
        self.patch = patch_exr_timecode_in_dir
        self.tmpdir = tempfile.mkdtemp(prefix="exr_test_rational_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _check_rational(self, fps: float, tc_str: str, exp_num: int, exp_den: int):
        from post_render_tool.timecode import Timecode
        path = os.path.join(self.tmpdir, "render.0000000.exr")
        _gen_test_exr(path)
        n = self.patch(
            self.tmpdir,
            "render.{frame:07d}.exr",
            0,
            Timecode.parse(tc_str, fps),
            fps,
        )
        self.assertEqual(n, 1)
        line = _read_exr_attribute_line(path, "framesPerSecond")
        self.assertIn(f"{exp_num}/{exp_den}", line,
                      f"expected {exp_num}/{exp_den} for {fps}fps, got: {line}")

    def test_23976_writes_24000_over_1001(self):
        self._check_rational(23.976, "00:00:00:00", 24000, 1001)

    def test_2997_writes_30000_over_1001(self):
        self._check_rational(29.97, "00:00:00;00", 30000, 1001)

    def test_5994_writes_60000_over_1001(self):
        self._check_rational(59.94, "00:00:00;00", 60000, 1001)

    def test_50_writes_50_over_1(self):
        self._check_rational(50.0, "00:00:00:00", 50, 1)


if __name__ == "__main__":
    unittest.main()
