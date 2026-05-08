# Path A · LensFile Runtime (Archived)

> **状态**: dormant — 不再属于 plugin runtime 的一部分
> **下架时间**: 2026-05-08
> **原因**: Path C (Custom Post-Process Material) 已落地并通过 take_4 production
> diff + take_5 静态帧 diff 验证, LensFile fallback baseline 不再交付给最终用户

## 这是什么

Path A 是基于 UE LensFile + BrownConradyUD lens model + M_RAT6 rational fit
的旧 distortion 路线. 详细决策证据见 `docs/archive/path_a/`.

本目录保留下架前的最后一份 production code 快照, 让未来如果发现 Path C 有
不可调和的 regression 时, 可以快速对照 / 回退.

## 文件清单

| 文件 | 来源 | 说明 |
|------|------|------|
| `lens_file_builder.py` | `Content/Python/post_render_tool/lens_file_builder.py` | 写 `LF_*` UE LensFile 资产 |
| `distortion_packing.py` | `Content/Python/post_render_tool/distortion_packing.py` | BrownConradyUD 8 槽 packing + Spherical 5 槽 packing |
| `distortion_math_path_a.py` | `Content/Python/post_render_tool/distortion_math.py` 中 Path A 部分 | M_RAT6 系数 + `compute_normalized_distortion()` |
| `tests/test_distortion_rational.py` | 同名测试 | 守 M_RAT6 系数映射 |
| `tests/test_c_distortion_packing.py` | 同名测试 | 守 BrownConradyUD / Spherical 字段顺序 |

## 同时下架的 plugin 改动

下架 Path A 还涉及修改主 plugin 的以下模块 (修改后 commit 在主分支):

- `pipeline.py` — 删 `from .lens_file_builder import build_lens_file` 和
  对应的 step 2/5 调用
- `camera_builder.py` — 删 `LensComponent` 整段挂载 (lens_file_picker /
  apply_distortion=False / evaluation_mode / lens_model). LensComponent 不
  再加到 CineCameraActor 上, 因此 `_load_lens_component_class` /
  `_ensure_lens_component` / Camera Calibration 插件检查也一并删除
- `distortion_math.py` — 只保留 Path C 函数 `official_sensor_inverse_uv`
- `tests/test_integration_ue.py` — `result.lens_file is not None` 断言改成
  `result.lens_file is None` (PipelineResult 字段保留以避免破坏可能的下游
  消费, 默认 None)

## 回退步骤 (如果未来需要)

1. **复制本目录文件回 plugin**:

   ```bash
   cp archive/path_a_runtime/lens_file_builder.py Content/Python/post_render_tool/
   cp archive/path_a_runtime/distortion_packing.py Content/Python/post_render_tool/
   cp archive/path_a_runtime/tests/test_distortion_rational.py Content/Python/post_render_tool/tests/
   cp archive/path_a_runtime/tests/test_c_distortion_packing.py Content/Python/post_render_tool/tests/
   ```

2. **把 Path A 函数合回 `distortion_math.py`**:

   `distortion_math_path_a.py` 中的 M_RAT6 常量 + `compute_normalized_distortion`
   函数贴回 `Content/Python/post_render_tool/distortion_math.py` (与 Path C
   的 `official_sensor_inverse_uv` 共存即可, 两条路线不耦合, 历史上就是同
   居一个文件).

3. **`pipeline.py` 加回 build_lens_file 调用**:

   - 顶部加 `from .lens_file_builder import build_lens_file`
   - 在 step 2/5 (创建 CineCameraActor 之前) 调用 `build_lens_file(...)`
     生成 `LF_*` 资产, 并把返回值传给 `build_camera(lens_file=...)`

4. **`camera_builder.py` 加回 LensComponent 挂载**:

   - 加回 `_LENS_COMPONENT_CLASS_PATH` / `_load_lens_component_class` /
     `_ensure_lens_component`
   - 加回 `_check_camera_calibration_plugin` 里的 LensComponent 校验
   - `_configure_camera` 加回 LensComponent attach + `lens_file_picker` /
     `apply_distortion` / `evaluation_mode` / `lens_model` 配置 (如果同时
     还跑 Path C, 必须保持 `apply_distortion=False`, 否则双倍畸变)

5. **`tests/test_integration_ue.py`**:

   断言改回 `assert result.lens_file is not None`.

完整 diff 可以参考下架 commit (本目录创建当次的 git commit hash).

## 不在本目录的史料

- 公式拟合脚本 / UV probe / k1_sweep dataset:
  `scripts/distortion_calibration/archive/`
- Path A 决策文档 / 5 个旧 plan: `docs/archive/path_a/`
