"""Unit tests for sample_packer.py — pure-Python sample preparation."""

import unittest
from dataclasses import dataclass, field
from typing import Optional

from post_render_tool.sample_packer import (
    SAMPLE_FIELDS,
    detect_contiguous,
    pack_samples,
)
from post_render_tool.timecode import Timecode


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
    timecode: Optional[Timecode] = None


def _make_frame(frame_number: int, **overrides) -> _MockFrame:
    # Synthesise a unique Timecode per frame so pack_samples produces a
    # strictly-ascending frame_numbers list — pack_samples now uses
    # `timecode.to_frames()` as the canonical sequence frame index.
    # Spread frames 1 second apart so to_frames() values stay unique and
    # ordered regardless of `frame_number` value.
    hh = (frame_number // 3600) % 24
    mm = (frame_number // 60) % 60
    ss = frame_number % 60
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
        timecode=Timecode(
            hours=hh, minutes=mm, seconds=ss, frames=0,
            drop_frame=False, rate_num=24, rate_den=1,
        ),
    )
    defaults.update(overrides)
    return _MockFrame(**defaults)


class TestPackSamples(unittest.TestCase):

    def test_pack_returns_frame_numbers_and_samples_same_length(self):
        frames = [_make_frame(10), _make_frame(11), _make_frame(12)]
        frame_numbers, samples = pack_samples(frames)
        self.assertEqual(len(frame_numbers), 3)
        self.assertEqual(len(samples), 3)
        # frame_numbers now derives from timecode.to_frames(), not the CSV
        # `frame` column. _make_frame spaces frames 1s apart at 24 fps, so
        # frame_number 10/11/12 → 240/264/288.
        self.assertEqual(frame_numbers, [10 * 24, 11 * 24, 12 * 24])

    def test_pack_cross_midnight_stays_monotonic(self):
        """take crossing 00:00:00:00 must produce strictly-ascending frames.

        Without unwrap, Timecode.to_frames() wraps at 24h: e.g. 23:59:58:00
        → 4319900 @ 50fps, 00:00:02:00 → 100 (wrapped). pack_samples
        anchors on frames[0].timecode + delta, so output stays ascending.
        """
        tc_before = Timecode(
            hours=23, minutes=59, seconds=58, frames=0,
            drop_frame=False, rate_num=24, rate_den=1,
        )
        # 4 seconds after that = 00:00:02:00 next day
        tc_after = Timecode(
            hours=0, minutes=0, seconds=2, frames=0,
            drop_frame=False, rate_num=24, rate_den=1,
        )
        frames = [
            _make_frame(0, timecode=tc_before),
            _make_frame(1, timecode=tc_after),
        ]
        frame_numbers, _ = pack_samples(frames)
        # Strictly ascending — last > first (raw to_frames() would be
        # 0 < 4319900-equivalent at 24fps)
        self.assertGreater(frame_numbers[1], frame_numbers[0])
        # Delta = 4 seconds × 24 fps = 96 frames
        self.assertEqual(frame_numbers[1] - frame_numbers[0], 96)

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
