"""Camera Builder — VP Post-Render Tool.

在 UE Editor 中创建 CineCameraActor，配置 Filmback 并挂载 LensComponent。
仅能在 UE Editor Python 环境中运行，不可在外部测试。
"""

from __future__ import annotations

import logging

# unreal 模块只在 UE Editor 进程内可用
import unreal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

_LENS_COMPONENT_CLASS_PATH = "/Script/LensComponent.LensComponent"


def _check_camera_calibration_plugin() -> None:
    """验证 Camera Calibration 与 Lens Component 插件均已加载。

    ULensFile 有 BlueprintType → Python 直接 unreal.LensFile 可见。
    ULensComponent 仅 MinimalAPI 无 BlueprintType → Python 绑定生成器跳过，
    unreal.LensComponent 不存在，只能走 load_class 动态解析 UClass。

    Raises
    ------
    RuntimeError
        任一插件未启用时抛出。
    """
    if not hasattr(unreal, "LensFile"):
        raise RuntimeError(
            "Camera Calibration 插件未启用。\n"
            "请在 Edit → Plugins 中搜索 'Camera Calibration' 并启用后重启编辑器。"
        )
    if _load_lens_component_class() is None:
        raise RuntimeError(
            "Lens Component 插件未启用或类路径不可解析。\n"
            "请在 Edit → Plugins 中搜索 'Lens Component' 并启用后重启编辑器。"
        )
    logger.info("Camera Calibration / Lens Component 插件已加载")


def _load_lens_component_class() -> "unreal.Class | None":
    """动态加载 ULensComponent 的 UClass；失败返回 None（插件未启用）。"""
    return unreal.load_class(None, _LENS_COMPONENT_CLASS_PATH)


def _add_component_via_subobject_subsystem(
    actor: "unreal.Actor",
    component_class: "unreal.Class",
) -> "unreal.ActorComponent":
    """UE 5.7 给 editor actor 实例动态添加 component。

    UE 5.7 的 AActor::AddComponentByClass 与 AddInstanceComponent 都未暴露到 Python
    （ScriptNoExport / 无 UFUNCTION），必须走 SubobjectDataSubsystem 官方路径。
    add_new_subobject 返回的 FSubobjectDataHandle 的 IsValid() 是普通 inline 方法
    未带 UFUNCTION（SubobjectDataHandle.h:46），Python 不可访问；用
    get_components_by_class 的前后差集定位新实例兼做失败检测。
    """
    # SubobjectDataSubsystem::Get 是 C++ 静态方法未进 Python 绑定，走 UEngineSubsystem 通道。
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    if subsystem is None:
        raise RuntimeError("SubobjectDataSubsystem 获取失败")

    handles = subsystem.k2_gather_subobject_data_for_instance(actor)
    if not handles:
        raise RuntimeError(
            f"SubobjectDataSubsystem 未能枚举 {actor.get_name()} 的 subobject handles"
        )

    params = unreal.AddNewSubobjectParams()
    params.parent_handle = handles[0]
    params.new_class = component_class

    class_name = component_class.get_name()
    before_comps = set(actor.get_components_by_class(component_class))
    _new_handle, fail_reason = subsystem.add_new_subobject(params)

    after_comps = actor.get_components_by_class(component_class)
    new_comps = [c for c in after_comps if c not in before_comps]
    if not new_comps:
        raise RuntimeError(
            f"{class_name} 添加失败: {fail_reason}"
        )
    return new_comps[0]


# ---------------------------------------------------------------------------
# 内部工具：幂等辅助
# ---------------------------------------------------------------------------

def _find_actor_by_label(
    label: str, actor_class: "unreal.Class"
) -> "unreal.Actor | None":
    """在当前关卡查找 label 匹配的指定类 Actor，找不到返回 None。"""
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if isinstance(actor, actor_class) and actor.get_actor_label() == label:
            return actor
    return None


def _ensure_lens_component(camera: "unreal.Actor") -> "unreal.ActorComponent":
    """返回 camera 上的 LensComponent：已有复用，没有则通过 Subsystem 添加。"""
    lens_comp_class = _load_lens_component_class()
    existing = camera.get_components_by_class(lens_comp_class)
    if existing:
        logger.info("复用现有 LensComponent")
        return existing[0]
    lens_component = _add_component_via_subobject_subsystem(camera, lens_comp_class)
    logger.info("已添加 LensComponent")
    return lens_component


