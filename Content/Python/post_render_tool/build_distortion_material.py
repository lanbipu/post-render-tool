"""Build M_PRT_OfficialSensorInverse — Path C Custom Post-Process Material.

幂等: 重跑会先删旧资产再新建. shader 公式 + 节点结构是 Path C 落地核心.

Material 配置 (跟 docs/custom-postprocess-distortion-final-plan.md §4.3 一致):
  - Domain: Post Process
  - Blendable Location: After Tonemapping
  - 输出: Emissive Color
  - 参数:
      K1 / K2 / K3 / Aspect / DistortionWeight  → Scalar Parameter
      CenterUV                                  → Vector Parameter (R=U, G=V)

节点图:
  ScreenPosition.ViewportUV ──┐
  CenterUV ───────────────────┤
  K1, K2, K3, Aspect, Weight ─┤── Custom HLSL (formula) ──┐
                                                          │
                                                          ▼
                       SceneTexture(PostProcessInput0).UVs ─→ Color ─┐
                       (bFiltered=true → bilinear sampling)          │
                                                                     ▼
                                                                  Multiply → Emissive
                                                                     ▲
  sourceUV ─→ Custom HLSL (in-bounds mask) ──────────────────────────┘
              (out-of-bounds → 0, 内圈 → 1)

HLSL 公式 1:1 镜像 distortion_math.official_sensor_inverse_uv (Python reference).
公式形态如果 Gate 6 后要改, 改 HLSL_CODE 这一处 + Python 那一处, 重跑 run_build().

为什么要 bilinear sampling 和 mask:
- bFiltered=True: distortion 产生 sub-pixel sourceUV, 不开 bilinear 会 stair-step,
  跟 cv2.remap INTER_LINEAR 离线 reference 对不上.
- mask: SceneTexture node 默认会把 sourceUV clamp 到 [0,1] 再采样, 等于 LED
  边缘像素被复制到画面外, 跟 plan 要求的 "constant black border" 不符. 显式
  用 mask 把超出 [0,1] 的位置乘成黑色.

调用方式 (UE Editor Python console):
    from post_render_tool import build_distortion_material
    build_distortion_material.run_build()

依赖 UE Editor 运行 (commandlet 模式 MaterialEditingLibrary 不工作).
"""
from __future__ import annotations

import logging

import unreal

logger = logging.getLogger(__name__)


# ── 资产路径 ────────────────────────────────────────────────────────────
PACKAGE_PATH = "/PostRenderTool/Materials"
ASSET_NAME = "M_PRT_OfficialSensorInverse"
FULL_ASSET_PATH = f"{PACKAGE_PATH}/{ASSET_NAME}"


# ── 主公式 HLSL (跟 official_sensor_inverse_uv 一字一致) ───────────────
# Custom node 的 inputs 顺序: UV, CenterUV, K1, K2, K3, Aspect, DistortionWeight
HLSL_CODE = """
// Mirrors distortion_math.official_sensor_inverse_uv (Python reference).
// Output → source UV sampling map (cv2.remap forward).
float2 d = UV - CenterUV.rg;
float2 r = float2(2.0 * d.x, 2.0 * d.y / Aspect);
float r2 = dot(r, r);
float fac = K1 * r2 + K2 * r2 * r2 + K3 * r2 * r2 * r2;
return UV + fac * d * DistortionWeight;
""".strip()


# ── In-bounds mask HLSL ────────────────────────────────────────────────
# sourceUV ∈ [0,1]² 时返回 1, 出界返回 0. 用 step() 避免分支.
# 离线 cv2.remap 用 borderMode=BORDER_CONSTANT/borderValue=0, 这里复刻"超出
# 输入图边界 → black"行为, 跟 SceneTexture 默认 clamp-to-edge 完全相反.
MASK_HLSL_CODE = """
// In-bounds test: 1.0 if sourceUV is fully inside [0,1]², else 0.0.
float2 inBounds = step(0.0, sourceUV) * step(sourceUV, 1.0);
return inBounds.x * inBounds.y;
""".strip()


# ── Custom node 输入端口名 (顺序就是 HLSL 里 UV, CenterUV, K1, K2, K3, Aspect, DistortionWeight) ──
CUSTOM_INPUT_NAMES = ("UV", "CenterUV", "K1", "K2", "K3", "Aspect", "DistortionWeight")


