"""EXR header SMPTE timecode patcher tests.

Offline (no `unreal` dependency). Uses oiio-static-python for mock-EXR
generation + attribute read-back; uses `exrheader` (from Miniforge3 on
lanPC; `brew install openimageio` on dev Mac) as ground-truth for
typed-attribute verification when available.

I/O tests skip if `oiio-static-python` is missing — keeps the pure-
Python suite runnable on contributors without it installed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest


try:
    import OpenImageIO as oiio
    import numpy as np
    _HAVE_OIIO = True
except ImportError:
    _HAVE_OIIO = False

_HAVE_EXRHEADER = shutil.which("exrheader") is not None


def _gen_test_exr(path: str, channels: int = 3) -> None:
    """Create a 4x4 EXR via OIIO Python (default RGB)."""
    spec = oiio.ImageSpec(4, 4, channels, "half")
    spec.attribute("compression", "zip")
    buf = oiio.ImageBuf(spec)
    fill = tuple([0.5] * channels)
    oiio.ImageBufAlgo.fill(buf, fill)
    if not buf.write(path):
        raise RuntimeError(f"OIIO write: {buf.geterror()}")


def _read_typed_timecode(path: str):
    """Return (time, user) tuple stored in smpte:TimeCode, or None."""
    buf = oiio.ImageBuf(path)
    return buf.spec().getattribute("smpte:TimeCode")


def _read_rational_fps(path: str):
    """Return (num, den) of FramesPerSecond, or None."""
    buf = oiio.ImageBuf(path)
    attr = buf.spec().getattribute("FramesPerSecond")
    return tuple(attr) if attr is not None else None


def _decode_smpte_time_field(val: int):
    """Inverse of _smpte_encode_time_field — for asserting per-frame
    increments in tests. Returns (h, m, s, f, drop_frame)."""
    ff = (val & 0xF) + ((val >> 4) & 0x3) * 10
    drop = bool((val >> 6) & 0x1)
    ss = ((val >> 8) & 0xF) + ((val >> 12) & 0x7) * 10
    mm = ((val >> 16) & 0xF) + ((val >> 20) & 0x7) * 10
    hh = ((val >> 24) & 0xF) + ((val >> 28) & 0x3) * 10
    return hh, mm, ss, ff, drop


def _exrheader_grep(path: str, attr_name: str) -> str:
    """Return the exrheader line containing `attr_name`, lower-cased.
    Empty string if exrheader unavailable or attribute not found."""
    if not _HAVE_EXRHEADER:
        return ""
    out = subprocess.check_output(
        ["exrheader", path], text=True, stderr=subprocess.STDOUT,
    )
    for line in out.splitlines():
        if attr_name.lower() in line.lower():
            return line.strip()
    return ""


@unittest.skipUnless(_HAVE_OIIO,
                     "oiio-static-python not installed — "
                     "pip install --user oiio-static-python==3.0.8.1.1")
class TestPatchExrTimecode(unittest.TestCase):
    def setUp(self):
        from post_render_tool.exr_timecode_writer import (
            patch_exr_timecode_in_dir,
        )
        self.patch = patch_exr_timecode_in_dir

        self.tmpdir = tempfile.mkdtemp(prefix="exr_test_")
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

        tc = _read_typed_timecode(first)
        self.assertIsNotNone(tc, "smpte:TimeCode missing after patch")
        self.assertEqual(len(tc), 2, f"expected (time,user) tuple, got {tc!r}")

        fps = _read_rational_fps(first)
        self.assertEqual(fps, (50, 1), f"got {fps!r}")

        # exrheader ground-truth cross-check.
        if _HAVE_EXRHEADER:
            tc_line = _exrheader_grep(first, "timecode")
            self.assertIn("type timecode", tc_line.lower(),
                          f"expected typed timecode, got: {tc_line!r}")
            fps_line = _exrheader_grep(first, "framesPerSecond")
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
        for offset, expected_ff in enumerate([0, 1, 2]):
            path = os.path.join(self.tmpdir, f"render.{625914 + offset:07d}.exr")
            tc_value = _read_typed_timecode(path)
            h, m, s, f, _drop = _decode_smpte_time_field(tc_value[0])
            self.assertEqual(
                (h, m, s, f), (10, 0, 0, expected_ff),
                f"frame {offset}: timecode drift")

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

    def test_subdir_pattern_raises(self):
        from post_render_tool.timecode import Timecode
        with self.assertRaises(ValueError) as ctx:
            self.patch(
                self.tmpdir,
                "shot1/render.{frame:07d}.exr",
                625914,
                Timecode.parse("10:00:00:00", 50.0),
                50.0,
            )
        self.assertIn("path separator", str(ctx.exception))

    def test_unresolved_mrq_token_raises(self):
        from post_render_tool.timecode import Timecode
        with self.assertRaises(ValueError) as ctx:
            self.patch(
                self.tmpdir,
                "{shot_name}.render.{frame:07d}.exr",
                625914,
                Timecode.parse("10:00:00:00", 50.0),
                50.0,
            )
        self.assertIn("unresolved tokens", str(ctx.exception))

    def test_skips_files_below_start_frame(self):
        from post_render_tool.timecode import Timecode
        below = os.path.join(self.tmpdir, "render.0625900.exr")
        _gen_test_exr(below)
        n = self.patch(
            self.tmpdir,
            "render.{frame:07d}.exr",
            625914,
            Timecode.parse("10:00:00:00", 50.0),
            50.0,
        )
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


@unittest.skipUnless(_HAVE_OIIO, "oiio-static-python not installed")
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
        r = _read_rational_fps(path)
        self.assertEqual(
            r, (exp_num, exp_den),
            f"expected {exp_num}/{exp_den} for {fps}fps, got: {r!r}",
        )
        # exrheader ground-truth: confirm it's stored as `type rational`.
        if _HAVE_EXRHEADER:
            line = _exrheader_grep(path, "framesPerSecond")
            self.assertIn(f"{exp_num}/{exp_den}", line,
                          f"exrheader: expected {exp_num}/{exp_den}, got: {line}")

    def test_23976_writes_24000_over_1001(self):
        self._check_rational(23.976, "00:00:00:00", 24000, 1001)

    def test_2997_writes_30000_over_1001(self):
        self._check_rational(29.97, "00:00:00;00", 30000, 1001)

    def test_5994_writes_60000_over_1001(self):
        self._check_rational(59.94, "00:00:00;00", 60000, 1001)

    def test_50_writes_50_over_1(self):
        self._check_rational(50.0, "00:00:00:00", 50, 1)


@unittest.skipUnless(_HAVE_OIIO, "oiio-static-python not installed")
class TestMultipartPreservation(unittest.TestCase):
    """Multipart EXR rewrite must preserve every subimage with its own
    channel layout. Regression-guards the failure mode Codex
    adversarial review [high] flagged (ImageBuf.write per-subimage
    collapsing multipart to last subimage)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="exr_test_multipart_")
        self.path = os.path.join(self.tmpdir, "render.0000000.exr")
        # Build a 2-subimage EXR: subimage 0 = RGB (3 ch), subimage 1 =
        # RGBA (4 ch). Different channel counts make collapsing visible.
        spec0 = oiio.ImageSpec(4, 4, 3, "half")
        spec0.attribute("compression", "zip")
        pix0 = np.full((4, 4, 3), 0.5, dtype=np.float16)
        spec1 = oiio.ImageSpec(4, 4, 4, "half")
        spec1.attribute("compression", "zip")
        pix1 = np.full((4, 4, 4), 0.3, dtype=np.float16)

        out = oiio.ImageOutput.create(self.path)
        if not out.open(self.path, [spec0, spec1]):
            self.fail(f"multipart open: {out.geterror()}")
        if not out.write_image(pix0):
            self.fail(f"subimage 0 write: {out.geterror()}")
        if not out.open(self.path, spec1, "AppendSubimage"):
            self.fail(f"AppendSubimage open: {out.geterror()}")
        if not out.write_image(pix1):
            self.fail(f"subimage 1 write: {out.geterror()}")
        out.close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_multipart_rewrite_preserves_two_subimages(self):
        from post_render_tool.exr_timecode_writer import (
            patch_exr_timecode_in_dir,
        )
        from post_render_tool.timecode import Timecode

        n = patch_exr_timecode_in_dir(
            self.tmpdir,
            "render.{frame:07d}.exr",
            0,
            Timecode.parse("10:00:00:00", 50.0),
            50.0,
        )
        self.assertEqual(n, 1, "patcher reported wrong file count")

        # Authoritative subimage count via ImageInput.seek_subimage.
        inp = oiio.ImageInput.open(self.path)
        try:
            specs = []
            si = 0
            while inp.seek_subimage(si, 0):
                specs.append(inp.spec())
                si += 1
        finally:
            inp.close()
        self.assertEqual(si, 2, f"subimage count drift: {si}")
        self.assertEqual([s.nchannels for s in specs], [3, 4],
                         f"channel layout drift: {[s.nchannels for s in specs]}")
        # Typed attrs must be on EVERY subimage.
        for i, sp in enumerate(specs):
            self.assertIsNotNone(
                sp.getattribute("smpte:TimeCode"),
                f"subimage {i}: smpte:TimeCode missing")
            self.assertEqual(
                tuple(sp.getattribute("FramesPerSecond")), (50, 1),
                f"subimage {i}: FramesPerSecond drift")


if __name__ == "__main__":
    unittest.main()
