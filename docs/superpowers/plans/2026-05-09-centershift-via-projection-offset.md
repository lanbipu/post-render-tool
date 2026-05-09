# CenterShift 走 Camera Projection Offset 替换 Shader Translation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Disguise `centerShift` 从 post-process shader 的 `sourceUV` 平移迁移到 UE `CineCameraComponent.Filmback.SensorHorizontalOffset/SensorVerticalOffset`,让 UE camera 的 frustum 跟 Disguise 一致,补回 take_6 当前缺失的上 + 右边缘内容(~9–10 px)。

**Architecture:** Disguise 在渲染前已把 frustum 中心歪到 principal point,所以它"看"的范围跟 UE 不一样;UE 现在 frustum 永远在 (0.5, 0.5),shader 后期只能搬已渲到的像素,补不回 frustum 外内容。修复路径:

1. shader 移除 `-csxUV` translation,只留 radial term `fac * d`
2. `sequence_builder` 加两条 float tracks(`Filmback.SensorHorizontalOffset` / `Filmback.SensorVerticalOffset`),用 `centerShift_*_mm` 关键帧驱动
3. `CenterU/V` material parameter 含义改为 "radial distortion 中心 in viewport UV";因 frustum offset 已把 principal point 对到图心,所有帧值改为 `(0.5, 0.5)` 常量
4. `csv_parser` `FrameData` 加 `overscan_x/y` + `overscan_resolution_x/y` 字段(diagnostics 用,不参与渲染;production spec 仍是 1920×1080)
5. SHADER_VERSION 翻新触发 pipeline 启动时 metadata-tag 校验失败 → 强制用户 `run_build()` 重生成 material asset

**Tech Stack:** Python 3 (UE 5.7 plugin runtime) · UE 5.7 Sequencer Python API · UE Material Editor Python API · unittest (pure-python tests)

**Sign Convention:** `SensorHorizontalOffset = -cs_x_mm`,`SensorVerticalOffset = -cs_y_mm`(两个轴都取负)。推理:

- UE `OffCenterProjectionOffset.X = 2 * SensorHorizontalOffset / SensorWidth`(`CineCameraComponent.cpp:347`),`OffCenterX > 0` 让 frustum 向右扩
- Disguise `cs_x < 0` 在 OpenCV/标定约定下 = 主点在 sensor 左 = forward ray 落在 raster 左 → camera 拍到右边多
- UE 复刻 = 也要拍到右边多 → `OffCenterX > 0` → `SensorHOff > 0` → `= -cs_x_mm`
- Y 方向同理(已结合现存 Y-flip 修复:`CenterV = 0.5 - cs_y/sh` 表明 cs_y<0 时 UV 主点在图心下方,等价于 Disguise 拍到上边多)
- take_6 实测 cs=(-0.166, -0.192) 且 UE 缺 top+right,跟该 sign 推理方向一致

Phase 1 frustum-only 渲染依然作为最终确认;若两轴 sign 都对,top+right edge 内容应被补回。

**Out of scope:**
- MRQ overscan(渲 1.3× 后 crop)— production spec 强制 1920×1080,且 ~10 px 不对称用 320 px overscan 是大炮打蚊子
- centerShift 的 per-frame 变化(take_6 只有 2 帧静止,这次足够;长 take 留待回归)
- 物理标定 / 重测 K1/K2/K3

---

## File Structure

| 文件 | 作用 | 改动类型 |
|---|---|---|
| `Content/Python/post_render_tool/csv_parser.py` | `FrameData` 加 4 字段 + carry-forward | 修改 |
| `Content/Python/post_render_tool/build_distortion_material.py` | shader 移除 `-csxUV`,bump SHADER_VERSION | 修改 |
| `Content/Python/post_render_tool/sequence_builder.py` | 加 2 条 filmback offset tracks;CenterU/V 改 0.5 常量 | 修改 |
| `Content/Python/post_render_tool/tests/test_csv_parser.py` | 验证 4 个新字段被解析 | 修改 |
| `Content/Python/post_render_tool/tests/test_shader_version.py` | 验证新 SHADER_VERSION 通过 sanity | 自动通过(无需改) |
| `validation_results/path_c_production/take_6/summary.md` | 标注当前 0001 PNG 是旧公式(`-csxUV`),记录新方向 | 修改 |
| `CLAUDE.md` | 更新 Path C 状态描述 | 修改 |