# ── 节点画布坐标 (单位是 graph editor 里的像素, 视觉布局用) ───────────
LAYOUT = {
    "K1":               (-800, -400),
    "K2":               (-800, -300),
    "K3":               (-800, -200),
    "Aspect":           (-800, -100),
    "DistortionWeight": (-800,    0),
    "CenterUV":         (-800,  100),
    "ScreenPosition":   (-800,  250),
    "Custom":           (-400,    0),
    "SceneTexture":     ( -50, -100),
    "Mask":             ( -50,  150),
    "Multiply":         ( 250,    0),
}


def _delete_existing() -> None:
    """删除已存在的资产, 让 run_build 可以幂等重跑."""
    if unreal.EditorAssetLibrary.does_asset_exist(FULL_ASSET_PATH):
        ok = unreal.EditorAssetLibrary.delete_asset(FULL_ASSET_PATH)
        if ok:
            logger.info(f"已删除已存在 Material: {FULL_ASSET_PATH}")
        else:
            raise RuntimeError(f"无法删除已存在 Material: {FULL_ASSET_PATH} (可能被引用?)")


def _ensure_directory() -> None:
    if not unreal.EditorAssetLibrary.does_directory_exist(PACKAGE_PATH):
        unreal.EditorAssetLibrary.make_directory(PACKAGE_PATH)
        logger.info(f"已创建目录: {PACKAGE_PATH}")


def _create_material() -> "unreal.Material":
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialFactoryNew()
    material = asset_tools.create_asset(
        asset_name=ASSET_NAME,
        package_path=PACKAGE_PATH,
        asset_class=unreal.Material,
        factory=factory,
    )
    if not material:
        raise RuntimeError(f"create_asset 失败: {FULL_ASSET_PATH}")
    logger.info(f"已创建 Material: {FULL_ASSET_PATH}")
    return material


def _set_post_process_domain(material: "unreal.Material") -> None:
    """Domain = PostProcess, BlendableLocation = AfterTonemapping."""
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property("blendable_location", unreal.BlendableLocation.BL_AFTER_TONEMAPPING)
    material.set_editor_property("blendable_priority", 0)
    logger.info("Material Domain = PostProcess, BlendableLocation = AfterTonemapping")


def _make_scalar(material, name: str, default: float, x: int, y: int) -> "unreal.MaterialExpressionScalarParameter":
    mel = unreal.MaterialEditingLibrary
    node = mel.create_material_expression(material, unreal.MaterialExpressionScalarParameter, x, y)
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", default)
    node.set_editor_property("group", "Distortion")
    return node


def _make_vector(material, name: str, default: "unreal.LinearColor", x: int, y: int) -> "unreal.MaterialExpressionVectorParameter":
    mel = unreal.MaterialEditingLibrary
    node = mel.create_material_expression(material, unreal.MaterialExpressionVectorParameter, x, y)
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", default)
    node.set_editor_property("group", "Distortion")
    return node


