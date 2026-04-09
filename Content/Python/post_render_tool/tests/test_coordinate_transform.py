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
        #   UE.X = -Designer.Z × 100 = -300.0
        #   UE.Y =  Designer.X × 100 =  100.0
        #   UE.Z =  Designer.Y × 100 =  200.0
        ue_x, ue_y, ue_z = transform_position(1.0, 2.0, 3.0)
        self.assertAlmostEqual(ue_x, -300.0)
        self.assertAlmostEqual(ue_y,  100.0)
        self.assertAlmostEqual(ue_z,  200.0)

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
        # Designer (rx=10, ry=20, rz=30):
        #   pitch = -rx × 1.0 = -10.0  → |pitch| = 10
        #   yaw   = -ry × 1.0 = -20.0  → |yaw|   = 20
        #   roll  =  rz × 1.0 =  30.0  → |roll|  = 30
        pitch, yaw, roll = transform_rotation(10.0, 20.0, 30.0)
        self.assertAlmostEqual(abs(pitch), 10.0)
        self.assertAlmostEqual(abs(yaw),   20.0)
        self.assertAlmostEqual(abs(roll),  30.0)


class TestTransformFocusDistance(unittest.TestCase):

    def test_focus_distance_conversion(self):
        # 5.0 meters → 500.0 cm
        result = transform_focus_distance(5.0)
        self.assertAlmostEqual(result, 500.0)


if __name__ == "__main__":
    unittest.main()
