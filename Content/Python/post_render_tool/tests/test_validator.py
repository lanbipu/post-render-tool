"""Tests for validator.py — TDD for Task 4 (FOV validation + anomalous frame detection)."""

import math
import unittest

from post_render_tool.csv_parser import FrameData
from post_render_tool.validator import (
    FovCheckResult,
    ValidationReport,
    compute_fov_h,
    detect_anomalous_frames,
    generate_report,
    validate_fov,
)
from post_render_tool.csv_parser import CsvDenseResult


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_frame(
    *,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    offset_z: float = 0.0,
    rotation_x: float = 0.0,
    rotation_y: float = 0.0,
    rotation_z: float = 0.0,
    focal_length_mm: float = 30.302,
    sensor_width_mm: float = 35.0,
    fov_h: float = 60.0145,
    frame_number: int = 0,
    timestamp: str = "00:00:00.00",
    aspect_ratio: float = 1.7778,
    aperture: float = 2.8,
    focus_distance: float = 1000.0,
    k1: float = 0.0,
    k2: float = 0.0,
    k3: float = 0.0,
    center_shift_x_mm: float = 0.0,
    center_shift_y_mm: float = 0.0,
    fov_v: float = None,
    resolution_x: int = None,
    resolution_y: int = None,
) -> FrameData:
    return FrameData(
        timestamp=timestamp,
        frame_number=frame_number,
        offset_x=offset_x,
        offset_y=offset_y,
        offset_z=offset_z,
        rotation_x=rotation_x,
        rotation_y=rotation_y,
        rotation_z=rotation_z,
        focal_length_mm=focal_length_mm,
        sensor_width_mm=sensor_width_mm,
        aspect_ratio=aspect_ratio,
        aperture=aperture,
        focus_distance=focus_distance,
        k1=k1,
        k2=k2,
        k3=k3,
        center_shift_x_mm=center_shift_x_mm,
        center_shift_y_mm=center_shift_y_mm,
        fov_h=fov_h,
        fov_v=fov_v,
        resolution_x=resolution_x,
        resolution_y=resolution_y,
    )


# ---------------------------------------------------------------------------
# TestComputeFov
# ---------------------------------------------------------------------------

class TestComputeFov(unittest.TestCase):

    def test_known_fov(self):
        """35mm sensor, 30.302mm focal -> FOV ≈ 60.01°"""
        fov = compute_fov_h(30.302, 35.0)
        expected = math.degrees(2 * math.atan(35.0 / (2 * 30.302)))
        self.assertAlmostEqual(fov, expected, places=4)
        # Roughly 60° range
        self.assertAlmostEqual(fov, 60.0, delta=1.0)

    def test_wide_lens(self):
        """14mm focal, 35mm sensor -> FOV > 90°"""
        fov = compute_fov_h(14.0, 35.0)
        self.assertGreater(fov, 90.0)

    def test_telephoto(self):
        """200mm focal, 35mm sensor -> FOV < 15°"""
        fov = compute_fov_h(200.0, 35.0)
        self.assertLess(fov, 15.0)


# ---------------------------------------------------------------------------
# TestValidateFov
# ---------------------------------------------------------------------------

class TestValidateFov(unittest.TestCase):

    def test_valid_fov(self):
        """Frame with fov_h matching computed FOV -> error < 0.05°"""
        computed = compute_fov_h(30.302, 35.0)
        frame = make_frame(focal_length_mm=30.302, sensor_width_mm=35.0, fov_h=computed)
        result = validate_fov([frame])
        self.assertIsInstance(result, FovCheckResult)
        self.assertLess(result.max_fov_error_deg, 0.05)

    def test_fov_error_detected(self):
        """Frame with wrong fov_h=65.0 -> error > 1.0°"""
        frame = make_frame(focal_length_mm=30.302, sensor_width_mm=35.0, fov_h=65.0)
        result = validate_fov([frame])
        self.assertGreater(result.max_fov_error_deg, 1.0)

    def test_warning_flag_on_threshold(self):
        """Error > threshold -> has_fov_warning=True"""
        frame = make_frame(focal_length_mm=30.302, sensor_width_mm=35.0, fov_h=65.0)
        result = validate_fov([frame])
        self.assertTrue(result.has_fov_warning)


# ---------------------------------------------------------------------------
# TestAnomalousFrames
# ---------------------------------------------------------------------------

class TestAnomalousFrames(unittest.TestCase):

    def test_no_anomalies(self):
        """3 frames with tiny position changes -> empty list"""
        frames = [
            make_frame(offset_x=0.0, offset_y=0.0, offset_z=0.0, frame_number=0),
            make_frame(offset_x=0.01, offset_y=0.0, offset_z=0.0, frame_number=1),
            make_frame(offset_x=0.02, offset_y=0.0, offset_z=0.0, frame_number=2),
        ]
        result = detect_anomalous_frames(frames)
        self.assertEqual(result, [])

    def test_position_jump_detected(self):
        """Frame jumps 10 meters (1000 cm) -> detected at index 1"""
        frames = [
            make_frame(offset_x=0.0, offset_y=0.0, offset_z=0.0, frame_number=0),
            # 10m jump in x — offset_x is in meters in Designer CSV
            make_frame(offset_x=10.0, offset_y=0.0, offset_z=0.0, frame_number=1),
            make_frame(offset_x=10.01, offset_y=0.0, offset_z=0.0, frame_number=2),
        ]
        result = detect_anomalous_frames(frames)
        self.assertTrue(len(result) >= 1)
        frame_indices = [r["frame_index"] for r in result]
        self.assertIn(1, frame_indices)

    def test_rotation_jump_detected(self):
        """45° rotation jump in rotation_y -> detected"""
        frames = [
            make_frame(rotation_x=0.0, rotation_y=0.0, rotation_z=0.0, frame_number=0),
            make_frame(rotation_x=0.0, rotation_y=45.0, rotation_z=0.0, frame_number=1),
        ]
        result = detect_anomalous_frames(frames)
        self.assertTrue(len(result) >= 1)
        reasons = [r["reason"] for r in result]
        self.assertTrue(any("rotation" in r.lower() for r in reasons))


# ---------------------------------------------------------------------------
# TestValidationReport (smoke test)
# ---------------------------------------------------------------------------

class TestValidationReport(unittest.TestCase):

    def _make_csv_result(self):
        frames = [
            make_frame(frame_number=0, timestamp="00:00:00.00"),
            make_frame(frame_number=1, timestamp="00:00:00.04"),
        ]
        return CsvDenseResult(
            file_path="fake.csv",
            camera_prefix="camera:A",
            frames=frames,
            frame_count=len(frames),
            timecode_start=frames[0].timestamp,
            timecode_end=frames[-1].timestamp,
            focal_length_range=(30.302, 30.302),
            sensor_width_mm=35.0,
            detected_fps=25.0,
        )

    def test_generate_report_returns_report(self):
        csv_result = self._make_csv_result()
        report = generate_report(csv_result, fps=25.0)
        self.assertIsInstance(report, ValidationReport)
        self.assertEqual(report.frame_count, 2)

    def test_format_report_returns_string(self):
        csv_result = self._make_csv_result()
        report = generate_report(csv_result, fps=25.0)
        text = report.format_report()
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)


if __name__ == "__main__":
    unittest.main()
