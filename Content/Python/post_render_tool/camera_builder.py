"""Camera Builder — VP Post-Render Tool.

在 UE Editor 中创建 CineCameraActor, 配置 Filmback, 挂载 Path C 的
PostRenderDistortionControllerComponent + Custom Post-Process Material.

Path A (LensFile + LensComponent + BrownConradyUD) 已下架 (2026-05-08), 历史
代码归档在 ``archive/path_a_runtime/``.

仅能在 UE Editor Python 环境中运行, 不可在外部测试.
"""

from __future__ import annotations

import logging

# unreal 模块只在 UE Editor 进程内可用
import unreal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

# Path C: Custom Post-Process Material distortion 路径用的资产 / 类.
# Material 通过 build_distortion_material.run_build() 在 UE Editor 内手工触发构建
# (commandlet 跑不了 MaterialEditingLibrary), 资产路径硬编码在 plugin Content 下.
_DISTORTION_MATERIAL_PATH = "/PostRenderTool/Materials/M_PRT_OfficialSensorInverse"
_DISTORTION_CONTROLLER_CLASS = "PostRenderDistortionControllerComponent"

# Path A 时代的 LensComponent 类路径, 仅用于复用 actor 时清理 stale 残留.
# Path A 下架 (2026-05-08) 后 plugin 不再主动添加 LensComponent.
_LEGACY_LENS_COMPONENT_CLASS_PATH = "/Script/LensComponent.LensComponent"


def _add_component_via_subobject_subsystem(
    actor: "unreal.Actor",
    component_class: "unreal.Class",
) -> "unreal.ActorComponent":
    """UE 5.7 给 editor actor 实例动态添加 component.

    UE 5.7 的 AActor::AddComponentByClass 与 AddInstanceComponent 都未暴露到 Python
    (ScriptNoExport / 无 UFUNCTION), 必须走 SubobjectDataSubsystem 官方路径.
    add_new_subobject 返回的 FSubobjectDataHandle 的 IsValid() 是普通 inline 方法
    未带 UFUNCTION (SubobjectDataHandle.h:46), Python 不可访问; 用
    get_components_by_class 的前后差集定位新实例兼做失败检测.
    """
    # SubobjectDataSubsystem::Get 是 C++ 静态方法未进 Python 绑定, 走 UEngineSubsystem 通道.
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
    """在当前关卡查找 label 匹配的指定类 Actor, 找不到返回 None."""
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if isinstance(actor, actor_class) and actor.get_actor_label() == label:
            return actor
    return None


def _remove_stale_lens_component(camera: "unreal.Actor") -> None:
    """删除复用 actor 上 Path A 时代遗留的 LensComponent. 不存在则 no-op.

    Why: Path A 时代代码会给 CineCameraActor 挂 LensComponent, 早期版本默认
    apply_distortion=True. 这些 actor 在 plugin 升级到 Path C 后, LensComponent
    仍挂在身上. 重新 import 走复用路径, 若不清理, LensComponent 跟新挂的
    PostRenderDistortionControllerComponent 会同时往 camera blendable 链路推
    distortion = 双倍畸变 (Codex review 2026-05-08, P2).

    用 SubobjectDataSubsystem.K2_DeleteSubobjectsFromInstance 走官方 actor-instance
    component 删除路径, 跟 add_new_subobject 对称. UE 5.7 SubobjectDataSubsystem.h
    L243-244 / L189-190 验证过签名.
    """
    lens_comp_class = unreal.load_class(None, _LEGACY_LENS_COMPONENT_CLASS_PATH)
    if lens_comp_class is None:
        # LensComponent plugin 未启用 → actor 上不可能有 LensComponent.
        return
    existing = camera.get_components_by_class(lens_comp_class)
    if not existing:
        return

    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    if subsystem is None:
        logger.warning(
            "SubobjectDataSubsystem 不可用, %d 个 stale LensComponent 未清理",
            len(existing),
        )
        return

    handles = subsystem.k2_gather_subobject_data_for_instance(camera)
    if not handles:
        logger.warning(
            "无法枚举 %s 的 subobject handles, %d 个 stale LensComponent 未清理",
            camera.get_name(), len(existing),
        )
        return
    context = handles[0]

    handles_to_delete = [
        subsystem.find_handle_for_object(context, comp) for comp in existing
    ]

    deleted = subsystem.k2_delete_subobjects_from_instance(context, handles_to_delete)
    logger.info(
        "清理 stale LensComponent x%d (Path A actor 遗留, 防止双倍畸变)",
        deleted,
    )


