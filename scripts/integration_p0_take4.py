"""P0 integration test — take_4 run_import + verify timecode propagation.

Runs end-to-end inside UE 5.7 Editor on lanPC:
1. Force-reload modified Python modules (timecode / csv_parser / sequence_builder / pipeline / ui_interface).
2. Smoke-check the C++ schema is deployed (PostRenderCameraSamples.start_timecode reflection).
3. Smoke-check WriteCameraSamples UFUNCTION accepts the new 9-arg signature.
4. Run pipeline.run_import on take_4 (50fps).
5. Read back:
   - LevelSequence Camera Cut Section TimecodeSource → start_timecode
   - UPostRenderCameraSection TimecodeSource → start_timecode
   - UPostRenderCameraSamples DataAsset .start_timecode / has_start_timecode
6. Run open_movie_render_queue → verify FrameNumberOffset, FileNameFormat,
   ZeroPadFrameNumbers configured per Task 7 spec.

Output goes to UE Output Log; bridge prints it back via stdout.
"""
import sys


def _verify(label: str, ok: bool, detail: str = "") -> bool:
    """Print PASS/FAIL marker that bridge can grep."""
    import unreal  # type: ignore
    status = "PASS" if ok else "FAIL"
    unreal.log(f"[P0_INTEG] {status} :: {label}" + (f" :: {detail}" if detail else ""))
    return ok


