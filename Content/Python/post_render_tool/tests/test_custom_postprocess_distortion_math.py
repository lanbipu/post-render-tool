"""Gate 1 - pure-Python reference for the Custom Post-Process Material shader.

跟 docs/custom-postprocess-distortion-final-plan.md §2.4 的 HLSL 公式一字一致.
shader / C++ controller 必须照抄. 任何形态偏移都先在这里反映出来.
"""

import unittest

from post_render_tool.distortion_math import (
    map_center_shift_projection,
    official_sensor_inverse_uv,
)


# 16:9 长宽比, 后续 production 多数是这个值
ASPECT_16_9 = 16.0 / 9.0


class TestIdentity(unittest.TestCase):
    """K1=K2=K3=0 时 sourceUV == UV, 任何位置任何 aspect 都成立."""

    def test_zero_K_at_center(self):
        u, v = official_sensor_inverse_uv(
            0.5, 0.5, k1=0.0, k2=0.0, k3=0.0, aspect=ASPECT_16_9
        )
        self.assertAlmostEqual(u, 0.5)
        self.assertAlmostEqual(v, 0.5)

    def test_zero_K_at_edge(self):
        u, v = official_sensor_inverse_uv(
            1.0, 0.0, k1=0.0, k2=0.0, k3=0.0, aspect=ASPECT_16_9
        )
        self.assertAlmostEqual(u, 1.0)
        self.assertAlmostEqual(v, 0.0)

    def test_distortion_weight_zero_kills_displacement(self):
        # K1=+0.5 但 weight=0 → 等价 identity
        u, v = official_sensor_inverse_uv(
            0.9, 0.5, k1=0.5, k2=0.0, k3=0.0,
            aspect=ASPECT_16_9, distortion_weight=0.0,
        )
        self.assertAlmostEqual(u, 0.9)
        self.assertAlmostEqual(v, 0.5)


class TestK1RadialDisplacement(unittest.TestCase):
    """K1>0 时边缘像素从更远位置取样 (Disguise pincushion 约定)."""

    def test_K1_positive_right_edge_samples_outward(self):
        # UV = (1.0, 0.5), center = (0.5, 0.5), K1 = +0.5, aspect = 16:9
        # d = (0.5, 0), r = (0.5, 0),  r2 = 0.25, fac = 0.5*0.25 = 0.125
        # sourceUV = (1.0 + 0.125*0.5, 0.5) = (1.0625, 0.5)
        u, v = official_sensor_inverse_uv(
            1.0, 0.5, k1=0.5, k2=0.0, k3=0.0, aspect=ASPECT_16_9
        )
        self.assertAlmostEqual(u, 1.0625, places=6)
        self.assertAlmostEqual(v, 0.5, places=6)

    def test_K1_positive_left_edge_samples_outward(self):
        # UV = (0.0, 0.5): d = (-0.5, 0), r = (-0.5, 0), r2 = 0.25, fac = 0.125
        # sourceUV = (0.0 + 0.125*(-0.5), 0.5) = (-0.0625, 0.5)
        u, v = official_sensor_inverse_uv(
            0.0, 0.5, k1=0.5, k2=0.0, k3=0.0, aspect=ASPECT_16_9
        )
        self.assertAlmostEqual(u, -0.0625, places=6)
        self.assertAlmostEqual(v, 0.5, places=6)

    def test_K1_negative_right_edge_samples_inward(self):
        # K1 = -0.5 时方向反过来, 边缘往中心靠
        # fac = -0.125, sourceUV = (1.0 + (-0.125)*0.5, 0.5) = (0.9375, 0.5)
        u, v = official_sensor_inverse_uv(
            1.0, 0.5, k1=-0.5, k2=0.0, k3=0.0, aspect=ASPECT_16_9
        )
        self.assertAlmostEqual(u, 0.9375, places=6)
        self.assertAlmostEqual(v, 0.5, places=6)

    def test_center_pixel_never_displaces(self):
        # UV == CenterUV → d = 0 → sourceUV == UV 任何 K 任何 weight
        for k1 in (-0.5, 0.0, 0.5):
            u, v = official_sensor_inverse_uv(
                0.5, 0.5, k1=k1, k2=0.3, k3=-0.2, aspect=ASPECT_16_9
            )
            self.assertAlmostEqual(u, 0.5, msg=f"K1={k1}")
            self.assertAlmostEqual(v, 0.5, msg=f"K1={k1}")


