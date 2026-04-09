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

def _check_camera_calibration_plugin() -> None:
    """验证 Camera Calibration 插件已加载。

    依次检查 "CameraCalibrationCore" 和 "CameraCalibration" 两个插件名称。
    若两者均未加载则抛出 RuntimeError。

    Raises
    ------
    RuntimeError
        Camera Calibration 插件未启用时抛出。
    """
    plugin_names = ["CameraCalibrationCore", "CameraCalibration"]

    for name in plugin_names:
        if unreal.PluginBlueprintLibrary.is_plugin_loaded(name):
            logger.info("Camera Calibration 插件已加载: %s", name)
            return

    raise RuntimeError(
        "Camera Calibration 插件未启用，请在 UE 插件管理器中启用 "
        "'Camera Calibration' 或 'CameraCalibrationCore' 后重启编辑器。"
    )


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
    lens_component: unreal.LensComponent = camera_actor.add_component_by_class(
        component_class=unreal.LensComponent,
        manual_attachment=False,
        relative_transform=unreal.Transform(),
    )

    if lens_component is None:
        logger.warning(
            "LensComponent 添加失败，跳过 LensFile 关联。"
            "请检查 Camera Calibration 插件版本兼容性。"
        )
    else:
        # 尝试通过 set_editor_property 关联 LensFile
        try:
            lens_component.set_editor_property("lens_file", lens_file)
            logger.info("LensFile 已关联到 LensComponent (方式A: set_editor_property)")
        except (AttributeError, TypeError, Exception) as exc_a:  # noqa: BLE001
            logger.warning("LensFile 关联失败 (方式A): %s", exc_a)
            # 尝试备用属性名
            try:
                lens_component.set_editor_property("LensFile", lens_file)
                logger.info("LensFile 已关联到 LensComponent (方式B: 大写属性名)")
            except (AttributeError, TypeError, Exception) as exc_b:  # noqa: BLE001
                logger.warning(
                    "LensFile 关联失败 (方式B): %s — 请手动在编辑器中指定 LensFile。",
                    exc_b,
                )

        # ------------------------------------------------------------------
        # 6. 启用畸变应用
        # ------------------------------------------------------------------
        try:
            lens_component.set_editor_property("apply_distortion", True)
            logger.info("LensComponent apply_distortion 已启用")
        except (AttributeError, TypeError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                "apply_distortion 设置失败: %s — 请手动在编辑器中勾选该选项。",
                exc,
            )

    logger.info(
        "CineCameraActor 构建完成: label='%s', sensor_width=%.3f mm, lens_file=%s",
        actor_label,
        sensor_width_mm,
        lens_file,
    )

    return camera_actor
