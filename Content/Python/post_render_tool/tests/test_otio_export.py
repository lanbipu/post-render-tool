"""OTIO sidecar exporter tests.

Verifies the .otio file produced by `otio_export.export_sidecar` is:
- well-formed (parses back via `otio.adapters.read_from_file`)
- carries the correct SMPTE start timecode in `timeline.global_start_time`
- has an `ImageSequenceReference` with `start_frame = absolute_csv_frame`
- has a reasonable `frame_zero_padding`

DaVinci 19+ / Nuke import compatibility is a manual step in Task 13;
unit tests cover the OTIO schema invariants.
"""
from __future__ import annotations

import os
import tempfile
import unittest

try:
    import opentimelineio as otio
    _HAVE_OTIO = True
except ImportError:
    _HAVE_OTIO = False


@unittest.skipUnless(_HAVE_OTIO, "opentimelineio not installed")
class TestOtioExport(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="otio_test_")
        self.sidecar = os.path.join(self.tmpdir, "shot.otio")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _export(self, **overrides):
        from post_render_tool.otio_export import export_sidecar
        from post_render_tool.timecode import Timecode
        defaults = dict(
            sidecar_path=self.sidecar,
            shot_name="take_4",
            cg_render_dir="/renders/take_4",
            cg_filename_pattern="render.{frame:07d}.exr",
            start_csv_frame=625914,
            frame_count=100,
            start_timecode=Timecode.parse("10:00:00:00", 50.0),
            fps=50.0,
        )
        defaults.update(overrides)
        export_sidecar(**defaults)
        return otio.adapters.read_from_file(self.sidecar)

    def test_timeline_well_formed(self):
        tl = self._export()
        self.assertEqual(len(tl.tracks), 1)
        self.assertEqual(tl.name, "take_4")

    def test_cg_track_has_image_sequence_reference(self):
        tl = self._export()
        cg_track = tl.tracks[0]
        self.assertEqual(cg_track.name, "CG Render")
        clip = cg_track[0]
        ref = clip.media_reference
        self.assertIsInstance(ref, otio.schema.ImageSequenceReference)
        self.assertEqual(ref.start_frame, 625914)
        self.assertEqual(ref.frame_zero_padding, 7)
        self.assertEqual(ref.name_prefix, "render.")
        self.assertEqual(ref.name_suffix, ".exr")

    def test_global_start_time_matches_start_tc(self):
        # 10:00:00:00 @ 50fps = 50*60*60*10 = 1_800_000 frames since 0
        tl = self._export()
        gst = tl.global_start_time
        self.assertIsNotNone(gst)
        self.assertAlmostEqual(gst.rate, 50.0, places=3)
        self.assertEqual(
            otio.opentime.to_timecode(gst, rate=50.0),
            "10:00:00:00",
        )

    def test_fractional_fps_keeps_rate(self):
        from post_render_tool.timecode import Timecode
        tl = self._export(
            start_timecode=Timecode.parse("00:00:00:00", 23.976),
            fps=23.976,
        )
        ref = tl.tracks[0][0].media_reference
        # 23.976 stored as 24000/1001 ≈ 23.97602...
        self.assertAlmostEqual(ref.rate, 23.976, places=2)

    def test_dropframe_2997(self):
        from post_render_tool.timecode import Timecode
        tl = self._export(
            start_timecode=Timecode.parse("00:00:00;00", 29.97),
            fps=29.97,
        )
        # global_start_time round-trips through drop-frame timecode
        gst = tl.global_start_time
        self.assertIsNotNone(gst)

    def test_unknown_pattern_raises(self):
        from post_render_tool.otio_export import export_sidecar
        from post_render_tool.timecode import Timecode
        with self.assertRaises(ValueError):
            export_sidecar(
                sidecar_path=self.sidecar,
                shot_name="x",
                cg_render_dir="/r",
                cg_filename_pattern="bad-no-placeholder.exr",
                start_csv_frame=0,
                frame_count=1,
                start_timecode=Timecode.parse("00:00:00:00", 24.0),
                fps=24.0,
            )

    def test_source_range_duration_matches_frame_count(self):
        tl = self._export(frame_count=200)
        clip = tl.tracks[0][0]
        duration = clip.duration()
        self.assertEqual(int(duration.value), 200)

    def test_windows_path_produces_escaped_file_uri(self):
        # lanPC MRQ output path has drive letter + spaces; URI must escape
        # them so DaVinci/Nuke can resolve the EXR sequence.
        tl = self._export(cg_render_dir=r"E:\RenderStream Projects\take_4")
        url = tl.tracks[0][0].media_reference.target_url_base
        # Must escape space and route the drive letter via the 3-slash form.
        self.assertTrue(url.startswith("file:///E:/"),
                        f"unexpected URL: {url!r}")
        self.assertIn("RenderStream%20Projects", url,
                      f"space not escaped: {url!r}")
        # Trailing slash for OTIO ImageSequenceReference convention
        self.assertTrue(url.endswith("/"), url)

    def test_posix_path_produces_file_uri(self):
        tl = self._export(cg_render_dir="/renders/take 4")
        url = tl.tracks[0][0].media_reference.target_url_base
        self.assertTrue(url.startswith("file:///"),
                        f"unexpected URL: {url!r}")
        self.assertIn("take%204", url, f"space not escaped: {url!r}")


if __name__ == "__main__":
    unittest.main()
