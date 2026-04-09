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

    def test_auto_detect_fps_from_timestamps(self):
        """3 rows at 0.04 s intervals → detected_fps ≈ 25."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        rows = [
            self._make_row("00:00:00.00", 0),
            self._make_row("00:00:00.04", 1),
            self._make_row("00:00:00.08", 2),
        ]
        path = self._tmp(self._write_csv(headers, rows))

        result = parse_csv_dense(path)

        self.assertIsNotNone(result.detected_fps)
        self.assertAlmostEqual(result.detected_fps, 25.0, delta=1.0)

    def test_constant_timestamp_no_fps_detection(self):
        """All rows same timestamp → detected_fps is None."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        rows = [
            self._make_row("00:00:30.00", 1),
            self._make_row("00:00:30.00", 2),
            self._make_row("00:00:30.00", 3),
        ]
        path = self._tmp(self._write_csv(headers, rows))

        result = parse_csv_dense(path)

        self.assertIsNone(result.detected_fps)

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


if __name__ == "__main__":
    unittest.main()
