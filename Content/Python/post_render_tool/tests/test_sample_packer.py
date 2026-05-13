"""Unit tests for sample_packer.py — pure-Python sample preparation."""

import unittest
from dataclasses import dataclass
from typing import Optional

from post_render_tool.sample_packer import (
    SAMPLE_FIELDS,
    detect_contiguous,
    pack_samples,
)


@dataclass
class _MockFrame:
    """Minimal stand-in for csv_parser.FrameData; only the fields packer reads."""
    frame_number: int
    offset_x: float
    offset_y: float
    offset_z: float
    rotation_x: float
    rotation_y: float
    rotation_z: float
    focal_length_mm: float
    aperture: float
    focus_distance: float
    k1: float
    k2: float
    k3: float
    aspect_ratio: float
    center_shift_x_mm: float
    center_shift_y_mm: float
    overscan_x: Optional[float]
    overscan_y: Optional[float]


def _make_frame(frame_number: int, **overrides) -> _MockFrame:
    defaults = dict(
        frame_number=frame_number,
        offset_x=1.0, offset_y=2.0, offset_z=3.0,
        rotation_x=0.0, rotation_y=0.0, rotation_z=0.0,
        focal_length_mm=35.0,
        aperture=8.0,
        focus_distance=10.0,
        k1=0.0, k2=0.0, k3=0.0,
        aspect_ratio=1.7778,
        center_shift_x_mm=0.0,
        center_shift_y_mm=0.0,
        overscan_x=1.0,
        overscan_y=1.0,
    )
    defaults.update(overrides)
    return _MockFrame(**defaults)


class TestPackSamples(unittest.TestCase):

    def test_pack_returns_frame_numbers_and_samples_same_length(self):
        frames = [_make_frame(10), _make_frame(11), _make_frame(12)]
        frame_numbers, samples = pack_samples(frames)
        self.assertEqual(len(frame_numbers), 3)
        self.assertEqual(len(samples), 3)
        self.assertEqual(frame_numbers, [10, 11, 12])

    def test_each_sample_dict_has_all_required_fields(self):
        frames = [_make_frame(0)]
        _, samples = pack_samples(frames)
        for field in SAMPLE_FIELDS:
            self.assertIn(field, samples[0], f"missing sample field: {field}")

    def test_pack_applies_coordinate_transform(self):
        # config.py POSITION_MAPPING default swaps (z,x,y)→(X,Y,Z) ×100 cm
        frames = [_make_frame(0, offset_x=1.0, offset_y=2.0, offset_z=3.0)]
        _, samples = pack_samples(frames)
        # Designer offset (1,2,3) m → UE (z,x,y) ×100 = (300, 100, 200) cm
        self.assertAlmostEqual(samples[0]["location_x"], 300.0, places=3)
        self.assertAlmostEqual(samples[0]["location_y"], 100.0, places=3)
        self.assertAlmostEqual(samples[0]["location_z"], 200.0, places=3)

    def test_pack_converts_focus_distance_m_to_cm(self):
        frames = [_make_frame(0, focus_distance=5.5)]
        _, samples = pack_samples(frames)
        self.assertAlmostEqual(samples[0]["focus_distance_cm"], 550.0, places=3)

    def test_pack_negates_center_shift_to_sensor_offset(self):
        # sensor_offset = -center_shift_mm (see sequence_builder.py:376-381 rationale)
        frames = [_make_frame(0, center_shift_x_mm=0.166, center_shift_y_mm=0.192)]
        _, samples = pack_samples(frames)
        self.assertAlmostEqual(samples[0]["sensor_horizontal_offset_mm"], -0.166, places=4)
        self.assertAlmostEqual(samples[0]["sensor_vertical_offset_mm"], -0.192, places=4)

    def test_pack_overscan_uses_csv_to_ue_conversion(self):
        # CSV ratio 1.0 → UE Overscan 0.0 (no enlargement)
        frames = [_make_frame(0, overscan_x=1.0, overscan_y=1.0)]
        _, samples = pack_samples(frames)
        self.assertAlmostEqual(samples[0]["overscan"], 0.0, places=4)

    def test_pack_overscan_133_ratio(self):
        # CSV ratio 1.3334 → UE Overscan 0.3334
        frames = [_make_frame(0, overscan_x=1.3334, overscan_y=1.3334)]
        _, samples = pack_samples(frames)
        self.assertAlmostEqual(samples[0]["overscan"], 0.3334, places=4)


class TestDetectContiguous(unittest.TestCase):

    def test_contiguous_run(self):
        self.assertTrue(detect_contiguous([10, 11, 12, 13]))

    def test_single_frame_is_contiguous(self):
        self.assertTrue(detect_contiguous([42]))

    def test_empty_list_is_contiguous(self):
        # Edge case: vacuously true; caller should handle empty separately if needed.
        self.assertTrue(detect_contiguous([]))

    def test_gap_breaks_contiguity(self):
        self.assertFalse(detect_contiguous([10, 11, 13]))  # missing 12

    def test_negative_step_is_not_contiguous(self):
        self.assertFalse(detect_contiguous([10, 9]))


if __name__ == "__main__":
    unittest.main()
