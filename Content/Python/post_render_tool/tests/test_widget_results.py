"""Results text formatting tests for widget callbacks."""

from __future__ import annotations

import importlib
import sys
import types
import unittest


_MISSING = object()


def _install_unreal_stub() -> None:
    stub = types.ModuleType("unreal")
    stub.Text = lambda value: value
    stub.log = lambda *args, **kwargs: None
    stub.log_warning = lambda *args, **kwargs: None
    stub.log_error = lambda *args, **kwargs: None
    sys.modules["unreal"] = stub


def _install_pipeline_stub() -> None:
    stub = types.ModuleType("post_render_tool.pipeline")

    class PipelineResult:
        pass

    def run_import(*_args, **_kwargs):
        raise AssertionError("run_import should not be called by formatting tests")

    def run_patch_exr_timecode(*_args, **_kwargs):
        return stub.patch_result

    def run_export_otio(*_args, **_kwargs):
        return stub.otio_result

    stub.PipelineResult = PipelineResult
    stub.run_import = run_import
    stub.run_patch_exr_timecode = run_patch_exr_timecode
    stub.run_export_otio = run_export_otio
    stub.patch_result = {"patched_count": 0, "start_timecode": "10:00:00:00"}
    stub.otio_result = {
        "frame_count": 240,
        "start_timecode": "10:00:00:00",
        "sidecar_path": "E:/Render/output/LS_take_01.otio",
    }
    sys.modules["post_render_tool.pipeline"] = stub


def _install_ui_interface_stub() -> None:
    stub = types.ModuleType("post_render_tool.ui_interface")
    stub.browse_csv_file = lambda: ""
    stub.get_prerequisite_status = lambda: []
    stub.derive_mrq_filename_pattern = lambda _level_sequence_path: (
        "{sequence_name}.{frame:04d}.exr",
        4,
    )
    stub.open_movie_render_queue = lambda *_args, **_kwargs: None
    stub.open_sequencer = lambda *_args, **_kwargs: None
    stub.save_axis_mapping = lambda *_args, **_kwargs: None
    sys.modules["post_render_tool.ui_interface"] = stub


class TestWidgetResultsFormatting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._module_names = [
            "unreal",
            "post_render_tool.pipeline",
            "post_render_tool.ui_interface",
            "post_render_tool.widget",
        ]
        cls._original_modules = {
            name: sys.modules.get(name, _MISSING) for name in cls._module_names
        }
        _install_unreal_stub()
        _install_pipeline_stub()
        _install_ui_interface_stub()
        sys.modules.pop("post_render_tool.widget", None)
        cls.widget = importlib.import_module("post_render_tool.widget")

    @classmethod
    def tearDownClass(cls):
        for name in reversed(cls._module_names):
            original = cls._original_modules[name]
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    def test_patch_success_text_includes_user_facing_fields(self):
        text = self.widget._format_patch_result(
            True,
            count=12,
            start_timecode="10:00:00:00",
            output_dir="E:/Render/output shot",
        )

        self.assertEqual(
            "✅ Patch EXR Timecode 成功\n\n"
            "  共处理 12 个 EXR 文件\n"
            "  起始时间码：10:00:00:00\n"
            "  输出目录：\n"
            "    E:/Render/output shot",
            text,
        )

    def test_patch_failure_text_preserves_exception_message(self):
        text = self.widget._format_patch_result(
            False,
            exception_message="sample asset missing: LS_take_01",
        )

        self.assertEqual(
            "❌ Patch EXR Timecode 失败\n\n"
            "  原因：sample asset missing: LS_take_01",
            text,
        )

    def test_otio_success_text_includes_user_facing_fields(self):
        text = self.widget._format_otio_result(
            True,
            frame_count=240,
            start_timecode="10:00:00:00",
            sidecar_path="E:/Render/output/LS_take_01.otio",
        )

        self.assertEqual(
            "✅ Export OTIO Sidecar 成功\n\n"
            "  共写入 240 帧\n"
            "  起始时间码：10:00:00:00\n"
            "  输出文件：\n"
            "    E:/Render/output/LS_take_01.otio",
            text,
        )

    def test_otio_failure_text_preserves_exception_message(self):
        text = self.widget._format_otio_result(
            False,
            exception_message="cannot write sidecar: permission denied",
        )

        self.assertEqual(
            "❌ Export OTIO Sidecar 失败\n\n"
            "  原因：cannot write sidecar: permission denied",
            text,
        )

    def test_patch_guard_without_level_sequence_uses_shared_text(self):
        ui = object.__new__(self.widget.PostRenderToolUI)
        ui._last_result = None
        messages = []
        ui._set_results = messages.append

        ui._on_patch_exr_timecode_clicked()

        self.assertEqual(
            messages,
            ["⚠️ 还没 Import LevelSequence\n\n  请先跑 Import CSV 流程，再回来点这个按钮。"],
        )

    def test_patch_zero_files_uses_failure_text(self):
        ui = object.__new__(self.widget.PostRenderToolUI)
        ui._last_result = types.SimpleNamespace(
            level_sequence_path="/Game/PostRender/LS_take_01.LS_take_01"
        )
        ui._get_render_output_dir = lambda: "E:/Render/output"
        messages = []
        ui._set_results = messages.append

        ui._on_patch_exr_timecode_clicked()

        self.assertEqual(len(messages), 1)
        self.assertIn("❌ Patch EXR Timecode 失败", messages[0])
        self.assertIn("原因：没有找到匹配的 EXR 文件。", messages[0])
        self.assertNotIn("pattern:", messages[0])

    def test_otio_guard_without_level_sequence_uses_shared_text(self):
        ui = object.__new__(self.widget.PostRenderToolUI)
        ui._last_result = None
        messages = []
        ui._set_results = messages.append

        ui._on_export_otio_clicked()

        self.assertEqual(
            messages,
            ["⚠️ 还没 Import LevelSequence\n\n  请先跑 Import CSV 流程，再回来点这个按钮。"],
        )

    def test_otio_callback_success_uses_result_template(self):
        ui = object.__new__(self.widget.PostRenderToolUI)
        ui._last_result = types.SimpleNamespace(
            level_sequence_path="/Game/PostRender/LS_take_01.LS_take_01"
        )
        ui._get_render_output_dir = lambda: "E:/Render/output"
        messages = []
        ui._set_results = messages.append

        ui._on_export_otio_clicked()

        self.assertEqual(
            messages,
            [
                "✅ Export OTIO Sidecar 成功\n\n"
                "  共写入 240 帧\n"
                "  起始时间码：10:00:00:00\n"
                "  输出文件：\n"
                "    E:/Render/output/LS_take_01.otio"
            ],
        )

    def test_render_output_dir_guard_for_empty_input(self):
        class EmptyTextControl:
            def get_text(self):
                return "   "

        ui = object.__new__(self.widget.PostRenderToolUI)
        messages = []
        ui._set_results = messages.append
        ui._get = lambda _name: EmptyTextControl()

        result = ui._get_render_output_dir()

        self.assertIsNone(result)
        self.assertEqual(
            messages,
            ["⚠️ Render output dir 没填\n\n  请先在上方输入框填渲染输出目录。"],
        )


if __name__ == "__main__":
    unittest.main()