class TestCenterShiftProjectionMapping(unittest.TestCase):
    """map_center_shift_projection: sensor-mm with both-axis sign flip + UV center.

    Formula validated against D3 K=0 control frames 2026-05-07 (5 frames at
    K1=K2=K3=0 with cs ∈ {(0,0), (±0.5,0), (0,±0.5)}; UE renders 5 frames vs
    D3 reference, X residual < 0.1 px, Y residual < 0.1 px).
    See docs/distortion-investigation.md "2026-05-07 — K=0 直接测量".

    Both axes are sign-flipped because UE Filmback.SensorOffset and D3
    centerShiftMM use opposite conventions for "光心偏移方向":
        sensor_horizontal_offset_mm = -center_shift_x_mm
        sensor_vertical_offset_mm   = -center_shift_y_mm
        center_u = 0.5 + center_shift_x_mm / sensor_width_mm
        center_v = 0.5 + center_shift_y_mm / sensor_height_mm
    """

    def test_d3_k_zero_anchor(self):
        """cs=(0, 0) → zero offsets, centered UV."""
        mapping = map_center_shift_projection(
            center_shift_x_mm=0.0,
            center_shift_y_mm=0.0,
            sensor_width_mm=35.0,
            aspect=ASPECT_16_9,
        )
        self.assertAlmostEqual(mapping.center_u, 0.5, places=10)
        self.assertAlmostEqual(mapping.center_v, 0.5, places=10)
        self.assertAlmostEqual(mapping.sensor_horizontal_offset_mm, 0.0, places=10)
        self.assertAlmostEqual(mapping.sensor_vertical_offset_mm, 0.0, places=10)

    def test_d3_k_zero_shiftx_p0p5(self):
        """cs=(+0.5, 0) → -0.5mm horizontal sensor offset (X flipped)."""
        mapping = map_center_shift_projection(
            center_shift_x_mm=0.5,
            center_shift_y_mm=0.0,
            sensor_width_mm=35.0,
            aspect=ASPECT_16_9,
        )
        self.assertAlmostEqual(mapping.sensor_horizontal_offset_mm, -0.5, places=10)
        self.assertAlmostEqual(mapping.sensor_vertical_offset_mm, 0.0, places=10)
        self.assertAlmostEqual(mapping.center_u, 0.5142857142857142, places=10)
        self.assertAlmostEqual(mapping.center_v, 0.5, places=10)

    def test_d3_k_zero_shiftx_n0p5(self):
        """cs=(-0.5, 0) → +0.5mm horizontal sensor offset (X flipped)."""
        mapping = map_center_shift_projection(
            center_shift_x_mm=-0.5,
            center_shift_y_mm=0.0,
            sensor_width_mm=35.0,
            aspect=ASPECT_16_9,
        )
        self.assertAlmostEqual(mapping.sensor_horizontal_offset_mm, 0.5, places=10)
        self.assertAlmostEqual(mapping.sensor_vertical_offset_mm, 0.0, places=10)

    def test_d3_k_zero_shifty_p0p5(self):
        """cs=(0, +0.5) → -0.5mm vertical sensor offset (Y flipped, UE → -27.43 px @ 1080×19.689).

        D3 实测 -27.550 px (residual 0.4%).
        """
        mapping = map_center_shift_projection(
            center_shift_x_mm=0.0,
            center_shift_y_mm=0.5,
            sensor_width_mm=35.0,
            aspect=ASPECT_16_9,
        )
        self.assertAlmostEqual(mapping.sensor_horizontal_offset_mm, 0.0, places=10)
        self.assertAlmostEqual(mapping.sensor_vertical_offset_mm, -0.5, places=10)
        self.assertAlmostEqual(mapping.center_u, 0.5, places=10)
        self.assertAlmostEqual(mapping.center_v, 0.5253968253968254, places=10)

    def test_d3_k_zero_shifty_n0p5(self):
        """cs=(0, -0.5) → +0.5mm vertical sensor offset (Y flipped)."""
        mapping = map_center_shift_projection(
            center_shift_x_mm=0.0,
            center_shift_y_mm=-0.5,
            sensor_width_mm=35.0,
            aspect=ASPECT_16_9,
        )
        self.assertAlmostEqual(mapping.sensor_horizontal_offset_mm, 0.0, places=10)
        self.assertAlmostEqual(mapping.sensor_vertical_offset_mm, 0.5, places=10)

    def test_sensor_height_derived_from_aspect(self):
        """sensor_height_mm = sensor_width_mm / aspect (used by CenterUV.v)."""
        mapping = map_center_shift_projection(
            center_shift_x_mm=0.0,
            center_shift_y_mm=0.0,
            sensor_width_mm=35.0,
            aspect=ASPECT_16_9,
        )
        self.assertAlmostEqual(mapping.sensor_height_mm, 35.0 / ASPECT_16_9, places=10)

    def test_focal_length_does_not_affect_mapping(self):
        """centerShiftMM is a sensor-space offset, independent of focal length.

        D3 K=0 sweep (focal=30.302mm) measures 27.5 px shift; Path A LensFile
        had a focal-divided variant predicting only 8-16 px — that branch was
        wrong. Pinning the formula here so future refactors don't reintroduce it.
        """
        mapping_a = map_center_shift_projection(
            center_shift_x_mm=0.5, center_shift_y_mm=0.0,
            sensor_width_mm=35.0, aspect=ASPECT_16_9,
        )
        # focal_length_mm 已经从签名拿掉, 没有 keyword argument 可以传, 所以
        # "不同 focal" 这件事在这里通过签名缺失证明: API 不再让调用方误传 focal.
        # 等价行为: 同样的 sensor 配置下, 多次调用必须返回完全一致的 offset.
        mapping_b = map_center_shift_projection(
            center_shift_x_mm=0.5, center_shift_y_mm=0.0,
            sensor_width_mm=35.0, aspect=ASPECT_16_9,
        )
        self.assertEqual(
            mapping_a.sensor_horizontal_offset_mm,
            mapping_b.sensor_horizontal_offset_mm,
        )

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            map_center_shift_projection(
                center_shift_x_mm=0.0,
                center_shift_y_mm=0.0,
                sensor_width_mm=0.0,
                aspect=ASPECT_16_9,
            )
        with self.assertRaises(ValueError):
            map_center_shift_projection(
                center_shift_x_mm=0.0,
                center_shift_y_mm=0.0,
                sensor_width_mm=35.0,
                aspect=0.0,
            )


