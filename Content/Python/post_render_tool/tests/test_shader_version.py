"""SHADER_VERSION sanity (Mac-side, no UE).

Codex adversarial review (2026-05-07): pin SHADER_VERSION's invariants so the
runtime metadata-tag check stays useful.

build_distortion_material.py imports `unreal` at module top, which is fine in
UE Editor but absent on the Mac dev box. Stub it before import so this test
can run as part of the standard unittest discovery.
"""
from __future__ import annotations

import sys
import types
import unittest

if "unreal" not in sys.modules:
    sys.modules["unreal"] = types.ModuleType("unreal")

from post_render_tool.build_distortion_material import (  # noqa: E402
    HLSL_CODE,
    SHADER_VERSION,
    SHADER_VERSION_TAG,
)


class TestShaderVersion(unittest.TestCase):
    def test_shader_version_nonempty(self):
        self.assertTrue(SHADER_VERSION)
        self.assertTrue(SHADER_VERSION.strip() == SHADER_VERSION)

    def test_shader_version_has_iso_date_prefix(self):
        # 'YYYY-MM-DD-...' helps git blame + makes drift visible at a glance.
        self.assertRegex(SHADER_VERSION, r"^\d{4}-\d{2}-\d{2}-")

    def test_shader_version_baked_into_hlsl(self):
        # HLSL_CODE must carry SHADER_VERSION as a comment so visual inspection
        # of a saved asset's Custom node code matches the source-of-truth.
        self.assertIn(f"// VERSION: {SHADER_VERSION}", HLSL_CODE)

    def test_metadata_tag_name_stable(self):
        # Tag name lives in deployed assets; renaming it would orphan deployed tags.
        self.assertEqual(SHADER_VERSION_TAG, "PRT.ShaderVersion")


if __name__ == "__main__":
    unittest.main()
