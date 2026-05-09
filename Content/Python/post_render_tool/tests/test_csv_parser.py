"""Tests for csv_parser module. TDD — write first, implement second."""

import csv
import os
import tempfile
import unittest


class TestCsvDenseParser(unittest.TestCase):

    # ------------------------------------------------------------------ helpers

    def _make_headers(self, prefix: str):
        """Return the 26-column header list matching the reference CSV format."""
        p = prefix
        return [
            "timestamp", "frame",
            f"{p}.offset.x", f"{p}.offset.y", f"{p}.offset.z",
            f"{p}.rotation.x", f"{p}.rotation.y", f"{p}.rotation.z",
            f"{p}.resolution.x", f"{p}.resolution.y",
            f"{p}.fieldOfViewV", f"{p}.fieldOfViewH",
            f"{p}.overscan.x", f"{p}.overscan.y",
            f"{p}.overscanResolution.x", f"{p}.overscanResolution.y",
            f"{p}.aspectRatio",
            f"{p}.focalLengthMM",
            f"{p}.paWidthMM",
            f"{p}.centerShiftMM.x", f"{p}.centerShiftMM.y",
            f"{p}.k1k2k3.x", f"{p}.k1k2k3.y", f"{p}.k1k2k3.z",
            f"{p}.aperture", f"{p}.focusDistance",
        ]

    def _make_row(self, ts: str, frame: int, focal: float = 30.302):
        """Return a row list with sensible defaults."""
        return [
            ts, str(frame),
            "0.002", "0.998", "-6.001",          # offset x/y/z
            "0.0008", "0.003", "-0.0002",         # rotation x/y/z
            "1920", "1080",                        # resolution x/y
            "35.993", "60.0145",                   # fovV, fovH
            "1.3", "1.3",                          # overscan x/y
            "2496", "1404",                        # overscanResolution x/y
            "1.77779",                             # aspectRatio
            str(focal),                            # focalLengthMM
            "35",                                  # paWidthMM
            "0.00343", "0.00327",                  # centerShiftMM x/y
            "0.000286", "-0.00395", "0.01130",     # k1k2k3 x/y/z
            "2.8", "5",                            # aperture, focusDistance
        ]

    def _write_csv(self, headers: list, rows: list) -> str:
        """Write a temp CSV file and return its path."""
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        )
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
        f.close()
        return f.name

    def tearDown(self):
        # clean up any temp files registered per-test
        for path in getattr(self, "_tmp_files", []):
            try:
                os.unlink(path)
            except OSError:
                pass

    def _tmp(self, path: str) -> str:
        """Register a temp file for cleanup."""
        if not hasattr(self, "_tmp_files"):
            self._tmp_files = []
        self._tmp_files.append(path)
        return path

    # ------------------------------------------------------------------ tests

    def test_parse_valid_single_row(self):
        """Parse a 1-row CSV; verify key fields via dot-access on FrameData."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        rows = [self._make_row("00:00:30.00", 1790, focal=30.302)]
        path = self._tmp(self._write_csv(headers, rows))

        result = parse_csv_dense(path)

        self.assertEqual(result.camera_prefix, prefix)
        self.assertEqual(result.frame_count, 1)
        self.assertAlmostEqual(result.sensor_width_mm, 35.0, places=3)
        self.assertAlmostEqual(result.frames[0].focal_length_mm, 30.302, places=3)

    def test_parse_multiple_rows(self):
        """3 rows → frame_count=3, timecode_start/end match first/last timestamp."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        rows = [
            self._make_row("00:00:10.00", 600),
            self._make_row("00:00:10.04", 601),
            self._make_row("00:00:10.08", 602),
        ]
        path = self._tmp(self._write_csv(headers, rows))

        result = parse_csv_dense(path)

        self.assertEqual(result.frame_count, 3)
        self.assertEqual(result.timecode_start, "00:00:10.00")
        self.assertEqual(result.timecode_end, "00:00:10.08")

    def test_auto_detect_camera_prefix(self):
        """Prefix 'camera:cam_2' is auto-detected from headers."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_2"
        headers = self._make_headers(prefix)
        rows = [self._make_row("00:00:05.00", 300)]
        path = self._tmp(self._write_csv(headers, rows))

        result = parse_csv_dense(path)

        self.assertEqual(result.camera_prefix, prefix)

    def test_missing_required_field_raises(self):
        """Removing focalLengthMM column raises CsvParseError mentioning it."""
        from post_render_tool.csv_parser import CsvParseError, parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        # Remove focalLengthMM column
        focal_idx = headers.index(f"{prefix}.focalLengthMM")
        headers.pop(focal_idx)
        row = self._make_row("00:00:01.00", 60)
        row.pop(focal_idx)
        path = self._tmp(self._write_csv(headers, [row]))

        with self.assertRaises(CsvParseError) as ctx:
            parse_csv_dense(path)

        self.assertIn("focalLengthMM", str(ctx.exception))

    def test_focal_length_range(self):
        """2 rows with different focal lengths → range tuple matches min/max."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        rows = [
            self._make_row("00:00:00.00", 0, focal=30.302),
            self._make_row("00:00:00.04", 1, focal=70.0),
        ]
        path = self._tmp(self._write_csv(headers, rows))

        result = parse_csv_dense(path)

        self.assertAlmostEqual(result.focal_length_range[0], 30.302, places=3)
        self.assertAlmostEqual(result.focal_length_range[1], 70.0, places=3)

    def test_empty_file_raises(self):
        """Completely empty file (no headers, no rows) → CsvParseError."""
        from post_render_tool.csv_parser import CsvParseError, parse_csv_dense

        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        )
        f.close()
        self._tmp(f.name)

        with self.assertRaises(CsvParseError):
            parse_csv_dense(f.name)

    def test_row_with_empty_required_field_is_skipped(self):
        """Disguise-style dropped-tracker rows (empty required fields) are
        skipped, not fatal. Good rows still parse."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)

        good = self._make_row("00:00:10.00", 600)
        bad_offset = self._make_row("00:00:10.04", 601)
        bad_offset[headers.index(f"{prefix}.offset.x")] = ""  # blank required field
        good2 = self._make_row("00:00:10.08", 602)

        path = self._tmp(self._write_csv(headers, [good, bad_offset, good2]))
        result = parse_csv_dense(path)

        self.assertEqual(result.frame_count, 2)
        self.assertEqual([f.frame_number for f in result.frames], [600, 602])

    def test_empty_frame_column_is_also_skipped(self):
        """Blank `frame` column is treated the same as a blank body field."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)

        good = self._make_row("00:00:10.00", 600)
        bad_frame = self._make_row("00:00:10.04", 601)
        bad_frame[headers.index("frame")] = ""

        path = self._tmp(self._write_csv(headers, [good, bad_frame]))
        result = parse_csv_dense(path)

        self.assertEqual(result.frame_count, 1)
        self.assertEqual(result.frames[0].frame_number, 600)

    def test_carry_forward_lens_fields(self):
        """Disguise sparse-lens CSV: row 0 has lens params, row 1 blanks
        them → row 1 carries forward from row 0 (not zeros)."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        r0 = self._make_row("00:00:10.00", 600, focal=35.0)
        r1 = self._make_row("00:00:10.04", 601, focal=99.0)  # noqa: F841 overridden below
        # Blank r1's lens / optics columns
        for suffix in ("focalLengthMM", "paWidthMM", "aspectRatio",
                       "k1k2k3.x", "k1k2k3.y", "k1k2k3.z",
                       "centerShiftMM.x", "centerShiftMM.y",
                       "aperture", "focusDistance", "fieldOfViewH"):
            r1[headers.index(f"{prefix}.{suffix}")] = ""

        path = self._tmp(self._write_csv(headers, [r0, r1]))
        result = parse_csv_dense(path)

        self.assertEqual(result.frame_count, 2)
        self.assertAlmostEqual(result.frames[0].focal_length_mm, 35.0, places=3)
        self.assertAlmostEqual(result.frames[1].focal_length_mm, 35.0, places=3)
        self.assertAlmostEqual(result.frames[1].k1, result.frames[0].k1, places=6)

    def test_backfill_from_later_row(self):
        """Row 0 has blank lens fields, row 1 populated → row 0 seeds
        backward from row 1 (Disguise warmup pattern)."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        r0 = self._make_row("00:00:10.00", 600, focal=99.0)
        r1 = self._make_row("00:00:10.04", 601, focal=50.0)
        for suffix in ("focalLengthMM", "paWidthMM", "aspectRatio", "aperture"):
            r0[headers.index(f"{prefix}.{suffix}")] = ""

        path = self._tmp(self._write_csv(headers, [r0, r1]))
        result = parse_csv_dense(path)

        self.assertEqual(result.frame_count, 2)
        # Row 0 should have inherited row 1's values
        self.assertAlmostEqual(result.frames[0].focal_length_mm, 50.0, places=3)
        self.assertAlmostEqual(result.frames[1].focal_length_mm, 50.0, places=3)

    def test_carry_forward_missing_everywhere_defaults(self):
        """Blank-in-every-row fallback: hard fields → 0.0, soft fields → cinema-safe.

        Hard fields (k1/k2/k3, fov_h) get 0.0 with a "blank in ALL rows" warning.
        Soft fields (aperture, focusDistance) get SOFT_DEFAULTS (8.0 / 100.0)
        because 0 would mean f/0 + focus-at-lens, blurring the entire frame.
        """
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        r0 = self._make_row("00:00:10.00", 600)
        for suffix in ("k1k2k3.x", "k1k2k3.y", "k1k2k3.z",
                       "aperture", "focusDistance", "fieldOfViewH"):
            r0[headers.index(f"{prefix}.{suffix}")] = ""

        path = self._tmp(self._write_csv(headers, [r0]))
        result = parse_csv_dense(path)

        self.assertEqual(result.frame_count, 1)
        f = result.frames[0]
        self.assertEqual(f.k1, 0.0)
        self.assertEqual(f.fov_h, 0.0)
        # SOFT defaults — must NOT be 0
        self.assertEqual(f.aperture, 8.0)
        self.assertEqual(f.focus_distance, 100.0)

    def test_all_rows_empty_raises(self):
        """If every row has empty required fields, raise CsvParseError
        (no usable frames) rather than returning an empty result."""
        from post_render_tool.csv_parser import CsvParseError, parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)

        r1 = self._make_row("00:00:10.00", 600)
        r1[headers.index(f"{prefix}.offset.x")] = ""
        r2 = self._make_row("00:00:10.04", 601)
        r2[headers.index(f"{prefix}.rotation.y")] = ""

        path = self._tmp(self._write_csv(headers, [r1, r2]))

        with self.assertRaises(CsvParseError) as ctx:
            parse_csv_dense(path)
        self.assertIn("skipped 2", str(ctx.exception))

    def test_overscan_fields_parsed(self):
        """Overscan + overscanResolution 4 个字段从 CSV 解出来,挂到 FrameData."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        rows = [self._make_row("00:00:00.00", 0)]
        path = self._tmp(self._write_csv(headers, rows))

        result = parse_csv_dense(path)
        f0 = result.frames[0]

        self.assertAlmostEqual(f0.overscan_x, 1.3, places=4)
        self.assertAlmostEqual(f0.overscan_y, 1.3, places=4)
        self.assertEqual(f0.overscan_resolution_x, 2496)
        self.assertEqual(f0.overscan_resolution_y, 1404)


class TestSpatialmapDialect(unittest.TestCase):
    """Spatialmap-style export (Disguise mr_set_target__backplate_) parsing.

    Schema split across two prefixes:
      - transform: ``<base>.engineCameraPos.x`` / ``.engineCameraRotation.x``
      - intrinsic: ``<base>.activeCamera.<field>``
    aperture / focusDistance columns are absent entirely; parser must default 0.0.
    """

    def _make_headers(self, base: str):
        cam = f"{base}.activeCamera"
        return [
            "timestamp", "frame",
            f"{base}.activeCamera",                                   # decorative col seen in real CSV
            f"{base}.engineCameraPos.x", f"{base}.engineCameraPos.y", f"{base}.engineCameraPos.z",
            f"{base}.engineCameraRotation.x", f"{base}.engineCameraRotation.y", f"{base}.engineCameraRotation.z",
            f"{cam}.resolution.x", f"{cam}.resolution.y",
            f"{cam}.fieldOfViewV", f"{cam}.fieldOfViewH",
            f"{cam}.overscan.x", f"{cam}.overscan.y",
            f"{cam}.overscanResolution.x", f"{cam}.overscanResolution.y",
            f"{cam}.aspectRatio",
            f"{cam}.focalLengthMM",
            f"{cam}.paWidthMM",
            f"{cam}.centerShiftMM.x", f"{cam}.centerShiftMM.y",
            f"{cam}.k1k2k3.x", f"{cam}.k1k2k3.y", f"{cam}.k1k2k3.z",
            # NOTE: spatialmap export omits aperture + focusDistance columns
        ]

    def _make_row(self, ts: str, frame: int, focal: float = 43.2886):
        return [
            ts, str(frame),
            "objects/camera/cam 1.apx",                # activeCamera col (string, ignored by parser)
            "5.00252", "1.99925", "-12.0007",          # pos x/y/z
            "0.001", "0.002", "0.003",                  # rot x/y/z
            "1920", "1080",
            "23.45", "40.55",
            "1.0", "1.0",
            "1920", "1080",
            "1.77778",
            str(focal),
            "50",
            "0.0048995", "0.00467297",
            "0.000286122", "-0.00395342", "0.011302",
        ]

    def _write_csv(self, headers, rows):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        )
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
        f.close()
        return f.name

    def tearDown(self):
        for p in getattr(self, "_tmp", []):
            try: os.unlink(p)
            except OSError: pass

    def _track(self, p):
        if not hasattr(self, "_tmp"): self._tmp = []
        self._tmp.append(p)
        return p

    def test_parse_spatialmap_single_row(self):
        from post_render_tool.csv_parser import parse_csv_dense

        base = "spatialmap:mr_set_1_target__backplate_"
        headers = self._make_headers(base)
        rows = [self._make_row("09:44:25.10", 625994)]
        path = self._track(self._write_csv(headers, rows))

        result = parse_csv_dense(path)

        self.assertEqual(result.camera_prefix, base)
        self.assertEqual(result.frame_count, 1)
        f = result.frames[0]
        # Transform columns came from engineCameraPos / engineCameraRotation
        self.assertAlmostEqual(f.offset_x, 5.00252, places=4)
        self.assertAlmostEqual(f.offset_z, -12.0007, places=4)
        # Intrinsic from .activeCamera.* prefix
        self.assertAlmostEqual(f.focal_length_mm, 43.2886, places=3)
        self.assertAlmostEqual(f.sensor_width_mm, 50.0, places=3)
        self.assertAlmostEqual(f.k1, 0.000286122, places=8)
        self.assertAlmostEqual(f.k3, 0.011302, places=6)
        self.assertAlmostEqual(f.center_shift_x_mm, 0.0048995, places=6)
        # aperture / focusDistance columns absent entirely from spatialmap export.
        # MUST fall back to cinema-safe defaults, not 0 (would cause full blur).
        self.assertEqual(f.aperture, 8.0)
        self.assertEqual(f.focus_distance, 100.0)

    def test_take_4_aperture_focus_safe_defaults(self):
        """Regression: take_4 spatialmap CSV omits aperture/focusDistance.

        Before fix, parser fell back to 0 for both, which made
        CineCameraComponent render f/0 with focus locked at the lens — every
        Sequencer frame came out blurred. Verify SOFT_DEFAULTS now apply.
        """
        from post_render_tool.csv_parser import parse_csv_dense, trim_static_padding
        import os
        real_csv = "/tmp/test_take_4_dense.csv"
        if not os.path.exists(real_csv):
            self.skipTest(f"sample CSV not present: {real_csv}")
        result = trim_static_padding(parse_csv_dense(real_csv))
        for fr in result.frames[:5]:
            self.assertGreater(fr.aperture, 0,
                               "aperture must be > 0 to avoid full-frame blur")
            self.assertGreater(fr.focus_distance, 0,
                               "focus_distance must be > 0 to avoid focus-at-lens")
        # Specifically the cinema-safe defaults
        self.assertEqual(result.frames[0].aperture, 8.0)
        self.assertEqual(result.frames[0].focus_distance, 100.0)

    def test_parse_real_take_4_csv(self):
        """End-to-end: real Disguise take_4 dense CSV (756 rows)."""
        from post_render_tool.csv_parser import parse_csv_dense

        real_csv = "/tmp/test_take_4_dense.csv"
        if not os.path.exists(real_csv):
            self.skipTest(f"sample CSV not present: {real_csv}")
        result = parse_csv_dense(real_csv)
        self.assertEqual(result.camera_prefix, "spatialmap:mr_set_1_target__backplate_")
        self.assertEqual(result.frame_count, 756)
        self.assertAlmostEqual(result.frames[0].offset_x, 5.00252, places=4)
        self.assertAlmostEqual(result.frames[0].focal_length_mm, 43.2886, places=3)
        # row 1 = first motion (per location-change analysis)
        self.assertNotEqual(
            (result.frames[0].offset_x, result.frames[0].offset_y, result.frames[0].offset_z),
            (result.frames[1].offset_x, result.frames[1].offset_y, result.frames[1].offset_z),
        )

    def test_spatialmap_missing_anchor_column_raises(self):
        from post_render_tool.csv_parser import CsvParseError, parse_csv_dense

        # Headers with NO legacy / spatialmap anchor → parser cannot detect dialect.
        headers = ["timestamp", "frame", "foo.bar.x", "foo.bar.y"]
        path = self._track(self._write_csv(headers, [["00:00:00.00", "0", "0", "0"]]))
        with self.assertRaises(CsvParseError) as ctx:
            parse_csv_dense(path)
        self.assertIn("dialect", str(ctx.exception).lower())


class TestTrimStaticPadding(unittest.TestCase):
    """trim_static_padding drops leading/trailing rows with frozen camera pos."""

    def _make_result(self, poses):
        """Build a minimal CsvDenseResult from a list of (x,y,z) tuples."""
        from post_render_tool.csv_parser import CsvDenseResult, FrameData
        frames = [
            FrameData(
                timestamp=f"00:00:00.{i:02d}", frame_number=1000 + i,
                offset_x=p[0], offset_y=p[1], offset_z=p[2],
                rotation_x=0.0, rotation_y=0.0, rotation_z=0.0,
                focal_length_mm=30.0, sensor_width_mm=35.0, aspect_ratio=1.778,
                aperture=2.8, focus_distance=5.0,
                k1=0.0, k2=0.0, k3=0.0,
                center_shift_x_mm=0.0, center_shift_y_mm=0.0,
                fov_h=60.0, fov_v=None, resolution_x=1920, resolution_y=1080,
            )
            for i, p in enumerate(poses)
        ]
        return CsvDenseResult(
            file_path="dummy.csv", camera_prefix="camera:cam_1",
            frames=frames, frame_count=len(frames),
            timecode_start=frames[0].timestamp,
            timecode_end=frames[-1].timestamp,
            focal_length_range=(30.0, 30.0),
            sensor_width_mm=35.0, aspect_ratio=1.778,
        )

    def test_round_trip_static_padding(self):
        """Round-trip recording (camera returns to start): trim head + tail static."""
        from post_render_tool.csv_parser import trim_static_padding
        # 2 static @ origin + 3 motion + 2 static @ origin
        origin = (0.0, 0.0, 0.0)
        poses = [origin, origin, (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 0.0, 0.0), origin, origin]
        result = trim_static_padding(self._make_result(poses))
        # head trimmed → first frame is first motion row (idx 2 in original)
        self.assertEqual(result.frames[0].frame_number, 1002)
        # tail keeps 1 anchor static frame at original origin
        self.assertEqual(
            (result.frames[-1].offset_x, result.frames[-1].offset_y, result.frames[-1].offset_z),
            origin,
        )

    def test_full_motion_through_no_round_trip(self):
        """take_5-style: camera ends elsewhere than it started → no trim.

        Mid-shot CSV without leading/trailing static padding must be returned
        as-is, because the head/tail-pose-equality heuristic correctly
        identifies this case as not-a-round-trip.
        """
        from post_render_tool.csv_parser import trim_static_padding
        poses = [(i * 0.1, 0.0, 0.0) for i in range(5)]   # head=(0,0,0), tail=(0.4,0,0)
        original = self._make_result(poses)
        result = trim_static_padding(original)
        self.assertEqual(result.frame_count, original.frame_count)
        self.assertIs(result, original)

    def test_fully_static_csv_returns_unchanged(self):
        """All-static CSV (camera never moved) → return original (no motion to extract)."""
        from post_render_tool.csv_parser import trim_static_padding
        poses = [(1.0, 2.0, 3.0)] * 5
        original = self._make_result(poses)
        result = trim_static_padding(original)
        self.assertIs(result, original)

    def test_take_4_real_csv_trim(self):
        """Real take_4 CSV: 756 → motion-only (753 ish), starts at d3 frame 625994."""
        from post_render_tool.csv_parser import parse_csv_dense, trim_static_padding
        import os
        real_csv = "/tmp/test_take_4_dense.csv"
        if not os.path.exists(real_csv):
            self.skipTest(f"sample CSV not present: {real_csv}")
        result = trim_static_padding(parse_csv_dense(real_csv))
        self.assertLess(result.frame_count, 756)
        self.assertEqual(result.frames[0].frame_number, 625994)


class TestCsvOverscanMapping(unittest.TestCase):
    """csv_overscan_to_ue_overscan: CSV 1.0+ 倍率 → UE 0–1 增量."""

    def test_equal_xy_returns_minus_one(self):
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        self.assertAlmostEqual(
            csv_overscan_to_ue_overscan(1.3334, 1.3334, frame_number=42),
            0.3334, places=4,
        )

    def test_none_fallback_zero(self):
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        self.assertEqual(
            csv_overscan_to_ue_overscan(None, None, frame_number=0), 0.0
        )
        self.assertEqual(
            csv_overscan_to_ue_overscan(1.3, None, frame_number=0), 0.0
        )

    def test_below_one_clamped_zero(self):
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        self.assertEqual(
            csv_overscan_to_ue_overscan(0.95, 0.95, frame_number=0), 0.0
        )

    def test_asymmetric_raises(self):
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        with self.assertRaises(ValueError) as ctx:
            csv_overscan_to_ue_overscan(1.3, 1.5, frame_number=42)
        self.assertIn("42", str(ctx.exception))
        self.assertIn("asymmetric", str(ctx.exception).lower())

    def test_within_tolerance_does_not_raise(self):
        # 1.3334 vs 1.3340 = ~0.045% 差异,<0.5% 阈值,不报错,取均值
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        v = csv_overscan_to_ue_overscan(1.3334, 1.3340, frame_number=0)
        self.assertAlmostEqual(v, 0.3337, places=4)

    def test_above_two_raises(self):
        # CSV ratio > 2.0 → UE.Overscan > 1.0 超出 UCameraComponent.Overscan
        # 的 ClampMax,fail-fast,不 silent clamp.
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        with self.assertRaises(ValueError) as ctx:
            csv_overscan_to_ue_overscan(2.5, 2.5, frame_number=99)
        self.assertIn("99", str(ctx.exception))
        msg = str(ctx.exception).lower()
        self.assertTrue("上界" in str(ctx.exception) or "exceed" in msg)

    def test_mixed_underscan_overscan_raises(self):
        # 一轴 < 1.0 (underscan), 另一轴有 overscan: 必须 raise asymmetric,
        # 不能 silent clamp 0.0. 否则 unsupported 输入会产生错误 render.
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        with self.assertRaises(ValueError) as ctx:
            csv_overscan_to_ue_overscan(0.95, 1.30, frame_number=7)
        self.assertIn("7", str(ctx.exception))
        self.assertIn("asymmetric", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
