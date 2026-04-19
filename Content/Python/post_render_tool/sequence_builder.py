"""Level Sequence builder: Disguise Designer CSV → UE LevelSequence asset.

Converts per-frame camera data (position, rotation, focal length, aperture,
focus distance) into a UE LevelSequence with animated tracks.

NOTE: This module is designed to run inside the Unreal Editor Python
environment. The `unreal` module is not available outside UE.
"""

from __future__ import annotations

import unreal

from .coordinate_transform import (
    transform_focus_distance,
    transform_position,
    transform_rotation,
)
from .csv_parser import CsvDenseResult


# ---------------------------------------------------------------------------
# FPS helpers
# ---------------------------------------------------------------------------

_FRACTIONAL_FPS: dict[float, tuple[int, int]] = {
    23.976: (24000, 1001),
    29.97:  (30000, 1001),
    59.94:  (60000, 1001),
}


def _resolve_frame_rate(fps: float) -> tuple[int, int]:
    """Return (numerator, denominator) for a given FPS value.

    Handles common drop-frame rates; falls back to (int(fps), 1).
    """
    # Match against known fractional rates with small tolerance
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
    """Build and save a LevelSequence asset from parsed CSV camera data.

    Parameters
    ----------
    csv_result:
        Parsed output from ``csv_parser.parse_csv_dense``.
    camera_actor:
        The UE CameraActor to animate (must already exist in the level).
    fps:
        Playback frame rate (e.g. 23.976, 24.0, 29.97).
    asset_name:
        Name for the new LevelSequence asset.
    package_path:
        Content-browser package path (e.g. ``"/Game/Sequences"``).

    Returns
    -------
    unreal.LevelSequence
        The created and saved LevelSequence asset.
    """
    # ------------------------------------------------------------------
    # Step 1: Create LevelSequence asset
    # ------------------------------------------------------------------
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    level_sequence: unreal.LevelSequence = asset_tools.create_asset(
        asset_name,
        package_path,
        unreal.LevelSequence,
        unreal.LevelSequenceFactoryNew(),
    )

    # ------------------------------------------------------------------
    # Step 2: Set frame rate
    # ------------------------------------------------------------------
    # UE 5.7: UMovieScene 的 SetDisplayRate / SetPlaybackRange / AddPossessable
    # 都是 inline / 非 UFUNCTION，Python 不可见。走 MovieSceneSequenceExtensions
    # 提供的 ScriptMethod UFUNCTION，挂在 UMovieSceneSequence（LevelSequence）上。
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
    # Step 4: Bind camera actor and CineCameraComponent as possessables
    # ------------------------------------------------------------------
    camera_binding: unreal.MovieSceneBindingProxy = level_sequence.add_possessable(
        camera_actor
    )

    cine_comp = camera_actor.get_cine_camera_component()
    comp_binding: unreal.MovieSceneBindingProxy = level_sequence.add_possessable(
        cine_comp
    )

    # ------------------------------------------------------------------
    # Step 5: Add tracks and sections
    # ------------------------------------------------------------------

    # --- Transform track on camera actor ---
    transform_track: unreal.MovieScene3DTransformTrack = camera_binding.add_track(
        unreal.MovieScene3DTransformTrack
    )
    transform_section: unreal.MovieScene3DTransformSection = (
        transform_track.add_section()
    )
    transform_section.set_range(0, frame_span)

    # --- Float tracks on CineCameraComponent ---
    def _add_float_track(
        binding: unreal.MovieSceneBindingProxy,
        prop_name: str,
        prop_path: str,
    ) -> unreal.MovieSceneFloatSection:
        track: unreal.MovieSceneFloatTrack = binding.add_track(
            unreal.MovieSceneFloatTrack
        )
        track.set_property_name_and_path(prop_name, prop_path)
        section: unreal.MovieSceneFloatSection = track.add_section()
        section.set_range(0, frame_span)
        return section

    focal_section = _add_float_track(
        comp_binding,
        "CurrentFocalLength",
        "CurrentFocalLength",
    )
    aperture_section = _add_float_track(
        comp_binding,
        "CurrentAperture",
        "CurrentAperture",
    )
    focus_section = _add_float_track(
        comp_binding,
        "ManualFocusDistance",
        "FocusSettings.ManualFocusDistance",
    )

    # ------------------------------------------------------------------
    # Step 6: Write keyframes
    # ------------------------------------------------------------------

    # Transform channels layout:
    #   [0] Location X, [1] Location Y, [2] Location Z
    #   [3] Roll,       [4] Pitch,      [5] Yaw
    transform_channels = transform_section.get_all_channels()
    ch_loc_x  = transform_channels[0]
    ch_loc_y  = transform_channels[1]
    ch_loc_z  = transform_channels[2]
    ch_roll   = transform_channels[3]
    ch_pitch  = transform_channels[4]
    ch_yaw    = transform_channels[5]

    # Float section channels (single channel each)
    focal_channels    = focal_section.get_all_channels()
    aperture_channels = aperture_section.get_all_channels()
    focus_channels    = focus_section.get_all_channels()
    ch_focal    = focal_channels[0]
    ch_aperture = aperture_channels[0]
    ch_focus    = focus_channels[0]

    interp = unreal.MovieSceneKeyInterpolation.LINEAR

    # Pre-allocate once to avoid 2N TransformConfig instantiations in the loop
    from .coordinate_transform import TransformConfig
    xform_cfg = TransformConfig()

    for frame in csv_result.frames:
        # Use original frame number offset from first frame to preserve cadence
        seq_frame_idx = frame.frame_number - first_frame_num
        frame_number = unreal.FrameNumber(seq_frame_idx)

        # Position: Designer (m) → UE (cm), axis remapped
        ue_x, ue_y, ue_z = transform_position(
            frame.offset_x, frame.offset_y, frame.offset_z, cfg=xform_cfg
        )
        # UE 5.7 AddKey 签名: (in_time, new_value, sub_frame=0.0,
        # time_unit=DisplayRate, in_interpolation=Auto)。interpolation 是第 5 位，
        # 必须用关键字参数，否则会被当 sub_frame (float) 报类型错。
        ch_loc_x.add_key(frame_number, ue_x, interpolation=interp)
        ch_loc_y.add_key(frame_number, ue_y, interpolation=interp)
        ch_loc_z.add_key(frame_number, ue_z, interpolation=interp)

        # Rotation: Designer → UE (pitch, yaw, roll)
        pitch, yaw, roll = transform_rotation(
            frame.rotation_x, frame.rotation_y, frame.rotation_z, cfg=xform_cfg
        )
        ch_roll.add_key(frame_number, roll, interpolation=interp)
        ch_pitch.add_key(frame_number, pitch, interpolation=interp)
        ch_yaw.add_key(frame_number, yaw, interpolation=interp)

        # Focal length: direct pass-through (mm)
        ch_focal.add_key(frame_number, frame.focal_length_mm, interpolation=interp)

        # Aperture: direct pass-through (f-stop)
        ch_aperture.add_key(frame_number, frame.aperture, interpolation=interp)

        # Focus distance: m → cm
        focus_cm = transform_focus_distance(frame.focus_distance)
        ch_focus.add_key(frame_number, focus_cm, interpolation=interp)

    # ------------------------------------------------------------------
    # Step 7: Save and log
    # ------------------------------------------------------------------
    asset_full_path = f"{package_path}/{asset_name}"
    unreal.EditorAssetLibrary.save_asset(asset_full_path)

    unreal.log(
        f"[post_render_tool] LevelSequence 创建完成：{asset_full_path}  "
        f"共 {csv_result.frame_count} 关键帧，帧跨度 {frame_span}，"
        f"帧率 {fps} fps（{numerator}/{denominator}）"
    )

    return level_sequence