不新建文件。

---

## Task 1: 扩展 FrameData 增加 overscan 字段(TDD)

**Files:**
- Modify: `Content/Python/post_render_tool/csv_parser.py:47-71`
- Modify: `Content/Python/post_render_tool/csv_parser.py:118-178`(legacy + spatialmap dialect 各加 4 个 soft column)
- Modify: `Content/Python/post_render_tool/csv_parser.py:362-367`(carry-forward 表加 4 个字段)
- Test: `Content/Python/post_render_tool/tests/test_csv_parser.py`

`overscan_x/y` 是 ratio(CSV 实测 1.3),`overscan_resolution_x/y` 是 int(CSV 实测 2496×1404)。**这次只加字段,不参与渲染**;`pipeline.run_import` / `sequence_builder` 不读它。后续做"overscan 真实支持"时再用。

- [ ] **Step 1: 写失败测试**

在 `test_csv_parser.py` 文件末尾(`if __name__ == "__main__"` 之前)新增一个测试方法:

```python
    def test_overscan_fields_parsed(self):
        """Overscan + overscanResolution 4 个字段从 CSV 解出来,挂到 FrameData."""
        from post_render_tool.csv_parser import parse_csv_dense

        prefix = "camera:cam_1"
        headers = self._make_headers(prefix)
        rows = [self._make_row("00:00:00.00", 0)]
        path = self._tmp(self._write_csv(headers, rows))

        result = parse_csv_dense(path)
        f0 = result.frames[0]

        self.assertAlmostEqual(f0.overscan_x, 1.3, places=4)
        self.assertAlmostEqual(f0.overscan_y, 1.3, places=4)
        self.assertEqual(f0.overscan_resolution_x, 2496)
        self.assertEqual(f0.overscan_resolution_y, 1404)
```

(`_make_headers` / `_make_row` 现有 helper 已经包含这 4 列,见 `test_csv_parser.py:18-49`,无需改。)

- [ ] **Step 2: 跑测试确认失败**

```bash
cd Content/Python && python -m unittest post_render_tool.tests.test_csv_parser.TestCsvDenseParser.test_overscan_fields_parsed -v
```

预期:`AttributeError: 'FrameData' object has no attribute 'overscan_x'`。

- [ ] **Step 3: 给 `FrameData` 加 4 个字段**

`csv_parser.py:47` 的 `FrameData` dataclass 末尾(`resolution_y` 之后)加:

```python
    overscan_x: Optional[float] = None
    overscan_y: Optional[float] = None
    overscan_resolution_x: Optional[int] = None
    overscan_resolution_y: Optional[int] = None
```

(`Optional + None` 默认值是为了 spatialmap dialect 缺这些字段时 `FrameData(...)` 仍能构造。)

- [ ] **Step 4: 给两个 dialect 的 `soft_columns` 加 4 项**

`_build_legacy_dialect`(csv_parser.py:118)的 `soft = {...}`(:138)末尾加:

```python
        "overscan_x":              f"{p}.overscan.x",
        "overscan_y":              f"{p}.overscan.y",
        "overscan_resolution_x":   f"{p}.overscanResolution.x",
        "overscan_resolution_y":   f"{p}.overscanResolution.y",
```

`_build_spatialmap_dialect`(csv_parser.py:148)的 `soft = {...}`(:170)同样末尾加 4 行,column 名前缀用 `cam =`(spatialmap 把 overscan 放在 `activeCamera` 子节点),具体路径若 spatialmap 不支持 overscan 也无妨,字段对它来说是 soft + 缺失返回 None,不影响。先按 legacy 同名加上去:

```python
        "overscan_x":              f"{cam}.overscan.x",
        "overscan_y":              f"{cam}.overscan.y",
        "overscan_resolution_x":   f"{cam}.overscanResolution.x",
        "overscan_resolution_y":   f"{cam}.overscanResolution.y",
```

- [ ] **Step 5: 在 `parse_csv_dense` 写 FrameData 处加 4 个 `_get_opt_*` 调用**

`csv_parser.py:408` 现有:

