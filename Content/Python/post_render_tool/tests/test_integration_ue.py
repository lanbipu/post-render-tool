"""Integration tests — run inside UE Editor Python console.

Usage in UE Output Log:
  py exec(open('Content/Python/post_render_tool/tests/test_integration_ue.py').read())
"""
import os
import unreal

# Update this to your reference CSV path
CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "reference", "shot 1_take_5_dense.csv"
)


def test_csv_parse():
    from post_render_tool.csv_parser import parse_csv_dense
    result = parse_csv_dense(CSV_PATH)
    assert result.frame_count > 0, f"Expected frames, got {result.frame_count}"
    assert result.camera_prefix.startswith("camera:"), f"Wrong prefix: {result.camera_prefix}"
    assert abs(result.sensor_width_mm - 35.0) < 0.01
    unreal.log("PASS: CSV parse")


def test_coordinate_sanity():
    from post_render_tool.csv_parser import parse_csv_dense
    from post_render_tool.coordinate_transform import transform_position
    csv_result = parse_csv_dense(CSV_PATH)
    frame = csv_result.frames[0]
    ue_x, ue_y, ue_z = transform_position(frame.offset_x, frame.offset_y, frame.offset_z)
    unreal.log(f"  Designer: ({frame.offset_x}, {frame.offset_y}, {frame.offset_z}) m")
    unreal.log(f"  UE: ({ue_x:.1f}, {ue_y:.1f}, {ue_z:.1f}) cm")
    assert any(abs(v) > 0.1 for v in (ue_x, ue_y, ue_z)), "All UE positions near zero"
    assert all(abs(v) < 100000 for v in (ue_x, ue_y, ue_z)), "UE position out of range"
    unreal.log("PASS: Coordinate sanity")


def test_full_pipeline():
    from post_render_tool.pipeline import run_import
    result = run_import(CSV_PATH, fps=24.0)
    assert result.success, f"Pipeline failed: {result.error_message}"
    assert result.lens_file is not None
    assert result.camera_actor is not None
    assert result.level_sequence is not None
    assert result.report is not None
    comp = result.camera_actor.get_cine_camera_component()
    sw = comp.filmback.sensor_width
    assert abs(sw - 35.0) < 0.01, f"Sensor width wrong: {sw}"
    unreal.log(result.report.format_report())
    unreal.log("PASS: Full pipeline")


def run_all():
    unreal.log("=== Integration Tests ===")
    test_csv_parse()
    test_coordinate_sanity()
    test_full_pipeline()
    unreal.log("=== All Integration Tests Passed ===")


run_all()
