"""Tests for ui_interface.save_axis_mapping — especially the legacy
config.py migration path (pre-ROTATION_OFFSET_DEG installations)."""

from __future__ import annotations

import ast
import sys
import tempfile
import types
import unittest
from pathlib import Path


def _stub_unreal_module() -> None:
    """Install a no-op ``unreal`` module so ui_interface can import."""
    if "unreal" in sys.modules:
        return
    stub = types.ModuleType("unreal")

    def _noop(*_args, **_kwargs):
        return None

    stub.log = _noop
    stub.log_warning = _noop
    stub.log_error = _noop
    sys.modules["unreal"] = stub


_stub_unreal_module()

from post_render_tool.ui_interface import save_axis_mapping  # noqa: E402


_LEGACY_CONFIG = '''"""Fake pre-offset config.py for migration test."""

POSITION_MAPPING = {
    "x": (2, -100.0),
    "y": (0, 100.0),
    "z": (1, 100.0),
}

ROTATION_MAPPING = {
    "pitch": (0, -1.0),
    "yaw": (1, -1.0),
    "roll": (2, 1.0),
}

ASSET_BASE_PATH = "/Game/PostRender"
'''

_MODERN_CONFIG = _LEGACY_CONFIG + '''
ROTATION_OFFSET_DEG = {
    "pitch": 5.0,
    "yaw": -45.0,
    "roll": 0.0,
}
'''


def _run_save(config_text: str, rot_offset: dict) -> str:
    """Write ``config_text`` to a temp file, invoke save_axis_mapping, return
    the resulting file contents."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.py"
        cfg.write_text(config_text, encoding="utf-8")

        pos = {"x": (2, -100.0), "y": (0, 100.0), "z": (1, 100.0)}
        rot = {"pitch": (0, -1.0), "yaw": (1, -1.0), "roll": (2, 1.0)}
        save_axis_mapping(pos, rot, rot_offset, config_path=str(cfg))

        return cfg.read_text(encoding="utf-8")


class TestSaveAxisMappingOffset(unittest.TestCase):
    """Offset block insertion / replacement semantics."""

    def test_modern_config_updates_existing_offset_block(self):
        result = _run_save(
            _MODERN_CONFIG,
            {"pitch": 0.0, "yaw": -90.0, "roll": 15.0},
        )
        self.assertIn("ROTATION_OFFSET_DEG", result)
        self.assertIn('"pitch": 0.0', result)
        self.assertIn('"yaw": -90.0', result)
        self.assertIn('"roll": 15.0', result)
        self.assertNotIn("-45.0", result, "old offset value should be replaced")
        ast.parse(result)  # must still be valid python

    def test_legacy_config_gains_offset_block(self):
        """Legacy config.py lacks ROTATION_OFFSET_DEG — insert after ROTATION_MAPPING."""
        self.assertNotIn("ROTATION_OFFSET_DEG", _LEGACY_CONFIG)

        result = _run_save(
            _LEGACY_CONFIG,
            {"pitch": 1.0, "yaw": -90.0, "roll": 0.0},
        )

        # Block inserted.
        self.assertIn("ROTATION_OFFSET_DEG", result)
        self.assertIn('"pitch": 1.0', result)
        self.assertIn('"yaw": -90.0', result)

        # Inserted AFTER ROTATION_MAPPING, BEFORE ASSET_BASE_PATH.
        rot_idx = result.index("ROTATION_MAPPING")
        off_idx = result.index("ROTATION_OFFSET_DEG")
        asset_idx = result.index("ASSET_BASE_PATH")
        self.assertLess(rot_idx, off_idx)
        self.assertLess(off_idx, asset_idx)

        ast.parse(result)  # must still be valid python

    def test_legacy_config_preserves_position_and_rotation(self):
        result = _run_save(
            _LEGACY_CONFIG,
            {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        )
        # Original mapping blocks must remain present after the migration.
        self.assertIn("POSITION_MAPPING", result)
        self.assertIn("ROTATION_MAPPING", result)
        self.assertIn("ASSET_BASE_PATH", result)


if __name__ == "__main__":
    unittest.main()