```python
    col_fov_v = dialect.soft_columns["fov_v"]
    col_res_x = dialect.soft_columns["resolution_x"]
    col_res_y = dialect.soft_columns["resolution_y"]
```

下方加 4 行:

```python
    col_oversc_x   = dialect.soft_columns["overscan_x"]
    col_oversc_y   = dialect.soft_columns["overscan_y"]
    col_oversc_rx  = dialect.soft_columns["overscan_resolution_x"]
    col_oversc_ry  = dialect.soft_columns["overscan_resolution_y"]
```

`csv_parser.py:446-454` 的 `frames.append(FrameData(...))` 在 `resolution_y=...` 之后加:

```python
            overscan_x=_get_opt_float(row, col_oversc_x),
            overscan_y=_get_opt_float(row, col_oversc_y),
            overscan_resolution_x=_get_opt_int(row, col_oversc_rx),
            overscan_resolution_y=_get_opt_int(row, col_oversc_ry),
```

- [ ] **Step 6: 跑测试确认通过**

```bash
cd Content/Python && python -m unittest post_render_tool.tests.test_csv_parser -v
```

预期:全部 csv_parser 测试 PASS,新加的 `test_overscan_fields_parsed` 也 PASS。

- [ ] **Step 7: 暂不 commit**(全部 task 完成后用户审核统一 commit)

---

## Task 2: Shader 移除 `-csxUV` translation + bump SHADER_VERSION

**Files:**
- Modify: `Content/Python/post_render_tool/build_distortion_material.py:62`(SHADER_VERSION 字符串)
- Modify: `Content/Python/post_render_tool/build_distortion_material.py:68-80`(HLSL_CODE)

shader 改完之后:
- `CenterUV` 输入仍保留(向后兼容 + 调试方便),但仅作为 radial distortion 中心
- `csxUV` 中间变量删除
- 公式从 `UV + (fac * d - csxUV) * Weight` 变为 `UV + (fac * d) * Weight`

`SHADER_VERSION` 改了之后,部署到 UE 的 Material asset metadata-tag 会跟源不匹配 → `pipeline.run_import` 启动时校验失败 → 用户被强制跑 `build_distortion_material.run_build()` 重生成 asset(这是设计好的安全机制,见 `verify_material_freshness` at :295)。

- [ ] **Step 1: 改 SHADER_VERSION 字符串**

`build_distortion_material.py:62`:

```python
SHADER_VERSION = "2026-05-09-centershift-via-projection-offset"
```

- [ ] **Step 2: 改 HLSL_CODE**

`build_distortion_material.py:68-80` 整段改为:

```python
HLSL_CODE = f"""
// VERSION: {SHADER_VERSION}
// Mirrors radial-only post-process distortion.
// CenterShift 已移到 CineCameraComponent.Filmback.SensorHorizontalOffset/Vertical
// (走 OffCenterProjectionOffset),frustum 在渲染时已对准 principal point;
// 这里只剩 radial term,radial 中心固定 = 图心 (0.5, 0.5),CenterUV 由
// sequence_builder 写入 (0.5, 0.5) 常量,Aspect 仍按 per-frame CSV 关键帧。
float2 d = UV - CenterUV.rg;
float2 r = float2(d.x, d.y / Aspect);
float r2 = dot(r, r);
float fac = K1 * r2 + K2 * r2 * r2 + K3 * r2 * r2 * r2;
return UV + (fac * d) * DistortionWeight;
""".strip()
```

`csxUV` 那行连同 `- csxUV` 一起删除。注释里把背景说清楚,方便未来 grep。

- [ ] **Step 3: 跑 shader_version test 确认通过**

```bash
cd Content/Python && python -m unittest post_render_tool.tests.test_shader_version -v
```

预期:全 PASS(测试只校验 ISO 日期前缀 + tag 名 + VERSION 注释镜像)。

- [ ] **Step 4: 跑全部 Mac-side 测试确认 distortion_math 等下游测试不被波及**

```bash
cd Content/Python && python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -v
```

预期:全 PASS。

> 注意:`test_custom_postprocess_distortion_math.py` 测的是 Python reference `distortion_math.official_sensor_inverse_uv`(它以前是 HLSL 公式的镜像)。HLSL 公式语义改了 → Python reference 也得跟着改,但 Python reference 当前已经不参与生产路径(controller 不调用它)。验证步骤会暴露这一点 → 列在 Task 3 解决。

