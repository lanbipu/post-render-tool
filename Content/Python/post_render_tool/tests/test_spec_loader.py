"""Pure-Python tests for spec_loader.py — no UE imports. Uses unittest (project convention)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Import spec_loader without touching sibling modules that require unreal.
_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
from spec_loader import (  # noqa: E402
    load_spec,
    validate_spec,
    collect_contract_names,
    SpecValidationError,
)


REQUIRED_NAMES = {
    "btn_recheck", "btn_browse", "txt_file_path",
    "txt_frame_count", "txt_focal_range", "txt_timecode", "txt_sensor_width",
    "spn_fps", "txt_detected_fps",
    "spn_frame", "txt_designer_pos", "txt_designer_rot",
    "txt_ue_pos", "txt_ue_rot", "btn_spawn_cam",
    "cmb_pos_x_src", "spn_pos_x_scale",
    "cmb_pos_y_src", "spn_pos_y_scale",
    "cmb_pos_z_src", "spn_pos_z_scale",
    "cmb_rot_pitch_src", "spn_rot_pitch_scale",
    "cmb_rot_yaw_src", "spn_rot_yaw_scale",
    "cmb_rot_roll_src", "spn_rot_roll_scale",
    "btn_apply_mapping", "btn_save_mapping",
    "btn_import", "btn_open_seq", "btn_open_mrq", "txt_results",
}
OPTIONAL_NAMES = {
    "prereq_label_0", "prereq_label_1", "prereq_label_2",
    "prereq_label_3", "prereq_label_4", "prereq_label_5",
    "prereq_summary", "txt_frame_hint",
}


def _minimal_spec() -> dict:
    return {
        "blueprint": {
            "asset_path": "/PostRenderTool/Blueprints/BP_PostRenderToolWidget",
            "parent_class": "/Script/PostRenderTool.PostRenderToolWidget",
            "root_panel": {"type": "VerticalBox", "name": "RootPanel"},
        },
        "root_children": [
            {
                "type": "TextBlock", "name": "txt_file_path", "role": "required",
                "properties": {"Text": ""},
            },
        ],
    }


class TestSpecLoader(unittest.TestCase):

    def test_load_spec_reads_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.json"
            p.write_text(json.dumps(_minimal_spec()))
            self.assertTrue(
                load_spec(str(p))["blueprint"]["asset_path"].endswith("BP_PostRenderToolWidget")
            )

    def test_load_spec_fails_on_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_spec(str(Path(tmp) / "does-not-exist.json"))

    def test_validate_accepts_minimal_spec(self):
        self.assertEqual(validate_spec(_minimal_spec()), [])

    def test_validate_rejects_missing_blueprint_key(self):
        spec = _minimal_spec()
        del spec["blueprint"]
        errs = validate_spec(spec)
        self.assertTrue(any("blueprint" in e for e in errs), errs)

    def test_validate_rejects_missing_asset_path(self):
        spec = _minimal_spec()
        del spec["blueprint"]["asset_path"]
        errs = validate_spec(spec)
        self.assertTrue(any("asset_path" in e for e in errs), errs)

    def test_validate_rejects_invalid_role(self):
        spec = _minimal_spec()
        spec["root_children"][0]["role"] = "mandatory"  # typo
        errs = validate_spec(spec)
        self.assertTrue(any("role" in e for e in errs), errs)

    def test_validate_rejects_duplicate_names(self):
        spec = _minimal_spec()
        spec["root_children"].append(spec["root_children"][0].copy())
        errs = validate_spec(spec)
        self.assertTrue(any("duplicate" in e.lower() for e in errs), errs)

    def test_validate_rejects_children_on_leaf_type(self):
        spec = _minimal_spec()
        spec["root_children"][0]["children"] = [
            {"type": "TextBlock", "name": "inner", "role": "decorative"}
        ]
        errs = validate_spec(spec)
        self.assertTrue(any("cannot have children" in e.lower() for e in errs), errs)

    def test_collect_contract_names_partitions_correctly(self):
        spec = _minimal_spec()
        spec["root_children"].append(
            {"type": "TextBlock", "name": "prereq_label_0", "role": "optional"}
        )
        spec["root_children"].append(
            {"type": "TextBlock", "name": "lbl_section_csv", "role": "decorative",
             "properties": {"Text": "CSV File"}}
        )
        req, opt, dec = collect_contract_names(spec)
        self.assertEqual(req, {"txt_file_path"})
        self.assertEqual(opt, {"prereq_label_0"})
        self.assertEqual(dec, {"lbl_section_csv"})

    def test_spec_validation_error_is_raised_when_requested(self):
        spec = _minimal_spec()
        del spec["blueprint"]
        with self.assertRaises(SpecValidationError):
            validate_spec(spec, raise_on_error=True)


class TestRealSpecFile(unittest.TestCase):
    """Guards against regressions in docs/widget-tree-spec.json itself."""

    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parents[4]
        cls.spec_path = repo_root / "docs" / "widget-tree-spec.json"
        if not cls.spec_path.exists():
            raise unittest.SkipTest("widget-tree-spec.json not yet authored")
        cls.spec = load_spec(str(cls.spec_path))

    def test_real_spec_file_is_valid(self):
        errs = validate_spec(self.spec)
        self.assertEqual(errs, [], "Spec has errors:\n" + "\n".join(errs))

    def test_real_spec_contract_names_match_hardcoded_sets(self):
        req, opt, _ = collect_contract_names(self.spec)
        self.assertEqual(req, REQUIRED_NAMES, f"Required mismatch: {req ^ REQUIRED_NAMES}")
        self.assertEqual(opt, OPTIONAL_NAMES, f"Optional mismatch: {opt ^ OPTIONAL_NAMES}")


if __name__ == "__main__":
    unittest.main()
