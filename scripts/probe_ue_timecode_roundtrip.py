"""Task 4 path decision — does Python set_editor_property('timecode_source', ...)
actually round-trip on a real MovieSceneSection?

Creates a transient LevelSequence + CameraCutSection, builds a
MovieSceneTimecodeSource from python, set_editor_property, read back via
get_editor_property, compares, then deletes the transient asset.

Run via run_ue.py bridge (lanPC).
"""
import unreal  # type: ignore


TRANSIENT_PATH = "/Game/_TempTcProbe"
TRANSIENT_NAME = "TestTimecodeRoundtrip"


def _enumerate_fields(cls_name: str) -> str:
    cls = getattr(unreal, cls_name, None)
    if cls is None:
        return f"{cls_name} NOT FOUND"
    return ", ".join(sorted(n for n in dir(cls) if not n.startswith("_")))


def main() -> None:
    unreal.log("\n=== Task 4 Roundtrip Probe ===")
    unreal.log("Timecode struct dir(): " + _enumerate_fields("Timecode"))
    unreal.log("MovieSceneTimecodeSource struct dir(): "
               + _enumerate_fields("MovieSceneTimecodeSource"))

    # 1. Build transient LevelSequence
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    full_path = f"{TRANSIENT_PATH}/{TRANSIENT_NAME}"
    if unreal.EditorAssetLibrary.does_asset_exist(full_path):
        unreal.EditorAssetLibrary.delete_asset(full_path)

    seq = asset_tools.create_asset(
        TRANSIENT_NAME,
        TRANSIENT_PATH,
        unreal.LevelSequence,
        unreal.LevelSequenceFactoryNew(),
    )
    if seq is None:
        unreal.log_error("FAIL: could not create transient LevelSequence")
        return

    # 2. Add Camera Cut Track + Section
    track = seq.add_track(unreal.MovieSceneCameraCutTrack)
    section = track.add_section()

    # 3. Construct MovieSceneTimecodeSource — try several field-name conventions
    # because UE Python snake-cases differently for bool vs non-bool fields.
    tc_attempts = []
    try:
        tc = unreal.Timecode()
        tc.set_editor_property("hours", 10)
        tc.set_editor_property("minutes", 30)
        tc.set_editor_property("seconds", 45)
        tc.set_editor_property("frames", 22)
        # Try both possible bool field names
        for bool_name in ("drop_frame_format", "b_drop_frame_format"):
            try:
                tc.set_editor_property(bool_name, False)
                tc_attempts.append(f"set Timecode.{bool_name} OK")
                break
            except Exception as e:
                tc_attempts.append(f"set Timecode.{bool_name} FAIL: {e}")
        unreal.log("Timecode construction attempts: " + " | ".join(tc_attempts))
        unreal.log(f"Timecode after set: hours={tc.get_editor_property('hours')}, "
                   f"minutes={tc.get_editor_property('minutes')}, "
                   f"seconds={tc.get_editor_property('seconds')}, "
                   f"frames={tc.get_editor_property('frames')}")
    except Exception as e:
        unreal.log_error(f"FAIL constructing Timecode: {e}")
        unreal.EditorAssetLibrary.delete_asset(full_path)
        return

    # 4. Wrap in MovieSceneTimecodeSource
    try:
        src = unreal.MovieSceneTimecodeSource()
        src.set_editor_property("timecode", tc)
        unreal.log(
            "MovieSceneTimecodeSource.timecode set via set_editor_property OK"
        )
    except Exception as e:
        unreal.log_error(f"FAIL wrapping in MovieSceneTimecodeSource: {e}")
        unreal.EditorAssetLibrary.delete_asset(full_path)
        return

    # 5. Try set_editor_property on Section
    try:
        section.set_editor_property("timecode_source", src)
        unreal.log("Section.set_editor_property('timecode_source', ...) OK")
    except Exception as e:
        unreal.log_error(f"FAIL Section.set_editor_property: {e}")
        unreal.EditorAssetLibrary.delete_asset(full_path)
        return

    # 6. Read back
    try:
        got = section.get_editor_property("timecode_source")
        got_tc = got.get_editor_property("timecode")
        gh = got_tc.get_editor_property("hours")
        gm = got_tc.get_editor_property("minutes")
        gs = got_tc.get_editor_property("seconds")
        gf = got_tc.get_editor_property("frames")
        unreal.log(
            f"Roundtrip OK: read back H={gh} M={gm} S={gs} F={gf} "
            f"(expected H=10 M=30 S=45 F=22)"
        )
        if (gh, gm, gs, gf) == (10, 30, 45, 22):
            unreal.log("=== VERDICT: Python native path WORKS — Task 4 wrapper UNNECESSARY ===")
        else:
            unreal.log("=== VERDICT: VALUES DRIFTED — write C++ wrapper ===")
    except Exception as e:
        unreal.log_error(f"FAIL reading back: {e}")
    finally:
        unreal.EditorAssetLibrary.delete_asset(full_path)
        unreal.log("transient asset cleaned up\n")


if __name__ == "__main__":
    main()
