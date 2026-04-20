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

    def test_carry_forward_missing_everywhere_defaults_zero(self):
        """If a lens field is blank in every row, default to 0.0 (no seed)."""
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
        self.assertEqual(f.aperture, 0.0)
        self.assertEqual(f.focus_distance, 0.0)
        self.assertEqual(f.fov_h, 0.0)

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


if __name__ == "__main__":
    unittest.main()