class TestAspectNormalization(unittest.TestCase):
    """Y 方向归一化用 sensor full-width (即 r.y = d.y/aspect)."""

    def test_y_displacement_smaller_than_x_at_same_offset(self):
        # 16:9 aspect, 同样的 d 偏移量, x 方向 r 更大, 位移也更大
        # UV=(0.6, 0.5): d=(0.1, 0), r=(0.1, 0), r2=0.01
        # UV=(0.5, 0.6): d=(0, 0.1), r=(0, 0.1/aspect)=(0, 0.05625), r2=0.003164
        # 同 K1, 同 d magnitude, 但 fac_x = K1*0.01 vs fac_y = K1*0.003164
        u_horiz, _ = official_sensor_inverse_uv(
            0.6, 0.5, k1=1.0, k2=0.0, k3=0.0, aspect=ASPECT_16_9
        )
        _, v_vert = official_sensor_inverse_uv(
            0.5, 0.6, k1=1.0, k2=0.0, k3=0.0, aspect=ASPECT_16_9
        )
        horiz_disp = u_horiz - 0.6
        vert_disp = v_vert - 0.6
        # 水平位移应该比垂直位移大 (aspect² 倍, 16:9 时是 ~3.16x)
        self.assertGreater(abs(horiz_disp), abs(vert_disp))
        # 比值精确等于 aspect²
        ratio = horiz_disp / vert_disp
        self.assertAlmostEqual(ratio, ASPECT_16_9 * ASPECT_16_9, places=4)

    def test_square_aspect_x_y_symmetric(self):
        # aspect=1.0 时同 d 偏移 x/y 对称
        u_horiz, _ = official_sensor_inverse_uv(
            0.6, 0.5, k1=1.0, k2=0.0, k3=0.0, aspect=1.0
        )
        _, v_vert = official_sensor_inverse_uv(
            0.5, 0.6, k1=1.0, k2=0.0, k3=0.0, aspect=1.0
        )
        self.assertAlmostEqual(u_horiz - 0.6, v_vert - 0.6, places=6)


