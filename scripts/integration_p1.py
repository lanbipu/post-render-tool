"""P1 integration test — run_patch_exr_timecode + run_export_otio.

Pre-requisite: take_4 already imported (LevelSequence + sample DataAsset
at /Game/PostRender/test_take_4_dense/). P0 集成测试已 set up。

Steps:
1. Reload modified Python modules (post_render_tool.*).
2. Generate a mock MRQ-style EXR sequence in `C:/temp/p1_test/`,
   filenames matching what MRQ would produce with FrameNumberOffset
   (e.g. `LS_test_take_4_dense.0625994.exr` if file_name_format is
   `{sequence_name}.{frame_number}`).
3. Call open_movie_render_queue to set up MRQ output_setting (so
   derive_mrq_filename_pattern can read it).
4. Call run_patch_exr_timecode, verify EXR header has typed timecode.
5. Call run_export_otio, verify .otio file written + parseable.
"""
import unreal  # type: ignore


def _verify(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    unreal.log(f"[P1_INTEG] {status} :: {label}" + (f" :: {detail}" if detail else ""))
    return ok


def main() -> None:
    import importlib
    import os
    import shutil
    import subprocess

    unreal.log("\n=== P1 Integration Test ===")

    # Reload modified modules.
    for mod_name in (
        "post_render_tool.timecode",
        "post_render_tool.csv_parser",
        "post_render_tool.validator",
        "post_render_tool.sequence_builder",
        "post_render_tool.exr_timecode_writer",
        "post_render_tool.otio_export",
        "post_render_tool.ui_interface",
        "post_render_tool.pipeline",
    ):
        try:
            mod = __import__(mod_name, fromlist=["_"])
            importlib.reload(mod)
            unreal.log(f"[P1_INTEG] reloaded {mod_name}")
        except Exception as e:
            _verify(f"reload {mod_name}", False, str(e))
            return

    # Verify imported LevelSequence is available
    ls_path = "/Game/PostRender/test_take_4_dense/LS_test_take_4_dense"
    ls = unreal.EditorAssetLibrary.load_asset(ls_path)
    if ls is None:
        _verify("take_4 LevelSequence exists", False,
                "rerun P0 integration first to import take_4")
        return
    _verify("take_4 LevelSequence exists", True)

    # Set up MRQ job so derive_mrq_filename_pattern has data to read.
    from post_render_tool.ui_interface import (
        open_movie_render_queue, derive_mrq_filename_pattern,
    )
    open_movie_render_queue(ls)
    pattern, pad = derive_mrq_filename_pattern(ls_path)
    _verify("derive_mrq_filename_pattern returns pattern", bool(pattern), pattern)
    _verify("derive_mrq_filename_pattern returns padding", pad > 0, str(pad))

    # Common setup for both EXR + OTIO paths.
    test_dir = r"C:/temp/p1_test"
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir)

    samples = unreal.EditorAssetLibrary.load_asset(ls_path + "_Samples")
    first_frame = int(samples.source_frame_numbers[0])

    have_oiiotool = shutil.which("oiiotool") is not None
    have_exrheader = shutil.which("exrheader") is not None
    if not have_oiiotool:
        unreal.log_warning(
            "[P1_INTEG] oiiotool not on lanPC PATH — EXR patcher tests "
            "SKIPPED. Run `scoop install openimageio` on lanPC."
        )

    if have_oiiotool:
        # Generate mock EXR matching derived pattern.
        for offset in range(3):
            frame = first_frame + offset
            filename = pattern.format(frame=frame)
            fpath = os.path.join(test_dir, filename)
            try:
                subprocess.check_call([
                    "oiiotool", "--create", "4x4", "3",
                    "--fill:color=0.5,0.5,0.5", "4x4",
                    "-o", fpath,
                ])
            except Exception as e:
                _verify(f"generate mock EXR offset={offset}", False, str(e))
                return
        _verify("generated 3 mock EXR files", True, test_dir)

        from post_render_tool.pipeline import run_patch_exr_timecode
        try:
            res = run_patch_exr_timecode(ls_path, test_dir, pattern)
            _verify("run_patch_exr_timecode runs", True)
            _verify("patched_count == 3", res["patched_count"] == 3,
                    f"got {res['patched_count']}")
            _verify("start_timecode reported",
                    res["start_timecode"] == "09:44:25:10",
                    f"got {res['start_timecode']}")
        except Exception as e:
            _verify("run_patch_exr_timecode runs", False, repr(e))
            return

        if have_exrheader:
            first_filename = pattern.format(frame=first_frame)
            first_path = os.path.join(test_dir, first_filename)
            try:
                out = subprocess.check_output(
                    ["exrheader", first_path], text=True,
                    stderr=subprocess.STDOUT,
                )
                has_typed_tc = any(
                    "type timecode" in line.lower() for line in out.splitlines()
                )
                _verify("EXR has typed timeCode attribute", has_typed_tc)
                has_rational_fps = any(
                    "framespersecond" in line.lower() and "rational" in line.lower()
                    for line in out.splitlines()
                )
                _verify("EXR has rational FramesPerSecond", has_rational_fps)
            except Exception as e:
                _verify("exrheader read", False, str(e))

    # Run run_export_otio.
    from post_render_tool.pipeline import run_export_otio
    sidecar = os.path.join(test_dir, "test_take_4.otio")
    try:
        res2 = run_export_otio(ls_path, test_dir, sidecar, pattern)
        _verify("run_export_otio runs", True)
        _verify("OTIO sidecar file exists", os.path.exists(sidecar))
        _verify("OTIO frame_count > 0", res2["frame_count"] > 0,
                str(res2["frame_count"]))
    except Exception as e:
        _verify("run_export_otio runs", False, repr(e))

    # Cleanup
    shutil.rmtree(test_dir, ignore_errors=True)
    unreal.log("\n=== P1 Integration Test DONE ===")


if __name__ == "__main__":
    main()