def _configure_camera(
    camera_actor: "unreal.CineCameraActor",
    sensor_width_mm: float,
    sensor_height_mm: float,
    lens_file: "unreal.LensFile",
) -> None:
    """配置 Filmback + LensComponent + LensFile + apply_distortion。

    对新建和复用的 CineCameraActor 都安全：所有字段都用"读-改-写"覆盖赋值，
    不依赖初始状态。
    """
    # Filmback：SensorWidth 和 SensorHeight 必须同时写。UE 5.7 默认 Filmback
    # 是 Super 35（36x18.67 mm），若只写 width 则 aspect 与 CSV 不一致：
    # UCineCameraComponent::GetVerticalFieldOfView 用的是 Filmback.SensorHeight
    # (CineCameraComponent.cpp:327)，导致垂直 FOV 偏差。
    comp: unreal.CineCameraComponent = camera_actor.get_cine_camera_component()
    filmback = comp.filmback
    filmback.sensor_width = sensor_width_mm
    filmback.sensor_height = sensor_height_mm
    comp.filmback = filmback
    logger.info(
        "Filmback 传感器已设置: %.3f x %.3f mm (aspect=%.4f)",
        sensor_width_mm, sensor_height_mm,
        sensor_width_mm / sensor_height_mm if sensor_height_mm > 0 else 0.0,
    )

    # LensComponent：已有复用，没有则 add（UE 5.7 无顶层 LensFile 属性，走 FLensFilePicker
    # 嵌套 struct — LensComponent.h:280-281）
    lens_component = _ensure_lens_component(camera_actor)
    try:
        picker = lens_component.get_editor_property("lens_file_picker")
        picker.lens_file = lens_file
        picker.use_default_lens_file = False
        lens_component.set_editor_property("lens_file_picker", picker)
        logger.info("LensFile 已关联到 LensComponent.lens_file_picker")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"LensFile 关联到 LensComponent.lens_file_picker 失败: {exc}"
        ) from exc

    try:
        lens_component.set_editor_property("apply_distortion", True)
        logger.info("LensComponent apply_distortion 已启用")
    except (AttributeError, TypeError, Exception) as exc:  # noqa: BLE001
        raise RuntimeError(
            f"apply_distortion 启用失败: {exc}"
        ) from exc

    # EvaluationMode：默认 UseLiveLink 在我们这条无 LiveLink 的 pipeline 里会让
    # EvalInputs.bIsValid 永远为 false，导致 LensFile 在渲染期被跳过 —
    # ULensComponent::UpdateLensFileEvaluationInputs (LensComponent.cpp:1002-1018)
    # 仅在收到 LiveLink 帧时才填 EvalInputs；ApplyDistortion 入口
    # (LensComponent.cpp:444) 看到 bIsValid=false 直接 return。
    # 切到 UseCameraSettings 让 LensComponent 从同一 actor 上的 CineCameraComponent
    # 直接读 CurrentFocusDistance/CurrentAperture/CurrentFocalLength 作为 FIZ 输入。
    try:
        lens_component.set_editor_property(
            "evaluation_mode",
            unreal.FIZEvaluationMode.USE_CAMERA_SETTINGS,
        )
        logger.info("LensComponent evaluation_mode 已切换到 USE_CAMERA_SETTINGS")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"evaluation_mode 设置失败: {exc}"
        ) from exc

    # bAutoActivate：LensComponent 默认 false → ExecuteRegisterEvents 不调
    # Activate(true) → bIsActive=false → TickComponent 整段被跳过 → LensFile 评估
    # 永远不跑 → MID/SVE state 永远不挂到相机。
    # ActorComponent.cpp:2797-2802 SetAutoActivate 在已 register 时静默忽略，必须
    # 走 set_editor_property 直接写底层 UPROPERTY。再补一刀 activate() 让当前
    # 实例立即生效（PIE/MRQ 的克隆体由 bAutoActivate=true 接管）。
    try:
        lens_component.set_editor_property("auto_activate", True)
        if not lens_component.is_active():
            lens_component.activate()
        logger.info(
            "LensComponent auto_activate=True, is_active=%s",
            lens_component.is_active(),
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"LensComponent activate 失败: {exc}"
        ) from exc

    # LensModel：必须显式设到 LensComponent 上。Python 的
    # set_editor_property("lens_file_picker", picker) 不会触发
    # PostEditChangeProperty(FLensFilePicker.LensFile)（LensComponent.cpp:391-394
    # 那一支只在 LensFile 内层字段被改时才 fire），SetLensFilePicker 不会被调，
    # 因此 SetLensModel → CreateDistortionHandler 这条链路走不到，
    # LensDistortionHandlerMap 永远空，TickComponent 第 121 行 FindRef 拿到 nullptr，
    # distortion eval 整段被跳过。直接写 lens_model 走 PostEditChangeProperty(LensModel)
    # 那一支 (line 395-398) 强制创建 handler。
    try:
        spherical_cls = unreal.load_class(
            None, "/Script/CameraCalibrationCore.SphericalLensModel"
        )
        if spherical_cls is None:
            raise RuntimeError(
                "SphericalLensModel UClass 加载失败，请确认 Camera Calibration 插件已启用"
            )
        lens_component.set_editor_property("lens_model", spherical_cls)
        logger.info("LensComponent lens_model 已设置为 SphericalLensModel")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"LensComponent lens_model 设置失败: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def build_camera(
    sensor_width_mm: float,
    sensor_height_mm: float,
    lens_file: "unreal.LensFile",
    actor_label: str = "CineCamera_PostRender",
) -> "unreal.CineCameraActor":
    """创建或复用 CineCameraActor，并配置 Filmback 与 LensComponent（幂等）。

    幂等策略：按 actor_label 在当前关卡查找 CineCameraActor，找到则复用并更新配置，
    否则在世界原点 Spawn 新实例。复用路径对于"改 axis mapping 后重新 Import"
    至关重要 —— 它保持 LevelSequence 里的 possessable GUID 稳定。

    Parameters
    ----------
    sensor_width_mm:
        物理传感器宽度（毫米），对应 Filmback sensor_width。
    sensor_height_mm:
        物理传感器高度（毫米），对应 Filmback sensor_height。通常由上游用
        ``sensor_width / aspect_ratio`` 推算得出。
    lens_file:
        已创建的 unreal.LensFile 资产对象。
    actor_label:
        在世界大纲中显示的 Actor 名称，默认 "CineCamera_PostRender"。

    Returns
    -------
    unreal.CineCameraActor
        已配置完毕的 CineCameraActor 实例（可能是现有的或新 Spawn 的）。

    Raises
    ------
    RuntimeError
        Camera Calibration 插件未加载，或 Actor Spawn / 属性写入失败时抛出。
    """
    _check_camera_calibration_plugin()

    # 优先复用 label 匹配的现有 actor（避免每次 Import 产生 CineCamera_*_2、_3 ...）
    existing = _find_actor_by_label(actor_label, unreal.CineCameraActor)
    if existing is not None:
        logger.info("复用现有 CineCameraActor: %s", actor_label)
        _configure_camera(existing, sensor_width_mm, sensor_height_mm, lens_file)
        logger.info(
            "CineCameraActor 配置完成（复用）: label='%s', sensor=%.3fx%.3f mm",
            actor_label, sensor_width_mm, sensor_height_mm,
        )
        return existing

    # Spawn 新实例
    location = unreal.Vector(0.0, 0.0, 0.0)
    rotation = unreal.Rotator(0.0, 0.0, 0.0)
    camera_actor: unreal.CineCameraActor = (
        unreal.EditorLevelLibrary.spawn_actor_from_class(
            actor_class=unreal.CineCameraActor,
            location=location,
            rotation=rotation,
        )
    )
    if camera_actor is None:
        raise RuntimeError(
            "CineCameraActor Spawn 失败，请确认当前关卡已打开且编辑器处于正常状态。"
        )
    camera_actor.set_actor_label(actor_label)
    logger.info("已创建 CineCameraActor: %s", actor_label)

    _configure_camera(camera_actor, sensor_width_mm, sensor_height_mm, lens_file)
    logger.info(
        "CineCameraActor 构建完成（新建）: label='%s', sensor=%.3fx%.3f mm",
        actor_label, sensor_width_mm, sensor_height_mm,
    )
    return camera_actor