def main() -> None:
    import unreal  # type: ignore
    import importlib

    unreal.log("\n=== P0 Integration Test (take_4, 50fps) ===")

    # ---------- 0. Reload modified Python modules ----------
    for mod_name in (
        "post_render_tool.timecode",
        "post_render_tool.csv_parser",
        "post_render_tool.validator",
        "post_render_tool.sequence_builder",
        "post_render_tool.ui_interface",
        "post_render_tool.pipeline",
    ):
        try:
            mod = __import__(mod_name, fromlist=["_"])
            importlib.reload(mod)
            unreal.log(f"[P0_INTEG] reloaded {mod_name}")
        except Exception as e:
            _verify(f"reload {mod_name}", False, str(e))
            return

    # ---------- 1. Schema smoke check ----------
    samples_cls = getattr(unreal, "PostRenderCameraSamples", None)
    _verify("unreal.PostRenderCameraSamples exposed", samples_cls is not None)
    if samples_cls is None:
        return

    # Check the new DataAsset fields are visible to Python (BlueprintReadOnly
    # ⇒ should appear in dir())
    samples_dir = dir(samples_cls)
    _verify("PostRenderCameraSamples.start_timecode field",
            "start_timecode" in samples_dir,
            f"dir has: {[d for d in samples_dir if 'timecode' in d.lower() or 'schema' in d.lower()]}")
    _verify("PostRenderCameraSamples.has_start_timecode field",
            "has_start_timecode" in samples_dir)

    # ---------- 2. Run pipeline ----------
    csv_path = (
        r"E:/RenderStream Projects/test_0311/Plugins/post-render-tool/"
        r"reference/test_take_4_dense.csv"
    )

    from post_render_tool.pipeline import run_import
    try:
        result = run_import(csv_path, fps=50.0)
    except Exception as e:
        _verify("run_import succeeds", False, repr(e))
        import traceback
        traceback.print_exc()
        return

    _verify("run_import succeeds", result.success,
            getattr(result, "error_message", "") or "")
    if not result.success or result.level_sequence is None:
        return

    ls = result.level_sequence
    ls_path = ls.get_path_name()
    unreal.log(f"[P0_INTEG] LevelSequence: {ls_path}")

    # ---------- 3. Verify Camera Cut Section TimecodeSource ----------
    cc_track_found = False
    cc_tc_set = False
    cc_tc_str = ""
    for track in ls.get_tracks():
        if track.get_class().get_name() == "MovieSceneCameraCutTrack":
            cc_track_found = True
            for section in track.get_sections():
                tcs = section.get_editor_property("timecode_source")
                if tcs is None:
                    continue
                tc = tcs.get_editor_property("timecode")
                if tc is None:
                    continue
                h = tc.get_editor_property("hours")
                m = tc.get_editor_property("minutes")
                s = tc.get_editor_property("seconds")
                f = tc.get_editor_property("frames")
                cc_tc_str = f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"
                # Anything non-zero = set; we'll compare to DataAsset below
                if (h, m, s, f) != (0, 0, 0, 0):
                    cc_tc_set = True
    _verify("Camera Cut Track exists", cc_track_found)
    _verify("Camera Cut Section TimecodeSource set", cc_tc_set, cc_tc_str)

    # ---------- 4. Verify UPostRenderCameraSection TimecodeSource ----------
    prc_track_found = False
    prc_tc_set = False
    prc_tc_str = ""
    for binding in ls.get_bindings():
        for track in binding.get_tracks():
            if track.get_class().get_name() != "PostRenderCameraTrack":
                continue
            prc_track_found = True
            for section in track.get_sections():
                tcs = section.get_editor_property("timecode_source")
                if tcs is None:
                    continue
                tc = tcs.get_editor_property("timecode")
                h = tc.get_editor_property("hours")
                m = tc.get_editor_property("minutes")
                s = tc.get_editor_property("seconds")
                f = tc.get_editor_property("frames")
                prc_tc_str = f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"
                if (h, m, s, f) != (0, 0, 0, 0):
                    prc_tc_set = True
    _verify("PostRenderCameraTrack exists", prc_track_found)
    _verify("UPostRenderCameraSection TimecodeSource set", prc_tc_set, prc_tc_str)

    # ---------- 5. Verify DataAsset canonical StartTimecode ----------
    samples_path = ls_path.replace("LS_", "LS_").replace(
        ls.get_name(), ls.get_name() + "_Samples"
    )
    # That replace is a no-op when name doesn't contain LS_; rebuild from
    # asset path convention used in sequence_builder.
    samples_obj_path = (
        ls_path.rsplit(".", 1)[0] + "_Samples." + ls.get_name() + "_Samples"
    )
    samples_asset_str = ls_path.rsplit(".", 1)[0] + "_Samples"
    samples_asset = unreal.EditorAssetLibrary.load_asset(samples_asset_str)
    _verify("sample DataAsset exists", samples_asset is not None,
            samples_asset_str)
    if samples_asset is None:
        return

    has_tc = samples_asset.has_start_timecode
    da_tc = samples_asset.start_timecode
    da_h = da_tc.get_editor_property("hours")
    da_m = da_tc.get_editor_property("minutes")
    da_s = da_tc.get_editor_property("seconds")
    da_f = da_tc.get_editor_property("frames")
    da_str = f"{da_h:02d}:{da_m:02d}:{da_s:02d}:{da_f:02d}"
    _verify("DataAsset bHasStartTimecode = True", bool(has_tc))
    _verify("DataAsset StartTimecode != 00:00:00:00",
            (da_h, da_m, da_s, da_f) != (0, 0, 0, 0), da_str)

    # ---------- 6. Cross-check: all three timecodes match ----------
    all_equal = (cc_tc_str == prc_tc_str == da_str) and cc_tc_str != ""
    _verify("CameraCut / PostRenderCamera / DataAsset timecodes match",
            all_equal,
            f"cc={cc_tc_str} prc={prc_tc_str} da={da_str}")

    # ---------- 7. MRQ FrameNumberOffset ----------
    from post_render_tool.ui_interface import open_movie_render_queue
    try:
        open_movie_render_queue(ls)
    except Exception as e:
        _verify("open_movie_render_queue runs", False, repr(e))
        return
    _verify("open_movie_render_queue runs", True)

    # Read back the job we just created
    queue_subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    queue = queue_subsystem.get_queue()
    jobs = queue.get_jobs()
    if not jobs:
        _verify("MRQ queue has at least 1 job", False)
        return
    job = jobs[-1]   # the one we just created
    output_setting = job.get_configuration().find_or_add_setting_by_class(
        unreal.MoviePipelineOutputSetting
    )
    fno = output_setting.get_editor_property("frame_number_offset")
    fnf = output_setting.get_editor_property("file_name_format")
    pad = output_setting.get_editor_property("zero_pad_frame_numbers")
    first_frame = int(samples_asset.source_frame_numbers[0])

    # SchemaVersion 3 invariant: SourceFrameNumbers[0] = timecode.to_frames()
    # take_4 trimmed start = 09:44:25:10 @ 50fps =
    # 50 * (9*3600 + 44*60 + 25) + 10 = 1753260
    expected_tc_frame = 50 * (9 * 3600 + 44 * 60 + 25) + 10
    _verify("DataAsset SchemaVersion = 3",
            int(samples_asset.schema_version) == 3,
            str(samples_asset.schema_version))
    _verify("SourceFrameNumbers[0] = timecode-derived (not CSV frame col)",
            first_frame == expected_tc_frame,
            f"got={first_frame}, expected={expected_tc_frame}")
    # FrameNumberOffset is now hardcoded 0 (sequence frame is already absolute)
    _verify("MRQ FrameNumberOffset = 0 (sequence frame is absolute)",
            int(fno) == 0, f"got={fno}")
    _verify("MRQ FileNameFormat contains {frame_number}",
            "{frame_number}" in str(fnf), repr(fnf))
    _verify("MRQ ZeroPadFrameNumbers >= 7",
            int(pad) >= 7, str(pad))

    # ---------- 8. G6 strict-mode SMPTE drift fail-fast ----------
    # Disguise dual-stream exports (timestamp = wall-clock SMPTE,
    # frame = free-running counter) commonly drift by design. Default
    # parse_csv_dense mode logs a warning and continues. Only the opt-in
    # strict_timecode=True mode raises CsvTimecodeMismatch.
    #
    # This probe builds a CSV with drift and asserts:
    #   - default mode: parse succeeds + warning logged (no exception)
    #   - strict_timecode=True: raises CsvTimecodeMismatch
    from post_render_tool.csv_parser import (
        parse_csv_dense, CsvTimecodeMismatch,
    )
    import os
    drift_path = r"C:/temp/ue-remote/take_4_drift.csv"
    try:
        with open(csv_path, "r") as fh:
            lines = fh.readlines()
        # Find the first data row with >= 2 columns and a valid integer frame
        # number; drift its frame_number by +1.
        for i in range(1, len(lines)):
            row = lines[i].split(",")
            if len(row) < 2:
                continue
            try:
                new_frame = int(row[1].strip()) + 1
            except (ValueError, IndexError):
                continue
            row[1] = str(new_frame)
            lines[i] = ",".join(row)
            unreal.log(f"[P0_INTEG] drift CSV: row {i} frame +1 → {new_frame}")
            break
        with open(drift_path, "w") as fh:
            fh.writelines(lines)

        # Default mode: drift should NOT raise
        try:
            parse_csv_dense(drift_path, fps=50.0)
            _verify("G6 default tolerant mode parses drifted CSV", True)
        except CsvTimecodeMismatch as e:
            _verify("G6 default tolerant mode parses drifted CSV", False,
                    f"unexpected raise: {str(e)[:80]}")

        # Strict mode: drift SHOULD raise
        try:
            parse_csv_dense(drift_path, fps=50.0, strict_timecode=True)
            _verify("G6 strict mode fail-fast", False, "no exception raised")
        except CsvTimecodeMismatch as e:
            _verify("G6 strict mode fail-fast (CsvTimecodeMismatch)", True,
                    str(e)[:100])
    finally:
        try:
            os.unlink(drift_path)
        except Exception:
            pass

    unreal.log("\n=== P0 Integration Test DONE ===")


if __name__ == "__main__":
    main()
