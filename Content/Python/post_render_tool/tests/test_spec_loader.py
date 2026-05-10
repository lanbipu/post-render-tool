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
    "spn_fps",
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
    "lbl_root_scroll",
    "prereq_label_0", "prereq_label_1", "prereq_label_2",
    "prereq_label_3", "prereq_label_4", "prereq_label_5",
    "prereq_summary",
    "spn_rot_pitch_offset", "spn_rot_yaw_offset", "spn_rot_roll_offset",
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


class TestFigmaSpecFile(unittest.TestCase):
    """Validate the side-by-side Figma widget spec without changing legacy drift rules."""

    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parents[4]
        cls.spec_path = repo_root / "docs" / "widget-tree-spec-figma-v2.json"
        if not cls.spec_path.exists():
            raise unittest.SkipTest("widget-tree-spec-figma-v2.json not yet authored")
        cls.spec = load_spec(str(cls.spec_path))

    @staticmethod
    def _walk_nodes(spec):
        stack = list(spec.get("root_children", []))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.get("children") or [])

    def test_figma_spec_file_is_valid(self):
        errs = validate_spec(self.spec)
        self.assertEqual(errs, [], "Figma spec has errors:\n" + "\n".join(errs))

    def test_figma_spec_targets_separate_blueprint(self):
        self.assertEqual(
            self.spec["blueprint"]["asset_path"],
            "/PostRenderTool/Blueprints/BP_PostRenderToolWidget_Figma",
        )
        self.assertEqual(
            self.spec["blueprint"]["parent_class"],
            "/Script/PostRenderTool.PostRenderToolWidget",
        )

    def test_figma_spec_keeps_legacy_required_contract(self):
        req, opt, _dec = collect_contract_names(self.spec)
        self.assertEqual(req, REQUIRED_NAMES)
        self.assertNotIn("spn_frame", opt)
        self.assertNotIn("btn_spawn_cam", opt)

    def test_figma_spec_prerequisites_render_five_rows(self):
        nodes_by_name = {node["name"]: node for node in self._walk_nodes(self.spec)}
        names = set(nodes_by_name)
        self.assertEqual(
            {name for name in names if name.startswith("lbl_prereq_row_")},
            {f"lbl_prereq_row_{i}" for i in range(5)},
        )
        self.assertEqual(
            {name for name in names if name.startswith("prereq_label_")},
            {f"prereq_label_{i}" for i in range(5)},
        )
        label_texts = [
            nodes_by_name[f"prereq_label_{i}"]["properties"]["Text"]
            for i in range(5)
        ]
        self.assertEqual(
            label_texts,
            [
                "OK: Python Editor Script Plugin",
                "OK: Editor Scripting Utilities",
                "OK: CineCameraActor",
                "OK: LevelSequence",
                "OK: EditorUtilitySubsystem",
            ],
        )
        self.assertNotIn("OK: Camera Calibration", label_texts)
        self.assertEqual(
            nodes_by_name["prereq_summary"]["properties"]["Text"],
            "5 / 5 OK",
        )

    def test_figma_spec_prerequisite_dots_are_round(self):
        nodes_by_name = {node["name"]: node for node in self._walk_nodes(self.spec)}
        for index in range(5):
            dot = nodes_by_name[f"lbl_prereq_dot_{index}_img"]
            self.assertEqual(dot["properties"].get("DrawAs"), "RoundedBox")

    def test_figma_spec_excludes_coordinate_verification_section(self):
        names = {node["name"] for node in self._walk_nodes(self.spec)}
        removed_names = {
            "lbl_card_coord_verify",
            "spn_frame",
            "txt_frame_hint",
            "txt_designer_pos",
            "txt_designer_rot",
            "txt_ue_pos",
            "txt_ue_rot",
            "btn_spawn_cam",
        }
        self.assertTrue(names.isdisjoint(removed_names), names & removed_names)

    def test_figma_spec_cards_and_controls_have_outlines(self):
        nodes_by_name = {node["name"]: node for node in self._walk_nodes(self.spec)}
        for name in (
            "lbl_card_prereq",
            "lbl_card_csv_file",
            "lbl_card_csv_preview",
            "lbl_card_axis",
            "lbl_card_actions",
        ):
            self.assertEqual(
                nodes_by_name[name]["properties"]["OutlineSettings"]["Width"],
                1,
            )
        self.assertEqual(
            nodes_by_name["btn_browse"]["properties"]["OutlineSettings"]["Width"],
            1,
        )
        self.assertEqual(
            nodes_by_name["btn_import"]["properties"]["OutlineSettings"]
            ["CornerRadius"],
            4,
        )
        self.assertEqual(
            nodes_by_name["box_txt_results"]["properties"]["OutlineSettings"]
            ["Width"],
            1,
        )
        self.assertEqual(
            nodes_by_name["spn_fps"]["properties"]["FigmaInputStyle"]
            ["OutlineSettings"]["Width"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
