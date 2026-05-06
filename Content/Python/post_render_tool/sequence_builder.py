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
from .distortion_math import map_center_shift_projection


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
    # Step 1: Create or reuse LevelSequence asset (idempotent)
    # ------------------------------------------------------------------
    # 若资产已存在（上一次 Import 留下的）→ load 后清空所有 bindings。
    # MovieSceneBindingProxy.Remove (MovieSceneBindingExtensions.h:143-144) 连同
    # 其下所有 tracks / sections / keyframes 一起删除，等同于"清场重建"。
    # 这样 Apply mapping 改动后重新 Import 能直接在 Sequencer 看到新轨迹。
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    full_sequence_path = f"{package_path}/{asset_name}"

    if unreal.EditorAssetLibrary.does_asset_exist(full_sequence_path):
        level_sequence = unreal.EditorAssetLibrary.load_asset(full_sequence_path)
        if level_sequence is None:
            raise RuntimeError(
                f"LevelSequence 资产存在但 load 失败: {full_sequence_path}"
            )
        # get_bindings (MovieSceneSequenceExtensions.h:382-383) 是 ScriptMethod
        # UFUNCTION，返回 list[MovieSceneBindingProxy]。
        existing_bindings = list(level_sequence.get_bindings())
        for binding in existing_bindings:
            binding.remove()
        # binding.remove() 只清 binding 自己挂的 tracks，sequence 根级的 master
        # track（Camera Cut Track 就是 master track）不会被带走，必须主动清。
        # 否则重新 Import 时会留下指向被删 binding 的悬挂 Camera Cut Section，
        # MRQ 渲染会 fallback 到错的相机。
        existing_tracks = list(level_sequence.get_tracks())
        for track in existing_tracks:
            level_sequence.remove_track(track)
        unreal.log(
            f"[post_render_tool] LevelSequence 已存在，清空 "
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

    # Path C distortion controller component (camera_builder 已经挂上去)
    controller_cls = getattr(unreal, "PostRenderDistortionControllerComponent", None)
    if controller_cls is None:
        raise RuntimeError(
            "unreal.PostRenderDistortionControllerComponent 不可见 — "
            "检查 plugin UBT 是否重新编译, Editor 是否重启."
        )
    controller_comps = camera_actor.get_components_by_class(controller_cls)
    if not controller_comps:
        raise RuntimeError(
            f"camera_actor '{camera_actor.get_actor_label()}' 上找不到 "
            "PostRenderDistortionControllerComponent. 检查 build_camera 是否正常执行."
        )
    distortion_controller = controller_comps[0]
    controller_binding: unreal.MovieSceneBindingProxy = level_sequence.add_possessable(
        distortion_controller
    )

    # Camera Cut Track：MRQ 渲染必需。缺这条 track 时 MRQ 拿不到 sequence 当前
    # 时间应该用哪个相机，会 fallback 到 World Outliner 第一个相机或 default
    # camera —— 表现就是 Sequencer 预览正确、MRQ 渲染 FOV/姿态完全错位。
    # binding id 必须从 actor possessable (camera_binding) 拿，不是 component
    # binding —— FMovieSceneCameraCutSection 只接受 actor 级 binding。
    camera_cut_track: unreal.MovieSceneCameraCutTrack = level_sequence.add_track(
        unreal.MovieSceneCameraCutTrack
    )
    camera_cut_section: unreal.MovieSceneCameraCutSection = (
        camera_cut_track.add_section()
    )
    camera_cut_section.set_range(0, frame_span)
    camera_cut_section.set_camera_binding_id(
        level_sequence.get_binding_id(camera_binding)
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
    sensor_h_offset_section = _add_float_track(
        comp_binding,
        "SensorHorizontalOffset",
        "Filmback.SensorHorizontalOffset",
    )
    sensor_v_offset_section = _add_float_track(
        comp_binding,
        "SensorVerticalOffset",
        "Filmback.SensorVerticalOffset",
    )

    # Path C controller float tracks: 7 个 Interp UPROPERTY → Sequencer keyframes.
    # 名字必须是 C++ UPROPERTY 的 PascalCase (Python 反射的 snake_case 是 getter 入口,
    # Sequencer track 用 reflected property name 即 PascalCase).
    k1_section = _add_float_track(controller_binding, "K1", "K1")
    k2_section = _add_float_track(controller_binding, "K2", "K2")
    k3_section = _add_float_track(controller_binding, "K3", "K3")
    center_u_section = _add_float_track(controller_binding, "CenterU", "CenterU")
    center_v_section = _add_float_track(controller_binding, "CenterV", "CenterV")
    aspect_section = _add_float_track(controller_binding, "Aspect", "Aspect")
    weight_section = _add_float_track(
        controller_binding, "DistortionWeight", "DistortionWeight"
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
    ch_sensor_h_offset = sensor_h_offset_section.get_all_channels()[0]
    ch_sensor_v_offset = sensor_v_offset_section.get_all_channels()[0]

    # Path C controller channels
    ch_k1       = k1_section.get_all_channels()[0]
    ch_k2       = k2_section.get_all_channels()[0]
    ch_k3       = k3_section.get_all_channels()[0]
    ch_center_u = center_u_section.get_all_channels()[0]
    ch_center_v = center_v_section.get_all_channels()[0]
    ch_aspect   = aspect_section.get_all_channels()[0]
    ch_weight   = weight_section.get_all_channels()[0]

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

        # Path C distortion: K1/K2/K3 pass through CSV. CenterUV tracks the radial
        # distortion centre; Filmback.Sensor*Offset tracks the projection principal
        # point (公式见 distortion_math.map_center_shift_projection).
        ch_k1.add_key(frame_number, frame.k1, interpolation=interp)
        ch_k2.add_key(frame_number, frame.k2, interpolation=interp)
        ch_k3.add_key(frame_number, frame.k3, interpolation=interp)

        center_shift = map_center_shift_projection(
            center_shift_x_mm=frame.center_shift_x_mm,
            center_shift_y_mm=frame.center_shift_y_mm,
            sensor_width_mm=frame.sensor_width_mm,
            aspect=frame.aspect_ratio,
        )
        ch_sensor_h_offset.add_key(
            frame_number,
            center_shift.sensor_horizontal_offset_mm,
            interpolation=interp,
        )
        ch_sensor_v_offset.add_key(
            frame_number,
            center_shift.sensor_vertical_offset_mm,
            interpolation=interp,
        )
        ch_center_u.add_key(frame_number, center_shift.center_u, interpolation=interp)
        ch_center_v.add_key(frame_number, center_shift.center_v, interpolation=interp)

        ch_aspect.add_key(frame_number, frame.aspect_ratio, interpolation=interp)

    # DistortionWeight 全程 1.0, 不必每帧打 key. 在 frame 0 打一个常值 key 让
    # Sequencer 里这条 track 仍然可见 (方便手动暂时调 0 验证 identity 路径).
    ch_weight.add_key(unreal.FrameNumber(0), 1.0, interpolation=interp)

    # ------------------------------------------------------------------
    # Step 7: Save and log
    # ------------------------------------------------------------------
    unreal.EditorAssetLibrary.save_asset(full_sequence_path)

    unreal.log(
        f"[post_render_tool] LevelSequence 创建完成：{full_sequence_path}  "
        f"共 {csv_result.frame_count} 关键帧，帧跨度 {frame_span}，"
        f"帧率 {fps} fps（{numerator}/{denominator}）"
    )

    return level_sequence