- [ ] **Step 5: 暂不 commit**

---

## Task 3: Python reference `official_sensor_inverse_uv` 同步去掉 csx_uv translation

**Files:**
- Modify: `Content/Python/post_render_tool/distortion_math.py`(如果有 `official_sensor_inverse_uv` 函数)
- Modify: `Content/Python/post_render_tool/tests/test_custom_postprocess_distortion_math.py`(可能需要更新 expected outputs)

> 这一步如果 Step 4 跑通了(Mac-side 测试全过),说明 Python reference 跟 HLSL 不再一致但测试没覆盖到平移项 — 那就**只改源,不改测试**,Step 4 就足够。如果 Step 4 失败(测试期望旧公式输出),按下面执行。

- [ ] **Step 1: 跑测试看是不是这个文件失败**

```bash
cd Content/Python && python -m unittest post_render_tool.tests.test_custom_postprocess_distortion_math -v
```

- [ ] **Step 2: 若失败,定位 `distortion_math.py` 里的 `official_sensor_inverse_uv` 函数**

```bash
grep -n "official_sensor_inverse_uv\|csx_uv" Content/Python/post_render_tool/distortion_math.py
```

把 `- csx_uv` 那一项从公式里删除,跟 HLSL 同步。

- [ ] **Step 3: 更新测试 expected values**

旧公式:`source_uv = uv + fac * d - csx_uv`,新公式:`source_uv = uv + fac * d`。
失败的测试用例里 expected 减去 csx_uv 项,加回去:`expected_new = expected_old + csx_uv`。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd Content/Python && python -m unittest post_render_tool.tests.test_custom_postprocess_distortion_math -v
```

- [ ] **Step 5: 暂不 commit**

---

## Task 4: sequence_builder 加 SensorHorizontalOffset/Vertical tracks + CenterU/V 改 0.5 常量

**Files:**
- Modify: `Content/Python/post_render_tool/sequence_builder.py:230-241`(加 2 条 track 创建)
- Modify: `Content/Python/post_render_tool/sequence_builder.py:266-273`(取 channel)
- Modify: `Content/Python/post_render_tool/sequence_builder.py:315-330`(写 keyframe;CenterU/V 改 0.5)

UE 5.7 `Filmback.SensorHorizontalOffset` / `SensorVerticalOffset` 是 `Interp + BlueprintReadWrite` UPROPERTY(`CineCameraSettings.h:27-33`),Sequencer 可绑;`OffCenterProjectionOffset` 由 `CineCameraComponent::GetCameraView` 读 filmback offset 算出来(`CineCameraComponent.cpp:603-604`)。

property 名跟现有 `ManualFocusDistance` 同模式:`prop_name = "SensorHorizontalOffset"`,`prop_path = "Filmback.SensorHorizontalOffset"`。

- [ ] **Step 1: 在 controller 7 条 track 创建之后追加 2 条 filmback offset tracks**

`sequence_builder.py:241` 之后(`weight_section = ...` 行之后)插入:

```python
    # CenterShift via camera projection (UE 5.7 Filmback.SensorHorizontalOffset/Vertical
    # → CineCameraComponent.GetCameraView 写入 OffCenterProjectionOffset, 渲染时改
    # frustum 中心). 必须 bind 到 comp_binding (CineCameraComponent), 不是 controller_binding.
    sensor_h_offset_section = _add_float_track(
        comp_binding, "SensorHorizontalOffset", "Filmback.SensorHorizontalOffset"
    )
    sensor_v_offset_section = _add_float_track(
        comp_binding, "SensorVerticalOffset", "Filmback.SensorVerticalOffset"
    )
```

- [ ] **Step 2: 取 channel**

`sequence_builder.py:273` 之后(`ch_weight = weight_section.get_all_channels()[0]` 行之后)插入:

```python
    ch_sensor_h_offset = sensor_h_offset_section.get_all_channels()[0]
    ch_sensor_v_offset = sensor_v_offset_section.get_all_channels()[0]
