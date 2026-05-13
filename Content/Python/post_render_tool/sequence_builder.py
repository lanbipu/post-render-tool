"""Level Sequence builder: Disguise Designer CSV → UE LevelSequence asset.

Path (since 2026-05-13): one UPostRenderCameraTrack per LevelSequence, backed
by a UPostRenderCameraSamples DataAsset. The 19-Float-Track + 1-Transform-Track
path was retired to fix 68k-frame import + scrub stutter (see
docs/superpowers/plans/2026-05-13-custom-moviescene-track.md).

NOTE: This module is designed to run inside the Unreal Editor Python
environment. The `unreal` module is not available outside UE.
"""

from __future__ import annotations

import unreal

from .csv_parser import CsvDenseResult, csv_overscan_to_ue_overscan
from .sample_packer import pack_samples


# ---------------------------------------------------------------------------
# FPS helpers
# ---------------------------------------------------------------------------

_FRACTIONAL_FPS: dict[float, tuple[int, int]] = {
    23.976: (24000, 1001),
    29.97:  (30000, 1001),
    59.94:  (60000, 1001),
}


def _resolve_frame_rate(fps: float) -> tuple[int, int]:
    """Return (numerator, denominator) for a given FPS value."""
    for known_fps, fraction in _FRACTIONAL_FPS.items():
        if abs(fps - known_fps) < 0.01:
            return fraction
    return (int(fps), 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_sequence(
    csv_result: CsvDenseResult,
    camera_actor: unreal.CameraActor,
    fps: float,
    asset_name: str,
    package_path: str,
) -> unreal.LevelSequence:
    """Build/refresh a LevelSequence + sample DataAsset from parsed CSV data.

    Produces:
      - {package_path}/{asset_name}              : LevelSequence
      - {package_path}/{asset_name}_Samples      : UPostRenderCameraSamples
    """
    # ------------------------------------------------------------------
    # Step 0: Pre-validate per-frame derived values that may raise (overscan).
    # ------------------------------------------------------------------
    for frame in csv_result.frames:
        csv_overscan_to_ue_overscan(
            frame.overscan_x, frame.overscan_y, frame_number=frame.frame_number
        )

    # ------------------------------------------------------------------
    # Step 1: Create or reuse LevelSequence asset (idempotent)
    # ------------------------------------------------------------------
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    full_sequence_path = f"{package_path}/{asset_name}"

    if unreal.EditorAssetLibrary.does_asset_exist(full_sequence_path):
        level_sequence = unreal.EditorAssetLibrary.load_asset(full_sequence_path)
        if level_sequence is None:
            raise RuntimeError(
                f"LevelSequence 资产存在但 load 失败: {full_sequence_path}"
            )
        existing_bindings = list(level_sequence.get_bindings())
        for binding in existing_bindings:
            binding.remove()
        existing_tracks = list(level_sequence.get_tracks())
        for track in existing_tracks:
            level_sequence.remove_track(track)
        unreal.log(
            f"[post_render_tool] LevelSequence 已存在,清空 "
            f"{len(existing_bindings)} 个 bindings + {len(existing_tracks)} 个 "
            f"master tracks 后重建: {full_sequence_path}"
        )
    else:
        level_sequence = asset_tools.create_asset(
            asset_name,
            package_path,
            unreal.LevelSequence,
            unreal.LevelSequenceFactoryNew(),
        )
        if level_sequence is None:
            raise RuntimeError(
                f"LevelSequence 资产创建失败: {full_sequence_path}"
            )

    # ------------------------------------------------------------------
    # Step 2: Set frame rate
    # ------------------------------------------------------------------
    numerator, denominator = _resolve_frame_rate(fps)
    level_sequence.set_display_rate(
        unreal.FrameRate(numerator=numerator, denominator=denominator)
    )

    # ------------------------------------------------------------------
    # Step 3: Set playback range (preserve original frame cadence)
    # ------------------------------------------------------------------
    first_frame_num = csv_result.frames[0].frame_number
    last_frame_num = csv_result.frames[-1].frame_number
    frame_span = last_frame_num - first_frame_num + 1
    level_sequence.set_playback_start(0)
    level_sequence.set_playback_end(frame_span)

    # ------------------------------------------------------------------
    # Step 4: Bind camera actor as possessable + Camera Cut Track
    # ------------------------------------------------------------------
    camera_binding = level_sequence.add_possessable(camera_actor)
    camera_cut_track = level_sequence.add_track(unreal.MovieSceneCameraCutTrack)
    camera_cut_section = camera_cut_track.add_section()
    camera_cut_section.set_range(0, frame_span)
    camera_cut_section.set_camera_binding_id(
        level_sequence.get_binding_id(camera_binding)
    )

    # ------------------------------------------------------------------
    # Step 5: Build sample DataAsset
    # ------------------------------------------------------------------
    samples_asset_name = f"{asset_name}_Samples"
    samples_asset_full_path = f"{package_path}/{samples_asset_name}"

    # UDataAsset 没默认 UFactory, AssetTools.create_asset(..., None) 会失败.
    # 走 BuildHelper C++ 侧的 CreateOrLoadCameraSamplesAsset (用 CreatePackage +
    # NewObject 直接建资产, find-or-create 都覆盖).
    samples_asset = unreal.PostRenderToolBuildHelper.create_or_load_camera_samples_asset(
        package_path,
        samples_asset_name,
    )
    if samples_asset is None:
        raise RuntimeError(
            f"UPostRenderCameraSamples 资产创建失败: {samples_asset_full_path}"
        )

    # Pack CSV frames into (frame_numbers, sample_dicts).
    frame_numbers, sample_dicts = pack_samples(csv_result.frames)

    # Convert sample dicts → list[unreal.PostRenderCameraSample]
    sample_structs = []
    for d in sample_dicts:
        s = unreal.PostRenderCameraSample()
        s.set_editor_property("location_x",        d["location_x"])
        s.set_editor_property("location_y",        d["location_y"])
        s.set_editor_property("location_z",        d["location_z"])
        s.set_editor_property("rotation_pitch",    d["rotation_pitch"])
        s.set_editor_property("rotation_yaw",      d["rotation_yaw"])
        s.set_editor_property("rotation_roll",     d["rotation_roll"])
        s.set_editor_property("focal_length_mm",   d["focal_length_mm"])
        s.set_editor_property("aperture",          d["aperture"])
        s.set_editor_property("focus_distance_cm", d["focus_distance_cm"])
        s.set_editor_property("sensor_horizontal_offset_mm", d["sensor_horizontal_offset_mm"])
        s.set_editor_property("sensor_vertical_offset_mm", d["sensor_vertical_offset_mm"])
        s.set_editor_property("overscan",          d["overscan"])
        s.set_editor_property("k1",                d["k1"])
        s.set_editor_property("k2",                d["k2"])
        s.set_editor_property("k3",                d["k3"])
        s.set_editor_property("aspect",            d["aspect"])
        sample_structs.append(s)

    # One-shot write.
    ok = unreal.PostRenderToolBuildHelper.write_camera_samples(
        samples_asset,
        frame_numbers,
        sample_structs,
        numerator,
        denominator,
        csv_result.file_path,
    )
    if not ok:
        raise RuntimeError(
            "WriteCameraSamples 失败 — 检查 UE Log 看 length / frame rate 校验"
        )
    unreal.EditorAssetLibrary.save_asset(samples_asset_full_path)
    unreal.log(
        f"[post_render_tool] sample DataAsset 写入完成: "
        f"{samples_asset_full_path} ({len(sample_structs)} 帧)"
    )

    # ------------------------------------------------------------------
    # Step 6: Attach UPostRenderCameraTrack + Section to camera binding
    # ------------------------------------------------------------------
    section = unreal.PostRenderToolBuildHelper.ensure_post_render_camera_track_on_binding(
        level_sequence,
        camera_binding.get_id(),
        0,           # section start (display-rate frame)
        frame_span,  # section end
    )
    if section is None:
        raise RuntimeError(
            "EnsurePostRenderCameraTrackOnBinding 返回 None — 检查 UE Log"
        )
    section.set_editor_property("sample_asset", samples_asset)

    # ------------------------------------------------------------------
    # Step 7: Save and log
    # ------------------------------------------------------------------
    unreal.EditorAssetLibrary.save_asset(full_sequence_path)

    unreal.log(
        f"[post_render_tool] LevelSequence 创建完成: {full_sequence_path}  "
        f"sample 数 {len(sample_structs)},帧跨度 {frame_span},"
        f"帧率 {fps} fps ({numerator}/{denominator})"
    )

    return level_sequence
