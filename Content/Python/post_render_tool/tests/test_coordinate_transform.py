"""Tests for coordinate_transform module. TDD — written before implementation."""

import unittest
from post_render_tool.coordinate_transform import (
    TransformConfig,
    transform_position,
    transform_rotation,
    transform_focus_distance,
)


class TestTransformPosition(unittest.TestCase):

    def test_origin_stays_origin(self):
        result = transform_position(0.0, 0.0, 0.0)
        self.assertEqual(result, (0.0, 0.0, 0.0))

    def test_unit_conversion_meters_to_cm(self):
        # Designer Y=1.0 → UE Z = Designer.Y × 100 = 100.0 cm
        result = transform_position(0.0, 1.0, 0.0)
        ue_x, ue_y, ue_z = result
        self.assertAlmostEqual(ue_z, 100.0)

    def test_position_mapping_axes(self):
        # Designer (1, 2, 3):
        #   UE.X = Designer.Z × 100 = 300.0
        #   UE.Y = Designer.X × 100 = 100.0
        #   UE.Z = Designer.Y × 100 = 200.0
        ue_x, ue_y, ue_z = transform_position(1.0, 2.0, 3.0)
        self.assertAlmostEqual(ue_x, 300.0)
        self.assertAlmostEqual(ue_y, 100.0)
        self.assertAlmostEqual(ue_z, 200.0)

    def test_custom_config(self):
        # Custom mapping: all axes identity × 1.0 (no reorder, no scale change)
        cfg = TransformConfig(
            pos_x=(0, 1.0),
            pos_y=(1, 1.0),
            pos_z=(2, 1.0),
            rot_pitch=(0, 1.0),
            rot_yaw=(1, 1.0),
            rot_roll=(2, 1.0),
        )
        ue_x, ue_y, ue_z = transform_position(4.0, 5.0, 6.0, cfg=cfg)
        self.assertAlmostEqual(ue_x, 4.0)
        self.assertAlmostEqual(ue_y, 5.0)
        self.assertAlmostEqual(ue_z, 6.0)


class TestTransformRotation(unittest.TestCase):

    def test_zero_rotation(self):
        result = transform_rotation(0.0, 0.0, 0.0)
        self.assertEqual(result, (0.0, 0.0, 0.0))

    def test_rotation_values_preserved_in_magnitude(self):
        # Designer (rx=10, ry=20, rz=30) → UE (pitch=10, yaw=20, roll=30)
        # All three are direct identity per default ROTATION_MAPPING.
        pitch, yaw, roll = transform_rotation(10.0, 20.0, 30.0)
        self.assertAlmostEqual(pitch, 10.0)
        self.assertAlmostEqual(yaw,   20.0)
        self.assertAlmostEqual(roll,  30.0)

    def test_yaw_offset_only_applies_to_yaw(self):
        # Offset yaw by -90°. Pitch and roll must be unaffected.
        cfg = TransformConfig(
            rot_pitch=(0, -1.0),
            rot_yaw=(1, -1.0),
            rot_roll=(2, 1.0),
            rot_pitch_offset=0.0,
            rot_yaw_offset=-90.0,
            rot_roll_offset=0.0,
        )
        pitch, yaw, roll = transform_rotation(10.0, 20.0, 30.0, cfg=cfg)
        #   pitch = -10 + 0    = -10
        #   yaw   = -20 + -90  = -110
        #   roll  =  30 + 0    =  30
        self.assertAlmostEqual(pitch, -10.0)
        self.assertAlmostEqual(yaw, -110.0)
        self.assertAlmostEqual(roll, 30.0)

    def test_all_offsets_sum_per_axis(self):
        cfg = TransformConfig(
            rot_pitch=(0, 1.0),
            rot_yaw=(1, 1.0),
            rot_roll=(2, 1.0),
            rot_pitch_offset=5.0,
            rot_yaw_offset=-12.5,
            rot_roll_offset=180.0,
        )
        pitch, yaw, roll = transform_rotation(1.0, 2.0, 3.0, cfg=cfg)
        self.assertAlmostEqual(pitch, 1.0 + 5.0)
        self.assertAlmostEqual(yaw,   2.0 + -12.5)
        self.assertAlmostEqual(roll,  3.0 + 180.0)

    def test_offset_rejects_non_numeric(self):
        with self.assertRaises(ValueError):
            TransformConfig(rot_yaw_offset="abc")


class TestTransformFocusDistance(unittest.TestCase):

    def test_focus_distance_conversion(self):
        # 5.0 meters → 500.0 cm
        result = transform_focus_distance(5.0)
        self.assertAlmostEqual(result, 500.0)


class TestKnownPoses(unittest.TestCase):
    """Regression: real Disguise CSV ↔ UE pose pairs captured 2026-04-20 by
    cross-checking the CSV import path against an FBX-imported camera wrapped
    in a Z=+90° parent Actor (the configuration verified visually correct in
    the UE viewport)."""

    def test_frame_1790_rest_pose(self):
        # CSV (0.00225, 0.99859, -6.00113) m, rotation ≈ 0 deg.
        ue_x, ue_y, ue_z = transform_position(0.0022488, 0.998591, -6.00113)
        self.assertAlmostEqual(ue_x, -600.113, places=3)
        self.assertAlmostEqual(ue_y,    0.225, places=3)
        self.assertAlmostEqual(ue_z,   99.859, places=3)

    def test_frame_2901_moved_pose(self):
        # CSV (5.00251, 1.99925, -12.0007) m, rotation (-7, -20, -18) deg.
        ue_x, ue_y, ue_z = transform_position(5.00251, 1.99925, -12.0007)
        self.assertAlmostEqual(ue_x, -1200.07,  places=2)
        self.assertAlmostEqual(ue_y,   500.251, places=3)
        self.assertAlmostEqual(ue_z,   199.925, places=3)
        pitch, yaw, roll = transform_rotation(-6.99896, -19.9967, -18.0002)
        self.assertAlmostEqual(pitch, -6.99896, places=4)
        self.assertAlmostEqual(yaw,  -19.9967,  places=4)
        self.assertAlmostEqual(roll, -18.0002,  places=4)


if __name__ == "__main__":
    unittest.main()