def run_build() -> "unreal.Material":
    """主入口: 建 (或重建) M_PRT_OfficialSensorInverse 资产."""
    _ensure_directory()
    _delete_existing()
    material = _create_material()
    _set_post_process_domain(material)

    mel = unreal.MaterialEditingLibrary

    # ── Parameter nodes ──
    n_K1 = _make_scalar(material, "K1", 0.0, *LAYOUT["K1"])
    n_K2 = _make_scalar(material, "K2", 0.0, *LAYOUT["K2"])
    n_K3 = _make_scalar(material, "K3", 0.0, *LAYOUT["K3"])
    n_Aspect = _make_scalar(material, "Aspect", 16.0 / 9.0, *LAYOUT["Aspect"])
    n_Weight = _make_scalar(material, "DistortionWeight", 1.0, *LAYOUT["DistortionWeight"])
    n_Center = _make_vector(material, "CenterUV", unreal.LinearColor(0.5, 0.5, 0.0, 0.0), *LAYOUT["CenterUV"])

    # ── ScreenPosition: viewport UV input ──
    n_ScreenPos = mel.create_material_expression(
        material, unreal.MaterialExpressionScreenPosition,
        *LAYOUT["ScreenPosition"],
    )

    # ── Custom HLSL node ──
    n_Custom = mel.create_material_expression(
        material, unreal.MaterialExpressionCustom,
        *LAYOUT["Custom"],
    )
    n_Custom.set_editor_property("code", HLSL_CODE)
    n_Custom.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT2)
    n_Custom.set_editor_property("description", "OfficialSensorInverse")

    # Custom node inputs: 默认带一个名为 "Input" 的 entry, 我们换成 7 个具名 input.
    custom_inputs = []
    for input_name in CUSTOM_INPUT_NAMES:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", input_name)
        custom_inputs.append(ci)
    n_Custom.set_editor_property("inputs", custom_inputs)

    # ── SceneTexture: PostProcessInput0 (bilinear sampling) ──
    n_SceneTex = mel.create_material_expression(
        material, unreal.MaterialExpressionSceneTexture,
        *LAYOUT["SceneTexture"],
    )
    n_SceneTex.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    # 默认 bFiltered=False = point sampling, 跟 cv2.remap INTER_LINEAR 离线 reference
    # 对不上 (subpixel sourceUV 会 stair-step). 显式开 bilinear.
    n_SceneTex.set_editor_property("b_filtered", True)

    # ── In-bounds mask Custom node ──
    # sourceUV 出界 [0,1]² 时输出 0, 在界内输出 1. 后面跟 SceneTexture.Color 相乘
    # 实现"出界像素 → black"语义, 复刻 cv2.remap BORDER_CONSTANT/borderValue=0 行为.
    n_Mask = mel.create_material_expression(
        material, unreal.MaterialExpressionCustom,
        *LAYOUT["Mask"],
    )
    n_Mask.set_editor_property("code", MASK_HLSL_CODE)
    n_Mask.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT1)
    n_Mask.set_editor_property("description", "InBoundsMask")
    mask_input = unreal.CustomInput()
    mask_input.set_editor_property("input_name", "sourceUV")
    n_Mask.set_editor_property("inputs", [mask_input])

    # ── Multiply: SceneTexture.Color × mask = 真实输出 ──
    n_Multiply = mel.create_material_expression(
        material, unreal.MaterialExpressionMultiply,
        *LAYOUT["Multiply"],
    )

    # ── 连线 ──
    # ScreenPosition.ViewportUV → Custom.UV
    mel.connect_material_expressions(n_ScreenPos, "ViewportUV", n_Custom, "UV")

    # CenterUV.RGB → Custom.CenterUV (Vector parameter 默认输出 = RGB)
    mel.connect_material_expressions(n_Center, "", n_Custom, "CenterUV")

    # 5 个 scalar parameter → Custom 对应 input
    mel.connect_material_expressions(n_K1, "", n_Custom, "K1")
    mel.connect_material_expressions(n_K2, "", n_Custom, "K2")
    mel.connect_material_expressions(n_K3, "", n_Custom, "K3")
    mel.connect_material_expressions(n_Aspect, "", n_Custom, "Aspect")
    mel.connect_material_expressions(n_Weight, "", n_Custom, "DistortionWeight")

    # Custom (sourceUV) → SceneTexture.UVs (用于实际采样)
    mel.connect_material_expressions(n_Custom, "", n_SceneTex, "UVs")

    # Custom (sourceUV) → Mask.sourceUV (复用同一个 sourceUV 算 mask)
    mel.connect_material_expressions(n_Custom, "", n_Mask, "sourceUV")

    # SceneTexture.Color → Multiply.A
    mel.connect_material_expressions(n_SceneTex, "Color", n_Multiply, "A")

    # Mask → Multiply.B
    mel.connect_material_expressions(n_Mask, "", n_Multiply, "B")

    # Multiply → Material Emissive Color (=出界已经被 mask 乘成 0 = black)
    mel.connect_material_property(n_Multiply, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    # ── 编译 + 保存 ──
    mel.recompile_material(material)
    saved = unreal.EditorAssetLibrary.save_loaded_asset(material)
    if not saved:
        logger.warning(f"save_loaded_asset 返回 False: {FULL_ASSET_PATH}")
    logger.info(f"完成: {FULL_ASSET_PATH}")
    return material


if __name__ == "__main__":
    run_build()