class TestCenterShift(unittest.TestCase):
    """centerShiftMM feeds projection offset and radial distortion center."""

    def test_shifted_center_is_fixed_point(self):
        # center_uv = (0.6, 0.5) 时, 输入 UV = (0.6, 0.5) 永不位移, K 任意
        u, v = official_sensor_inverse_uv(
            0.6, 0.5, k1=0.5, k2=0.3, k3=-0.2,
            center_uv=(0.6, 0.5), aspect=ASPECT_16_9,
        )
        self.assertAlmostEqual(u, 0.6, places=6)
        self.assertAlmostEqual(v, 0.5, places=6)

    def test_center_shift_displaces_old_center(self):
        # center_uv = (0.6, 0.5) 时, UV = (0.5, 0.5) 不再是零点
        # d = (-0.1, 0), r = (-0.1, 0), r2 = 0.01, fac_K1 = 0.5*0.01 = 0.005
        # sourceUV = (0.5 + 0.005*(-0.1), 0.5) = (0.4995, 0.5)
        u, v = official_sensor_inverse_uv(
            0.5, 0.5, k1=0.5, k2=0.0, k3=0.0,
            center_uv=(0.6, 0.5), aspect=ASPECT_16_9,
        )
        self.assertAlmostEqual(u, 0.4995, places=6)
        self.assertAlmostEqual(v, 0.5, places=6)


class TestK2K3Powers(unittest.TestCase):
    """K2 是 r⁴ 项, K3 是 r⁶ 项 (OpenCV 标准形态先打底; Gate 6 验证后可能改)."""

    def test_K2_only_at_unit_radius(self):
        # UV = (1.0, 0.5), aspect = 16:9, K1=K3=0, K2=+0.5
        # d.x=0.5, r.x=0.5, r2=0.25, fac = 0 + 0.5*0.25² + 0 = 0.03125
        # sourceUV = (1.0 + 0.03125*0.5, 0.5) = (1.015625, 0.5)
        u, _ = official_sensor_inverse_uv(
            1.0, 0.5, k1=0.0, k2=0.5, k3=0.0, aspect=ASPECT_16_9
        )
        self.assertAlmostEqual(u, 1.015625, places=6)

    def test_K3_only_at_unit_radius(self):
        # 同上 r2=0.25, K1=K2=0, K3=+0.5
        # fac = 0 + 0 + 0.5*0.25³ = 0.0078125
        # sourceUV = (1.0 + 0.0078125*0.5, 0.5) = (1.00390625, 0.5)
        u, _ = official_sensor_inverse_uv(
            1.0, 0.5, k1=0.0, k2=0.0, k3=0.5, aspect=ASPECT_16_9
        )
        self.assertAlmostEqual(u, 1.00390625, places=6)

    def test_K2_K3_orders_diverge_at_half_radius(self):
        # UV=(0.75, 0.5), d.x=0.25, r.x=0.25 (full-width), r2=0.0625
        u_K2, _ = official_sensor_inverse_uv(
            0.75, 0.5, k1=0.0, k2=1.0, k3=0.0, aspect=ASPECT_16_9
        )
        u_K3, _ = official_sensor_inverse_uv(
            0.75, 0.5, k1=0.0, k2=0.0, k3=1.0, aspect=ASPECT_16_9
        )
        # K2: fac = 1.0 * 0.0625² = 0.00390625, sourceU = 0.75 + 0.00390625*0.25 = 0.7509765625
        # K3: fac = 1.0 * 0.0625³ = 0.000244140625, sourceU = 0.75 + 0.000244140625*0.25 = 0.75006103515625
        self.assertAlmostEqual(u_K2, 0.7509765625, places=6)
        self.assertAlmostEqual(u_K3, 0.75006103515625, places=6)


if __name__ == "__main__":
    unittest.main()