```

- [ ] **Step 3: 改 CenterU/V 为 0.5 常量,删 cs-based 公式;在主循环里写 filmback offset 关键帧 (sign 取负,见 Sign Convention)**

`sequence_builder.py:321-330` 现有:

```python
        sensor_height_mm = frame.sensor_width_mm / frame.aspect_ratio
        center_u = 0.5 + frame.center_shift_x_mm / frame.sensor_width_mm
        # Y axis flip: ...
        center_v = 0.5 - frame.center_shift_y_mm / sensor_height_mm
        ch_center_u.add_key(frame_number, center_u, interpolation=interp)
        ch_center_v.add_key(frame_number, center_v, interpolation=interp)
```

整段替换为:

```python
        # Path C 新模型 (2026-05-09 之后):
        #   CenterShift 通过 CineCameraComponent.Filmback.SensorHorizontalOffset/Vertical
        #   驱动 frustum offset, UE 渲染时主光轴已对到图心 (0.5, 0.5).
        #   Shader 只做 radial distortion, radial 中心 = 图心 = (0.5, 0.5) 常量,
        #   跟 cs 解耦.
        ch_center_u.add_key(frame_number, 0.5, interpolation=interp)
        ch_center_v.add_key(frame_number, 0.5, interpolation=interp)

        # Filmback offset 取 -centerShift_mm (Sign Convention 见 plan 顶部).
        ch_sensor_h_offset.add_key(
            frame_number, -frame.center_shift_x_mm, interpolation=interp
        )
        ch_sensor_v_offset.add_key(
            frame_number, -frame.center_shift_y_mm, interpolation=interp
        )
```

- [ ] **Step 4: 语法 check sequence_builder**

```bash
python3 -c "import ast; ast.parse(open('Content/Python/post_render_tool/sequence_builder.py').read()); print('OK')"
```

预期:`OK`。

- [ ] **Step 5: 暂不 commit**

---

## Task 5: 验证 Mac-side 全测试 + 语法 check 全部 UE-dependent 模块

- [ ] **Step 1: Mac-side unit tests**

```bash
cd Content/Python && python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -v
```

预期:全 PASS。

- [ ] **Step 2: spec drift test(C++ / widget.py / JSON 三方一致性,这次 BindWidget 没动应当 PASS)**

```bash
cd Content/Python && python -m unittest post_render_tool.tests.test_spec_drift -v
```

- [ ] **Step 3: 全部 UE-dependent 模块 syntax check**

```bash
cd Content/Python && for f in post_render_tool/{camera_builder,sequence_builder,pipeline,ui_interface,widget,widget_builder,build_distortion_material}.py; do
  python3 -c "import ast; ast.parse(open('$f').read()); print('OK: $f')"
