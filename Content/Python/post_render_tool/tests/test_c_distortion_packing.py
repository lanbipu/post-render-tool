"""Tests for distortion_packing — guards Spherical parameter order.

匹配 ``test_c*.py`` 通配符，会被项目主测试命令自动发现：

    python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py"
"""

import unittest

from post_render_tool.distortion_packing import (
    SPHERICAL_PARAMETER_ORDER,
    to_spherical_parameters,
)


class TestSphericalParameterOrder(unittest.TestCase):

    def test_order_matches_ue_field_iteration(self):
        """K1, K2, K3, P1, P2 — UE FSphericalDistortionParameters 声明顺序。"""
        self.assertEqual(
            SPHERICAL_PARAMETER_ORDER,
            ("k1", "k2", "k3", "p1", "p2"),
        )

    def test_packs_in_declared_order(self):
        nd = {"k1": 0.249, "k2": 0.213, "k3": 0.335, "p1": 0.0, "p2": 0.0,
              "fx": 0.5, "fy": 0.7, "cx": 0.5, "cy": 0.5}
        result = to_spherical_parameters(nd)
        self.assertEqual(result, [0.249, 0.213, 0.335, 0.0, 0.0])

    def test_regression_k3_must_not_land_in_p2_slot(self):
        """已知 Bug（commit 9376195 之前）：K3 被错位到 index 4 (P2 槽)。"""
        nd = {"k1": 0.0, "k2": 0.0, "k3": 0.987, "p1": 0.0, "p2": 0.0}
        result = to_spherical_parameters(nd)
        self.assertEqual(result[2], 0.987, "K3 must occupy index 2")
        self.assertEqual(result[4], 0.0, "P2 must remain 0 when CSV has no tangential")

    def test_missing_key_raises(self):
        nd = {"k1": 0.0, "k2": 0.0, "k3": 0.0, "p1": 0.0}  # 缺 p2
        with self.assertRaises(KeyError):
            to_spherical_parameters(nd)

    def test_returns_floats(self):
        nd = {"k1": 1, "k2": 2, "k3": 3, "p1": 4, "p2": 5}
        result = to_spherical_parameters(nd)
        for v in result:
            self.assertIsInstance(v, float)


class TestBrownConradyUDOrder(unittest.TestCase):
    """to_brown_conrady_ud_parameters 顺序必须严格匹配
    FBrownConradyUDDistortionParameters 的 UPROPERTY 声明顺序 (BrownConradyUDLensModel.h:23-52):
        K1, K2, K3, K4, K5, K6, P1, P2
    """

    def test_packs_in_declared_order(self):
        from post_render_tool.distortion_packing import to_brown_conrady_ud_parameters
        nd = {
            "k1": 1.0, "k2": 2.0, "k3": 3.0,
            "k4": 4.0, "k5": 5.0, "k6": 6.0,
            "p1": 7.0, "p2": 8.0,
        }
        result = to_brown_conrady_ud_parameters(nd)
        self.assertEqual(result, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])

    def test_returns_floats(self):
        from post_render_tool.distortion_packing import to_brown_conrady_ud_parameters
        nd = {"k1": 1, "k2": 2, "k3": 3, "k4": 4, "k5": 5, "k6": 6, "p1": 7, "p2": 8}
        result = to_brown_conrady_ud_parameters(nd)
        for v in result:
            self.assertIsInstance(v, float)

    def test_missing_key_raises(self):
        from post_render_tool.distortion_packing import to_brown_conrady_ud_parameters
        nd = {"k1": 0.0, "k2": 0.0, "k3": 0.0, "k4": 0.0, "k5": 0.0, "k6": 0.0, "p1": 0.0}
        with self.assertRaises(KeyError):
            to_brown_conrady_ud_parameters(nd)

    def test_extra_keys_ignored(self):
        from post_render_tool.distortion_packing import to_brown_conrady_ud_parameters
        nd = {
            "k1": 0.0, "k2": 0.0, "k3": 0.0,
            "k4": 0.0, "k5": 0.0, "k6": 0.0,
            "p1": 0.0, "p2": 0.0,
            "fx": 999, "fy": 999, "cx": 999, "cy": 999,
        }
        result = to_brown_conrady_ud_parameters(nd)
        self.assertEqual(len(result), 8)


if __name__ == "__main__":
    unittest.main()
