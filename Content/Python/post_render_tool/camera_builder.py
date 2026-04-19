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
# 公共 API
# ---------------------------------------------------------------------------

def build_camera(
    sensor_width_mm: float,
    lens_file: "unreal.LensFile",
    actor_label: str = "CineCamera_PostRender",
) -> "unreal.CineCameraActor":
    """创建 CineCameraActor 并配置 Filmback 与 LensComponent。

    流程：
    1. 检查 Camera Calibration 插件是否已加载。
    2. 在世界原点 Spawn CineCameraActor。
    3. 设置 Actor Label。
    4. 配置 CineCameraComponent 的 Filmback 传感器宽度。
    5. 添加 LensComponent 并关联 LensFile 资产。
    6. 启用 LensComponent 的畸变应用（apply_distortion = True）。

    Parameters
    ----------
    sensor_width_mm:
        物理传感器宽度（毫米），对应 Filmback sensor_width。
    lens_file:
        已创建的 unreal.LensFile 资产对象。
    actor_label:
        在世界大纲中显示的 Actor 名称，默认 "CineCamera_PostRender"。

    Returns
    -------
    unreal.CineCameraActor
        已配置完毕的 CineCameraActor 实例。

    Raises
    ------
    RuntimeError
        Camera Calibration 插件未加载，或 Actor Spawn 失败时抛出。
    """
    # ------------------------------------------------------------------
    # 1. 检查插件
    # ------------------------------------------------------------------
    _check_camera_calibration_plugin()

    # ------------------------------------------------------------------
    # 2. 在世界原点 Spawn CineCameraActor
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 3. 设置 Actor Label
    # ------------------------------------------------------------------
    camera_actor.set_actor_label(actor_label)
    logger.info("已创建 CineCameraActor: %s", actor_label)

    # ------------------------------------------------------------------
    # 4. 配置 Filmback 传感器宽度
    # ------------------------------------------------------------------
    comp: unreal.CineCameraComponent = camera_actor.get_cine_camera_component()

    filmback = comp.filmback
    filmback.sensor_width = sensor_width_mm
    comp.filmback = filmback

    logger.info("Filmback 传感器宽度已设置: %.3f mm", sensor_width_mm)

    # ------------------------------------------------------------------
    # 5. 添加 LensComponent 并关联 LensFile
    # ------------------------------------------------------------------
    # UE 5.7: ULensComponent 无 BlueprintType，unreal.LensComponent 不存在，
    # 需用 load_class 拿 UClass；AActor::AddComponentByClass 带 ScriptNoExport
    # 也不可用，走 SubobjectDataSubsystem 的官方 editor 路径。
    lens_component = _add_component_via_subobject_subsystem(
        camera_actor,
        _load_lens_component_class(),
    )
    logger.info("LensComponent 已添加到 %s", actor_label)

    # ULensComponent 没有顶层 LensFile 属性；实际 UPROPERTY 是 FLensFilePicker 嵌套
    # （LensComponent.h:280-281 → FLensFilePicker.LensFile，CameraCalibrationCore/
    # Public/LensFile.h:361-378）。Python 需先拿 struct、改内部字段、再 set 回去。
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

    # ------------------------------------------------------------------
    # 6. 启用畸变应用
    # ------------------------------------------------------------------
    try:
        lens_component.set_editor_property("apply_distortion", True)
        logger.info("LensComponent apply_distortion 已启用")
    except (AttributeError, TypeError, Exception) as exc:  # noqa: BLE001
        raise RuntimeError(
            f"apply_distortion 启用失败: {exc}"
        ) from exc

    logger.info(
        "CineCameraActor 构建完成: label='%s', sensor_width=%.3f mm, lens_file=%s",
        actor_label,
        sensor_width_mm,
        lens_file,
    )

    return camera_actor