done
```

预期:每行都是 `OK: ...`。

---

## Task 6: 同步文档(CLAUDE.md + take_6 summary)

**Files:**
- Modify: `CLAUDE.md`(顶部 Path C 状态 block)
- Modify: `validation_results/path_c_production/take_6/summary.md`

- [ ] **Step 1: CLAUDE.md 顶部 status block 加一段**

`CLAUDE.md:1-22` 现有 Path C 状态描述。在 take_5 / Y-flip 描述之后追加一段:

```markdown
> **2026-05-09 update**: take_6 production diff 暴露非对称 frustum 截断
> (上 + 右少 ~10 px),原因是 `centerShift` 当成 post-process UV 平移只能搬
> 已渲像素,补不回 frustum 外内容。修复:`centerShift` 改走
> `CineCameraComponent.Filmback.SensorHorizontalOffset/Vertical`(UE 原生
> projection offset),shader 只剩 radial 项,radial 中心 = 图心 (0.5, 0.5)。
> SHADER_VERSION → `2026-05-09-centershift-via-projection-offset`,部署后必须
> 重跑 `build_distortion_material.run_build()`。详见
> `docs/superpowers/plans/2026-05-09-centershift-via-projection-offset.md`。
```

- [ ] **Step 2: take_6 summary 标注当前 png 是旧公式产物**

`validation_results/path_c_production/take_6/summary.md` 顶部,在状态行下方加:

```markdown
**注意**(2026-05-09):后续观察发现 `LS_test_take_6_dense.0001.png` 上 + 右
边缘比 Disguise reference 少约 10 px 内容,phase correlation 看不出来(它测
中心结构对齐,不测 frustum 范围)。这是 shader 平移补不回 frustum 外像素
的固有限制,已切到 camera projection offset 方案;计划见
`docs/superpowers/plans/2026-05-09-centershift-via-projection-offset.md`。
本 summary 的 PASS 仅针对中心结构 + Y vertical shift,不代表 frustum 完整。
```

- [ ] **Step 3: 暂不 commit**

---

## Task 7: 部署到 lanPC + Phase 1 frustum-only 渲染验证(用户操作)

> 这一步代码已写完,执行交给用户。我**只整理执行清单**,不远程操作 lanPC UE Editor。

**前置:**
- 通过 `git push` → post-commit hook → p4 depot,确保新代码到达 lanPC P4 workspace
- 或者用户手动 git pull / p4 sync

**Phase 1: frustum-only(关 radial distortion,只验 frustum 是否对准)**

- [ ] **Step 1: lanPC UE Editor 重生成 Material asset**

UE Python console:
```python
from post_render_tool import build_distortion_material
build_distortion_material.run_build()
```

预期 log:`完成: /PostRenderTool/Materials/M_PRT_OfficialSensorInverse (SHADER_VERSION=2026-05-09-centershift-via-projection-offset)`

- [ ] **Step 2: 重 import take_6 CSV**

```python
import init_post_render_tool
# UI 走 take_6 CSV → Apply mapping → Run
```

或 Python 直跑:
```python
from post_render_tool.pipeline import run_import
run_import(r"E:\RenderStream Projects\test_0311\Plugins\post-render-tool\validation_results\path_c_production\take_6\test_take_6_dense.csv", fps=24.0)
```

- [ ] **Step 3: Sequencer 里手动把 DistortionWeight 全程改为 0**

打开生成的 LevelSequence,选 PostRenderDistortionControllerComponent → DistortionWeight track → 把那一个 keyframe 的值改成 `0.0`。

(目的:关掉 radial,只让 SensorHorizontalOffset/Vertical 起作用。这样视觉差异只反映 frustum 是否对了。)

- [ ] **Step 4: MRQ 渲染单帧(frame 0)**

输出到一个临时目录,例如 `validation_results/path_c_production/take_6/phase1_frustum_only/`。

- [ ] **Step 5: 跟 Disguise reference 比较上 + 右 32 px edge strip**

比较的是:Disguise reference EXR vs 新 UE PNG。
- 如果 UE 的上 + 右边缘多出来的内容 = Disguise 看到的 → **sign 正确**,进 Phase 2
- 如果 UE 的下 + 左多了内容(方向反)→ sign 反了,在 `sequence_builder.py` 把两条 `frame.center_shift_*_mm` 改成 `-frame.center_shift_*_mm`,回到 Step 2
- 如果方向只对一个轴 → 单独翻那一轴的 sign

工具(可选):
```bash
# Mac 端跑,假设 EXR/PNG 已经 sync 回 mac
python scripts/measure_edge_strip.py \
  --ref validation_results/path_c_production/take_6/reference/screen_mr_set_1_00001.exr \
  --ue validation_results/path_c_production/take_6/phase1_frustum_only/<file>.png \
  --strip-px 32
```

> 这个脚本不存在,要现写。如果不想写脚本,肉眼对比 + screen ruler 量像素也行。32 px 内的内容差异肉眼可辨。

- [ ] **Step 6: 记录确认的 sign**

把 Phase 1 结果写到 `validation_results/path_c_production/take_6/phase1_frustum_only/summary.md`,内容包括:
- 最终 sign(`+` 或 `-`,X / Y 各自)
- 确认的 frustum offset 量(像素)
- 旧公式 / 新公式 边缘内容对比图

---

## Task 8: Phase 2 — 完整 take_6 production diff(用户操作)

- [ ] **Step 1: 把 DistortionWeight 改回 1.0**

Sequencer 里把那条 keyframe 改回 `1.0`,或者重新跑 `run_import` (默认 1.0)。

- [ ] **Step 2: MRQ 渲染 take_6 全部帧(2 帧)**

输出到 `validation_results/path_c_production/take_6/take_7_phase2/` 或同级新目录。

- [ ] **Step 3: 跟 Disguise reference 完整 diff**

```bash
python scripts/diff_exr_png.py \
  --ref validation_results/path_c_production/take_6/reference/screen_mr_set_1_00001.exr \
  --ue <new render path>