def _ensure_distortion_controller(
    camera: "unreal.Actor",
) -> "unreal.ActorComponent":
    """Path C: 返回 camera 上的 PostRenderDistortionControllerComponent.

    已有复用, 没有则通过 SubobjectSubsystem 添加. 添加后:
    1. 加载 M_PRT_OfficialSensorInverse material 资产
    2. 设到 controller.base_material
    3. controller 的 BeginPlay 会自动创建 MID 挂到 camera blendable

    资产不存在时 raise RuntimeError 让用户先跑 build_distortion_material.run_build().
    """
    py_cls = getattr(unreal, _DISTORTION_CONTROLLER_CLASS, None)
    if py_cls is None:
        raise RuntimeError(
            f"unreal.{_DISTORTION_CONTROLLER_CLASS} 不可见。\n"
            "检查 plugin UBT 是否重新编译, Editor 是否重启 (UPROPERTY 增改"
            "Live Coding 不支持)."
        )
    # `unreal.<Component>` attribute access 返回 Python wrapper 类型 (有自己的元类),
    # 但 SubobjectDataSubsystem.add_new_subobject + UClass.get_name() 都期望
    # `unreal.Class` (UClass) 实例. 用 .static_class() 转一下. get_components_by_class
    # 接受任一形态, 但 .get_name() 在 Python wrapper 上是 unbound method 报错
    # (实测 dry-run 翻车点).
    controller_cls = py_cls.static_class()

    existing = camera.get_components_by_class(controller_cls)
    if existing:
        controller = existing[0]
        logger.info("复用现有 PostRenderDistortionControllerComponent")
    else:
        controller = _add_component_via_subobject_subsystem(camera, controller_cls)
        logger.info("已添加 PostRenderDistortionControllerComponent")

    material = unreal.EditorAssetLibrary.load_asset(_DISTORTION_MATERIAL_PATH)
    if material is None:
        raise RuntimeError(
            f"找不到 distortion material: {_DISTORTION_MATERIAL_PATH}\n"
            "请先在 UE Editor Python console 跑:\n"
            "    from post_render_tool import build_distortion_material\n"
            "    build_distortion_material.run_build()\n"
            "或通过 SSH + Remote Execution 触发等价命令."
        )
    controller.set_editor_property("base_material", material)
    logger.info(
        "Controller.base_material 已绑定到 %s",
        material.get_path_name(),
    )
    return controller


def _configure_camera(
    camera_actor: "unreal.CineCameraActor",
    sensor_width_mm: float,
    sensor_height_mm: float,
) -> None:
    """配置 Filmback + 挂 Path C distortion controller.

    对新建和复用的 CineCameraActor 都安全: 所有字段都用"读-改-写"覆盖赋值,
    不依赖初始状态.
    """
    # 复用 Path A 时代创建的 actor 时, 先清掉 stale LensComponent, 避免它跟
    # PostRenderDistortionController 同时推 blendable = 双倍畸变.
    _remove_stale_lens_component(camera_actor)

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

    # Overscan 静态行为 (per-take 不变, 所以静态设;Overscan 数值由 sequence_builder
    # 上 keyframe). 配合 bScaleResolutionWithOverscan + bCropOverscan 镜像 Disguise:
    # 扩大 frustum + 扩大渲染分辨率 → distortion shader 在多渲一圈的图上采样
    # → 末端 crop 回原 resolution. UE 源码: CameraStackTypes.cpp:500 ApplyOverscan,
    # PostProcessing.cpp:3270-3273 (BL_SCENE_COLOR_AFTER_TONEMAPPING) 在
    # SecondaryUpscale crop (PostProcessing.cpp:3340-3347) 之前, 所以 PP material
    # 看到的是 overscanned SceneTexture.
    comp.set_editor_property("scale_resolution_with_overscan", True)
    comp.set_editor_property("crop_overscan", True)
    logger.info("Overscan 行为已设置: scale_resolution_with_overscan=True, crop_overscan=True")

    # Path C: 挂 PostRenderDistortionControllerComponent + 绑 Material.
    # Controller 的 BeginPlay 是 camera 上 distortion blendable 的唯一来源.
    _ensure_distortion_controller(camera_actor)


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def build_camera(
    sensor_width_mm: float,
    sensor_height_mm: float,
    actor_label: str = "CineCamera_PostRender",
) -> "unreal.CineCameraActor":
    """创建或复用 CineCameraActor, 并配置 Filmback 与 distortion controller (幂等).

    幂等策略: 按 actor_label 在当前关卡查找 CineCameraActor, 找到则复用并更新配置,
    否则在世界原点 Spawn 新实例. 复用路径对于"改 axis mapping 后重新 Import"
    至关重要 —— 它保持 LevelSequence 里的 possessable GUID 稳定.

    Parameters
    ----------
    sensor_width_mm:
        物理传感器宽度 (毫米), 对应 Filmback sensor_width.
    sensor_height_mm:
        物理传感器高度 (毫米), 对应 Filmback sensor_height. 通常由上游用
        ``sensor_width / aspect_ratio`` 推算得出.
    actor_label:
        在世界大纲中显示的 Actor 名称, 默认 "CineCamera_PostRender".

    Returns
    -------
    unreal.CineCameraActor
        已配置完毕的 CineCameraActor 实例 (可能是现有的或新 Spawn 的).

    Raises
    ------
    RuntimeError
        Actor Spawn / 属性写入 / distortion controller 挂载失败时抛出.
    """
    # 优先复用 label 匹配的现有 actor (避免每次 Import 产生 CineCamera_*_2、_3 ...)
    existing = _find_actor_by_label(actor_label, unreal.CineCameraActor)
    if existing is not None:
        logger.info("复用现有 CineCameraActor: %s", actor_label)
        _configure_camera(existing, sensor_width_mm, sensor_height_mm)
        logger.info(
            "CineCameraActor 配置完成 (复用): label='%s', sensor=%.3fx%.3f mm",
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
            "CineCameraActor Spawn 失败, 请确认当前关卡已打开且编辑器处于正常状态."
        )
    camera_actor.set_actor_label(actor_label)
    logger.info("已创建 CineCameraActor: %s", actor_label)

    _configure_camera(camera_actor, sensor_width_mm, sensor_height_mm)
    logger.info(
        "CineCameraActor 构建完成 (新建): label='%s', sensor=%.3fx%.3f mm",
        actor_label, sensor_width_mm, sensor_height_mm,
    )
    return camera_actor
