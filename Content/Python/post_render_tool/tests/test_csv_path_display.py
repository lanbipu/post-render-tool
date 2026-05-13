"""Tests for compact CSV path labels in the widget."""

from __future__ import annotations

import unittest

from post_render_tool.path_display import format_middle_ellipsis_path


class TestMiddleEllipsisPathDisplay(unittest.TestCase):

    def test_short_path_is_unchanged(self):
        path = "E:/shot.csv"
        self.assertEqual(format_middle_ellipsis_path(path), path)

    def test_windows_style_path_keeps_start_and_filename(self):
        path = (
            "E:/d3 Projects/0408/output/shots/test/take_15/"
            "test_take_15_dense.csv"
        )
        self.assertEqual(
            format_middle_ellipsis_path(path),
            "E:/d3 Projects/.../test_take_15_dense.csv",
        )

    def test_long_first_directory_is_preserved_when_it_fits(self):
        path = (
            "E:/RenderStream Projects/test_0311/Plugins/post-render-tool/"
            "validation_results/take_5_diff/test_take_5_dense.csv"
        )
        self.assertEqual(
            format_middle_ellipsis_path(path),
            "E:/RenderStream Projects/.../test_take_5_dense.csv",
        )

    def test_backslash_path_keeps_separator_style(self):
        path = (
            r"C:\Users\bip.lan\Documents\very\deep\folder"
            r"\shot_1_take_5_dense.csv"
        )
        self.assertEqual(
            format_middle_ellipsis_path(path),
            r"C:\Users\...\shot_1_take_5_dense.csv",
        )

    def test_long_filename_falls_back_to_middle_text_truncation(self):
        path = (
            "E:/d3 Projects/very/deep/"
            "shot_with_an_extremely_long_descriptive_dense_export_name.csv"
        )
        label = format_middle_ellipsis_path(path, max_chars=44)
        self.assertLessEqual(len(label), 44)
        self.assertTrue(label.startswith("E:/d3 Projects"))
        self.assertTrue(label.endswith("export_name.csv"))
        self.assertIn("...", label)


if __name__ == "__main__":
    unittest.main()