```

(diff harness 现有,见 take_6 summary 引用的工具。)

- [ ] **Step 4: 更新 take_6 summary**

记录 Phase 2 PASS / 残差量化 / 跟 Phase 1 对比。

---

## Task 9: 全部通过后,用户审核 + 一次 commit

> 所有代码改动 + 文档更新攒到这一次 commit。Commit message 中文。

- [ ] **Step 1: `git status` + `git diff` 自检改动范围**

```bash
git status
git diff --stat
```

预期 staged-able 文件:
- `Content/Python/post_render_tool/csv_parser.py`
- `Content/Python/post_render_tool/build_distortion_material.py`
- `Content/Python/post_render_tool/sequence_builder.py`
- `Content/Python/post_render_tool/tests/test_csv_parser.py`
- (可能)`Content/Python/post_render_tool/distortion_math.py` + 它的 test
- `CLAUDE.md`
- `validation_results/path_c_production/take_6/summary.md`
- `docs/superpowers/plans/2026-05-09-centershift-via-projection-offset.md`(本 plan 文件)

- [ ] **Step 2: 用户审核确认**

我把 diff 摆到对话里,等用户回 "OK" / "commit"。

- [ ] **Step 3: 用户同意后,一次 commit**

```bash
git add <files>
git commit -m "$(cat <<'EOF'
feat(distortion): centerShift 走 CineCameraComponent.Filmback.SensorOffset 替代 shader UV 平移

把 Disguise centerShift 从 post-process shader 的 sourceUV translation 迁移到
UE 原生 Filmback.SensorHorizontalOffset/Vertical → OffCenterProjectionOffset,
让 UE camera frustum 对准 principal point,补回 take_6 当前缺失的上 + 右边缘
~10px 内容(shader 平移只能搬已渲像素,补不回 frustum 外内容)。

- shader 移除 -csxUV 项,只剩 radial term;CenterUV 含义改为 radial 中心 = (0.5, 0.5)
- sequence_builder 加 SensorHorizontalOffset/Vertical 两条 float tracks,关键帧 = centerShift_*_mm
- csv_parser FrameData 加 overscan_x/y + overscan_resolution_x/y(diagnostics 用,不参与渲染)
- SHADER_VERSION → 2026-05-09-centershift-via-projection-offset,触发 metadata-tag 校验强制 run_build()
- take_6 summary 标注 0001.png 是旧公式产物,PASS 仅限中心结构

详见 docs/superpowers/plans/2026-05-09-centershift-via-projection-offset.md。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(post-commit hook 自动 push 到 p4 depot,见 CLAUDE.md "Git / P4 Workflow")

---

## Self-Review

**Spec coverage:**
- ✅ shader 移除 `-csxUV`(Task 2 Step 2)
- ✅ sequence 加两条 SensorOffset tracks(Task 4 Step 1-3)
- ✅ CenterU/V 改 0.5(Task 4 Step 3)
- ✅ FrameData 加 overscan 字段(Task 1)
- ✅ SHADER_VERSION bump(Task 2 Step 1)
- ✅ Phase 1/2 验证清单(Task 7-8)
- ✅ 文档同步(Task 6)
- ✅ Sign convention 由 Phase 1 验证 + 翻转方法(Task 7 Step 5)

**Placeholder scan:**
- 没有 TBD / TODO / "implement later"
- 所有代码块给完整内容
- Task 3 是 conditional task(只在 Step 4 失败时触发)— 写明了触发条件

**Type consistency:**
- `SensorHorizontalOffset` / `SensorVerticalOffset` UE 5.7 PascalCase(`CineCameraSettings.h:29,33` 验证过)
- property path `Filmback.SensorHorizontalOffset` / `Filmback.SensorVerticalOffset` 跟现有 `FocusSettings.ManualFocusDistance` 同模式
- `frame.center_shift_x_mm` / `center_shift_y_mm` 字段已存在,不需新增
- `_add_float_track` 现有 helper(`sequence_builder.py:201`),签名 `(binding, prop_name, prop_path)`
