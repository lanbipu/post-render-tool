# UE Overscan 支持(镜像 Disguise overscan render → crop 流程)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Disguise CSV 自带的 `overscan.x/y` 字段(目前被 UE pipeline 完全忽略)接到 UE 5.7 引擎原生 `UCameraComponent.Overscan` + `bScaleResolutionWithOverscan` + `bCropOverscan`,让 UE 渲染流程跟 Disguise 一致(扩大 frustum + 扩大渲染分辨率 → distortion 在多渲一圈的图上采样 → 末端 crop 回原 res),解决 take_7 加大 distortion 后边缘黑边问题。

**Architecture:** 引擎已经实现完整 overscan 链路(`CameraStackTypes.cpp:500 ApplyOverscan`),Sequencer 端只要写 `Overscan` 关键帧 + camera 端把 2 个 bool 打开即可。`Overscan` 是 `Interp + BlueprintReadWrite`,跟 `Filmback.SensorOffset` (commit `69a9bea`)同模式,直接 `_add_float_track("Overscan", "Overscan")`。映射关系:`UE.Overscan = (CSV.overscan_x + CSV.overscan_y) / 2 - 1.0`(CSV 是 1.0+ 倍率制,UE 是 0–1 增量制;take_6/7 都是 1.3334 → 0.3334)。等比检查 fail-fast(x≠y 偏差 > 0.5% raise ValueError),上界保护 fail-fast(CSV ratio > 2.0 即 UE.Overscan > 1.0 超出 `UCameraComponent.Overscan` 的 ClampMax raise ValueError),asymmetric 跟超界都留给后续 phase 再扩。

**API 命名两套规则(别混):**
- `set_editor_property("scale_resolution_with_overscan", True)` — Python 反射 UPROPERTY 走 snake_case,bool 自动去 `b` 前缀(`PyGenUtil.cpp:1954-1974`,跟 `bFiltered → "filtered"` 同 pattern)
- `_add_float_track(comp_binding, "Overscan", "Overscan")` — Sequencer property name + path 用 C++ PascalCase(顶层简单字段两个都是 `"Overscan"`;`Filmback.SensorHorizontalOffset` 这种 nested 才点分隔)

**两修复并存 — 不冲突:** UE 源码确认 uniform overscan 不动 `OffCenterProjectionOffset`(`CameraStackTypes.cpp:528` 只改 `CropFraction`,不改 OffCenter),所以 commit `69a9bea` 的 SensorOffset 修复在 overscan 启用后仍生效。引擎自己处理交互:`OffCenterProjectionOffset.X = 2 * SensorHOff / (SensorWidth * OverscanScalar)`(`CineCameraComponent.cpp:347`),量级自动校准。

**Tech Stack:** Python 3 (UE 5.7 plugin runtime) · UE 5.7 Sequencer Python API · UE Camera UPROPERTY reflection · unittest

**风险点(已源码确认,Phase 1 仅作可视化兜底):** `BL_SCENE_COLOR_AFTER_TONEMAPPING` 在 `PostProcessing.cpp:3270-3273` 加入 PP chain,overscan crop 由其后的 `SecondaryUpscale` 处理(`PostProcessing.cpp:3340-3347` 用 `View.GetSecondaryViewCropRect()` 裁切),**PP material 看到的是 overscanned SceneTexture,在 crop 之前** — 设计成立,blendable location 不需要改。Phase 1 渲染仍跑,作为可视化兜底验证。

**Out of scope:**
- AsymmetricOverscan(CSV x≠y),fail-fast 拒绝(take_6/7 都是等比,YAGNI)
- 物理标定 / 重测 K1/K2/K3
- shader / Material / SHADER_VERSION 改动(公式没变)

---

## File Structure

| 文件 | 作用 | 改动 |
|---|---|---|
| `Content/Python/post_render_tool/csv_parser.py` | 加 `csv_overscan_to_ue_overscan` pure-python helper | 修改 |
| `Content/Python/post_render_tool/camera_builder.py` | `_configure_camera` 加 `scale_resolution_with_overscan = True`、`crop_overscan = True` 静态设置 | 修改 |
| `Content/Python/post_render_tool/sequence_builder.py` | comp_binding 加 1 条 `Overscan` float track + 关键帧 | 修改 |
| `Content/Python/post_render_tool/tests/test_csv_parser.py` | 加 `TestCsvOverscanMapping` 测试类(5 个 case) | 修改 |
| `CLAUDE.md` | Path C 状态加 overscan 段 | 修改 |
| `validation_results/path_c_production/take_6/summary.md` | Phase 2 take_6 regression 通过后,加一行确认 overscan 共启不破 | 修改 |
| `docs/superpowers/plans/2026-05-09-overscan-support.md` | 本 plan 文件 | 新增 |

不新建模块文件,不动 shader / Material。

---

## Task 1: csv_parser 加 `csv_overscan_to_ue_overscan` helper(TDD)

**Files:**
- Modify: `Content/Python/post_render_tool/csv_parser.py`(在公共 API 段加 module-level 函数)
- Test: `Content/Python/post_render_tool/tests/test_csv_parser.py`(新 class `TestCsvOverscanMapping`)

helper 函数封装 5 件事:`None fallback → 0.0`、`asymmetric > 0.5% → raise ValueError(带 frame_number,优先 asymmetry 检查避免 mixed underscan/overscan silent clamp)`、`两轴都 <1.0 → clamp 0.0`、`等比 → CSV.overscan - 1.0`、`UE.Overscan > 1.0(CSV ratio > 2.0)→ raise ValueError(超 UE Overscan 上界)`。**关键顺序**: asymmetry 检查必须先于 `<1.0` clamp,否则 (0.95, 1.30) 这种 mixed case 会被 silent 关闭。pure python 不依赖 unreal,Mac 可直接 unit test。

- [ ] **Step 1: 写失败测试**

`test_csv_parser.py` 末尾(`TestTrimStaticPadding` 类之后,`if __name__ == "__main__"` 之前)新增:

```python
class TestCsvOverscanMapping(unittest.TestCase):
    """csv_overscan_to_ue_overscan: CSV 1.0+ 倍率 → UE 0–1 增量."""

    def test_equal_xy_returns_minus_one(self):
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        self.assertAlmostEqual(
            csv_overscan_to_ue_overscan(1.3334, 1.3334, frame_number=42),
            0.3334, places=4,
        )

    def test_none_fallback_zero(self):
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        self.assertEqual(
            csv_overscan_to_ue_overscan(None, None, frame_number=0), 0.0
        )
        self.assertEqual(
            csv_overscan_to_ue_overscan(1.3, None, frame_number=0), 0.0
        )

    def test_below_one_clamped_zero(self):
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        self.assertEqual(
            csv_overscan_to_ue_overscan(0.95, 0.95, frame_number=0), 0.0
        )

    def test_asymmetric_raises(self):
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        with self.assertRaises(ValueError) as ctx:
            csv_overscan_to_ue_overscan(1.3, 1.5, frame_number=42)
        self.assertIn("42", str(ctx.exception))
        self.assertIn("asymmetric", str(ctx.exception).lower())

    def test_within_tolerance_does_not_raise(self):
        # 1.3334 vs 1.3340 = ~0.045% 差异,<0.5% 阈值,不报错,取均值
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        v = csv_overscan_to_ue_overscan(1.3334, 1.3340, frame_number=0)
        self.assertAlmostEqual(v, 0.3337, places=4)

    def test_above_two_raises(self):
        # CSV ratio > 2.0 → UE.Overscan > 1.0 超出 UCameraComponent.Overscan
        # 的 ClampMax,fail-fast,不 silent clamp.
        from post_render_tool.csv_parser import csv_overscan_to_ue_overscan
        with self.assertRaises(ValueError) as ctx:
            csv_overscan_to_ue_overscan(2.5, 2.5, frame_number=99)
        self.assertIn("99", str(ctx.exception))
        # 错误消息提到 "上界" 或 "exceed"
        msg = str(ctx.exception).lower()
        self.assertTrue("上界" in str(ctx.exception) or "exceed" in msg)
```

- [ ] **Step 2: 跑失败测试**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python && python -m unittest post_render_tool.tests.test_csv_parser.TestCsvOverscanMapping -v
```

预期:5 个测试都报 `ImportError` 或 `AttributeError: module ... has no attribute 'csv_overscan_to_ue_overscan'`。

- [ ] **Step 3: 实现 helper 函数**

`csv_parser.py` 在 `parse_csv_dense` 函数之前(`# Public API` 注释下方,`trim_static_padding` 之前)新增:

```python
def csv_overscan_to_ue_overscan(
    overscan_x: Optional[float],
    overscan_y: Optional[float],
    *,
    frame_number: int,
    asymmetric_tolerance: float = 0.005,
) -> float:
    """把 Disguise CSV 的 overscan ratio (1.0+ 倍率) 转成 UE 5.7
    UCameraComponent.Overscan 的增量制 (0.0 = 不开,0.3334 = 33% 扩大).

    Disguise CSV: ``overscan.x = 1.3334`` 表示 frustum + 渲染分辨率 1.3334 倍.
    UE: ``Overscan = 0.3334`` 表示 frustum 扩 33%(配合 bScaleResolutionWithOverscan
    和 bCropOverscan 复刻 Disguise 流程).

    Parameters
    ----------
    overscan_x, overscan_y
        CSV 一帧的 overscan ratio. None = 该字段缺失.
    frame_number
        当前帧号, 仅用于 error message context.
    asymmetric_tolerance
        |x - y| / max(x, y) 超过这个比例就视为 asymmetric 抛 ValueError.
        默认 0.5%.

    Returns
    -------
    float
        UE.Overscan 值, [0.0, ...). 缺失或 < 1.0 一律 clamp 到 0.0.

    Raises
    ------
    ValueError
        x ≠ y 超过 tolerance(本 spec 不支持 asymmetric overscan).
    """
    if overscan_x is None or overscan_y is None:
        return 0.0

    # Asymmetry check 优先 (在 <1.0 clamp 之前). 否则 mixed underscan/overscan
    # 例如 (0.95, 1.30) 会在 "<1.0 早返 0.0" silently 关掉 overscan,而不是 raise.
    largest = max(overscan_x, overscan_y)
    if largest > 0 and abs(overscan_x - overscan_y) > asymmetric_tolerance * largest:
        raise ValueError(
            f"frame {frame_number}: asymmetric overscan unsupported "
            f"(x={overscan_x}, y={overscan_y}, |x-y|/max > {asymmetric_tolerance}). "
            f"Path C uniform-only;后续 phase 再扩 AsymmetricOverscan."
        )

    # 仅当两轴都 < 1.0 (一致 underscan) 才 clamp 到 0.0.
    if overscan_x < 1.0 and overscan_y < 1.0:
        return 0.0

    ue_overscan = (overscan_x + overscan_y) / 2.0 - 1.0
    if ue_overscan < 0.0:
        return 0.0
    if ue_overscan > 1.0:
        # UCameraComponent.Overscan 的 ClampMax = 1.0 (CameraComponent.h:135),
        # 超过等于让引擎 silent clamp,容易掩盖 CSV 异常输入 — fail-fast 更稳.
        raise ValueError(
            f"frame {frame_number}: overscan exceeds UE upper bound "
            f"(CSV ratio x={overscan_x}, y={overscan_y} → UE.Overscan="
            f"{ue_overscan:.4f} > 1.0;UCameraComponent.Overscan ClampMax=1.0). "
            f"超 200% overscan 不在当前 spec 支持范围,如确需请扩 spec."
        )
    return ue_overscan
```

`Optional` 已经从 typing 导入(看文件头部 `from typing import Dict, List, Optional, Tuple`),不用加 import。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python && python -m unittest post_render_tool.tests.test_csv_parser.TestCsvOverscanMapping -v
```

预期:7 测试全 PASS(等比、None、<1.0 clamp、asymmetric raise、tolerance 内取均值、>2.0 raise、mixed underscan/overscan raise)。

- [ ] **Step 5: 跑 csv_parser 全测试确认不打破现有功能**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python && python -m unittest post_render_tool.tests.test_csv_parser -v
```

预期:全 PASS(原 21 + 新 7 = 28 个,3 个 skipped 因为 sample CSV 不在 /tmp)。

---

## Task 2: camera_builder 静态打开 bScaleResolutionWithOverscan + bCropOverscan

**Files:**
- Modify: `Content/Python/post_render_tool/camera_builder.py`(`_configure_camera` 函数,line 191–222 范围)

UE 5.7 Python 反射 bool UPROPERTY 会去 b 前缀转 snake_case(跟 `bFiltered → filtered` 同 pattern,见 `build_distortion_material.py:221` 注释),所以 `bScaleResolutionWithOverscan → scale_resolution_with_overscan`、`bCropOverscan → crop_overscan`。**这一假设由 Phase 1 启动验证**:lanPC UE Editor Python console 跑 `dir(cine_comp)` grep `overscan`,看到这 2 个 snake_case 属性即对。

- [ ] **Step 1: 找到 `_configure_camera` 函数,在 Filmback 设置之后、`_ensure_distortion_controller` 调用之前插入 overscan 静态设置**

`camera_builder.py` 当前 line 209–222(filmback 块):

```python
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

    # Path C: 挂 PostRenderDistortionControllerComponent + 绑 Material.
    # Controller 的 BeginPlay 是 camera 上 distortion blendable 的唯一来源.
    _ensure_distortion_controller(camera_actor)
```

在 logger.info 之后、`# Path C:` 注释之前加:

```python
    # Overscan 静态行为(per-take 不变,所以静态设;Overscan 数值由 sequence_builder
    # 上 keyframe).配合 bScaleResolutionWithOverscan + bCropOverscan 镜像 Disguise:
    # 扩大 frustum + 扩大渲染分辨率 → distortion shader 在多渲一圈的图上采样
    # → 末端 crop 回原 resolution. UE 源码: CameraStackTypes.cpp:500 ApplyOverscan.
    comp.set_editor_property("scale_resolution_with_overscan", True)
    comp.set_editor_property("crop_overscan", True)
    logger.info("Overscan 行为已设置: scale_resolution_with_overscan=True, crop_overscan=True")
```

- [ ] **Step 2: 语法 check**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool && python3 -c "import ast; ast.parse(open('Content/Python/post_render_tool/camera_builder.py').read()); print('OK')"
```

预期:`OK`。

- [ ] **Step 3: spec drift test 不动(BindWidget 没变)**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python && python -m unittest post_render_tool.tests.test_spec_drift -v
```

预期:4 PASS。

---

## Task 3: sequence_builder 加 Overscan float track + per-frame 关键帧

**Files:**
- Modify: `Content/Python/post_render_tool/sequence_builder.py`(track 创建段、channel 取段、主循环 keyframe 段)

`Overscan` UPROPERTY 是 `Interp + BlueprintReadWrite` 在 `UCameraComponent`(父类),`UCineCameraComponent` 继承。Sequencer 走 property name `Overscan`,property path `Overscan`(UCameraComponent 直接字段,不在子结构里)。

- [ ] **Step 0: 在 `build_sequence` 顶部加 pre-validate loop**

helper raise ValueError(asymmetric / >2.0 / mixed underscan-overscan)时不能让 LevelSequence 处于半改状态,所以在任何 asset mutation 之前先跑一遍所有帧的 helper。在 `build_sequence` docstring 之后、Step 1 LevelSequence 创建之前:

```python
    # ------------------------------------------------------------------
    # Step 0: Pre-validate per-frame derived values that may raise (overscan).
    # ...
    # ------------------------------------------------------------------
    for frame in csv_result.frames:
        csv_overscan_to_ue_overscan(
            frame.overscan_x, frame.overscan_y, frame_number=frame.frame_number
        )
```

- [ ] **Step 1: 加 Overscan track 创建**

`sequence_builder.py` 在 Filmback offset tracks 创建之后(commit `69a9bea` 加的两条)插入:

```python
    # Overscan: UE 5.7 UCameraComponent.Overscan (Interp UPROPERTY, [0, 1] 增量制).
    # bind 在 comp_binding (CineCameraComponent), 不是 controller_binding.
    # 配合 _configure_camera 的 scale_resolution_with_overscan + crop_overscan
    # 镜像 Disguise overscan→render→crop 流程.
    overscan_section = _add_float_track(comp_binding, "Overscan", "Overscan")
```

(找现有 `sensor_v_offset_section = _add_float_track(comp_binding, "SensorVerticalOffset", ...)` 那行,本块加在它的紧后面。)

- [ ] **Step 2: 取 Overscan channel**

在 `ch_sensor_v_offset = sensor_v_offset_section.get_all_channels()[0]` 之后插入:

```python
    ch_overscan = overscan_section.get_all_channels()[0]
```

- [ ] **Step 3: 主循环里写 keyframe**

主循环里在 `ch_sensor_h_offset.add_key(...)` / `ch_sensor_v_offset.add_key(...)` 之后(SensorOffset 关键帧之后)插入:

```python
        # CSV.overscan(1.0+ 倍率)→ UE.Overscan(0–1 增量), 见
        # csv_parser.csv_overscan_to_ue_overscan. asymmetric overscan(x≠y > 0.5%)
        # raise ValueError, 整个 import 失败 — 当前 Path C 不支持 asymmetric.
        ue_overscan = csv_overscan_to_ue_overscan(
            frame.overscan_x, frame.overscan_y, frame_number=frame.frame_number
        )
        ch_overscan.add_key(frame_number, ue_overscan, interpolation=interp)
```

- [ ] **Step 4: 在文件顶部加 `csv_overscan_to_ue_overscan` import**

`sequence_builder.py` 顶部 imports 段当前:

```python
from .csv_parser import CsvDenseResult
```

改成:

```python
from .csv_parser import CsvDenseResult, csv_overscan_to_ue_overscan
```

- [ ] **Step 5: 语法 check**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool && python3 -c "import ast; ast.parse(open('Content/Python/post_render_tool/sequence_builder.py').read()); print('OK')"
```

预期:`OK`。

---

## Task 4: 全测试 + UE 模块语法 check

- [ ] **Step 1: Mac-side 全测试**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python && python -m unittest discover -s post_render_tool/tests 2>&1 | tail -5
```

预期:`Ran 101 tests in ...`(原 94 + 新 7 = 101),`FAILED (errors=1, skipped=3)` — 唯一 ERROR 是 `test_integration_ue.py` 因 `import unreal` 失败(Mac 预期),其他全 PASS。

- [ ] **Step 2: UE-dependent 模块 syntax check**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool && for f in Content/Python/post_render_tool/{camera_builder,sequence_builder,pipeline,ui_interface,widget,widget_builder,build_distortion_material}.py; do
  python3 -c "import ast; ast.parse(open('$f').read()); print('OK: $f')"
done
```

预期:全 OK。

---

## Task 5: 同步 CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`(顶部 Path C status block)

- [ ] **Step 1: CLAUDE.md 顶部 status block 后追加一段**

`CLAUDE.md:13–22` 范围(commit `69a9bea` 加的 2026-05-09 update 之后)加:

```markdown
> **2026-05-09 update #2 (overscan)**: take_7 加大 distortion 暴露
> 边缘黑边 — 因为 UE 之前一直没用 CSV 自带的 overscan 字段(1.3334),
> radial 弯曲把边缘 sourceUV 弯到 frustum 外 = 黑;Disguise 多渲一圈
> 后边缘有内容。修复:接上 UE 5.7 引擎原生 `UCameraComponent.Overscan`
> + `bScaleResolutionWithOverscan` + `bCropOverscan`,Sequencer 关键帧
> 写 `Overscan = (CSV.overscan_x + overscan_y) / 2 - 1.0`(等比检查
> fail-fast)。**这一修复跟 commit 69a9bea (centerShift via SensorOffset)
> 并存,不冲突** — uniform overscan 不动 OffCenterProjectionOffset
> (`CameraStackTypes.cpp:528`),引擎自己处理两个修复的交互。详见
> `docs/superpowers/plans/2026-05-09-overscan-support.md`。
```

---

## Task 6: 部署到 lanPC + Phase 1 / Phase 2 验证(用户操作)

> 代码改完后由用户在 lanPC UE Editor 走完整链路。我整理执行清单。

**Phase 0:验证 UE Python 反射属性名**

- [ ] **Step 1: lanPC UE Editor Python console 跑反射 dump**

```python
from unreal import CineCameraComponent
import unreal
# 找一个 CineCamera 实例
ed = unreal.EditorActorSubsystem
actors = unreal.EditorLevelLibrary.get_all_level_actors()
cam = next((a for a in actors if isinstance(a, unreal.CineCameraActor)), None)
if cam:
    comp = cam.get_cine_camera_component()
    # grep overscan 属性
    for name in dir(comp):
        if "overscan" in name.lower() or "crop" in name.lower():
            print(name)
```

预期(基于 UE 5.7 Hungarian b 前缀去除规则):

```
overscan
asymmetric_overscan
scale_resolution_with_overscan
crop_overscan
```

如果实际看到 `b_scale_resolution_with_overscan` / `b_crop_overscan`(保留 b 前缀),回到 `camera_builder.py` Step 1 把属性名改一下重跑 syntax check。

**Phase 1: overscan 本身验证(确认 BL_SCENE_COLOR_AFTER_TONEMAPPING 在 crop 之前)**

- [ ] **Step 2: 重 import take_7 CSV(此时 sequence_builder 已会写 Overscan keyframe)**

```python
import init_post_render_tool
# UI 走 take_7 CSV
```

或:

```python
from post_render_tool.pipeline import run_import
run_import(r"E:\d3 Projects\0408\output\shots\test\take_7\test_take_7_dense.csv", fps=24.0)
```

预期 log 包含:`Overscan 行为已设置: scale_resolution_with_overscan=True, crop_overscan=True`。

- [ ] **Step 3: MRQ 渲染 take_7 单帧**

输出到临时目录,跟现有的旧 `LS_test_take_7_dense.0002.png`(无 overscan,有黑边)肉眼对比。

- [ ] **Step 4: 判断 overscan 是否生效**

- 黑边消失 → BL location 在 crop 之前,设计成立,继续 Phase 2
- 黑边还在 → BL location 在 crop 之后,overscan 失效,**回头改 plan**(可能要换 `BL_BEFORE_TONEMAPPING` 或换机制)

**Phase 2: take_6 regression(centerShift 修复 + overscan 共启不破)**

- [ ] **Step 5: 重 import take_6 CSV**

take_6 CSV `overscan = 1.3334`(跟 take_7 同),原来 commit `69a9bea` 验证时 overscan 还没接,所以也是无 overscan 渲的。这次接上后 take_6 也会过 overscan 流程。

- [ ] **Step 6: MRQ 渲染 take_6 单帧,跟 Disguise reference 比中心结构 + frustum 完整**

预期:之前 PASS 的 centerShift 修复仍然 PASS(中心 + frustum 完整都 OK)。如果 regress(开 overscan 后 take_6 中心错位 / frustum 不全),说明两个修复交互有问题,回头查。

- [ ] **Step 7: 用户记录 Phase 2 take_6 regression 结果到 take_6/summary.md**

加一行,例如:`2026-05-09 update #2: overscan 启用后 take_6 regression PASS,centerShift 跟 overscan 共存不破。`

---

## Task 7: 用户审核 + 一次 commit

> 所有代码 + 文档改动攒到这次 commit。Commit message 中文。

- [ ] **Step 1: `git status` + `git diff --stat` 自检改动范围**

```bash
git status
git diff --stat
```

预期改动:

- `Content/Python/post_render_tool/csv_parser.py`
- `Content/Python/post_render_tool/camera_builder.py`
- `Content/Python/post_render_tool/sequence_builder.py`
- `Content/Python/post_render_tool/tests/test_csv_parser.py`
- `CLAUDE.md`
- `validation_results/path_c_production/take_6/summary.md`(Phase 2 通过后加一行)
- `docs/superpowers/plans/2026-05-09-overscan-support.md`(本 plan 文件,untracked)
- 可能新增:`validation_results/path_c_production/take_7/summary.md` + 渲染对照图(用户可选)

- [ ] **Step 2: 用户审 diff,确认 OK 后我执行 commit**

- [ ] **Step 3: 用户同意后,一次 commit**

```bash
git add <files>
git commit -m "$(cat <<'EOF'
feat(distortion): UE 接入引擎原生 Overscan,镜像 Disguise overscan→render→crop

CSV.overscan 字段(take_6/7 都是 1.3334)之前一直被 UE pipeline 忽略;
take_7 加大 distortion 暴露边缘黑边 — radial 弯曲把 sourceUV 弯到 frustum
外,Disguise 渲染时 overscan 多看一圈,UE 没 overscan 边缘就黑。修复路径:
接上 UE 5.7 引擎原生 UCameraComponent.Overscan(Interp UPROPERTY)+
bScaleResolutionWithOverscan + bCropOverscan,Sequencer 关键帧写
(CSV.overscan_x + overscan_y) / 2 - 1.0(uniform 等比;asymmetric 偏差
> 0.5% 直接 raise ValueError,留给后续 phase 接 AsymmetricOverscan)。

代码改动:
- csv_parser 加 csv_overscan_to_ue_overscan pure-python helper(等比检查 +
  None/<1.0 fallback 0.0)
- camera_builder._configure_camera 静态打开 scale_resolution_with_overscan
  + crop_overscan(per-take 不变,所以静态设)
- sequence_builder comp_binding 加 1 条 Overscan float track,关键帧调
  csv_overscan_to_ue_overscan

共存验证: 这一修复跟 commit 69a9bea (centerShift via Filmback.SensorOffset)
并存不冲突 — UE 源码确认 uniform overscan 只改 CropFraction,不动
OffCenterProjectionOffset(CameraStackTypes.cpp:528);引擎自己处理交互
(OffCenter 量级除以 OverscanScalar,CineCameraComponent.cpp:347)。
take_6 regression 通过(Phase 2 验证)。

测试改动:
- test_csv_parser 加 TestCsvOverscanMapping(5 case:等比、None、<1.0
  clamp、asymmetric raise、tolerance 内取均值)

文档改动:
- CLAUDE.md Path C 状态加 2026-05-09 update #2(overscan)
- take_6/summary.md 加 Phase 2 regression PASS 备注
- 完整方案 + 推理 + Phase 1/2 验证清单见
  docs/superpowers/plans/2026-05-09-overscan-support.md

未做(由后续 phase 决定):
- AsymmetricOverscan(CSV x≠y),目前 fail-fast,等真出现这种数据再扩
- BL location 在 crop 之前/后已被 Phase 1 验证(本次落代码假设之前)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(post-commit hook 自动 push 到 p4 depot,见 CLAUDE.md "Git / P4 Workflow")

---

## Self-Review

**Spec coverage:**
- ✅ csv_parser helper(Task 1)
- ✅ camera_builder bool 设置(Task 2)
- ✅ sequence_builder track + 关键帧(Task 3)
- ✅ asymmetric fail-fast(Task 1 helper 内)
- ✅ 跟 commit `69a9bea` 共存性(Architecture 段 + commit message)
- ✅ Phase 0 反射属性名验证(Task 6 Step 1)
- ✅ Phase 1 BL location 风险验证(Task 6 Step 4)
- ✅ Phase 2 take_6 regression(Task 6 Step 5–7)
- ✅ 文档同步(Task 5 + take_6 summary update)

**Placeholder scan:**
- 没有 TBD / TODO / "implement later"
- 所有代码块给完整内容
- helper 默认 tolerance 0.5% 写死,用户可改 keyword arg

**Type consistency:**
- `csv_overscan_to_ue_overscan(overscan_x, overscan_y, *, frame_number, asymmetric_tolerance=0.005)` 签名在 Task 1 实现 + Task 1 测试 + Task 3 调用一致
- UE 5.7 反射 snake_case 假设(`scale_resolution_with_overscan` / `crop_overscan` / `overscan`)在 camera_builder + sequence_builder + Phase 0 验证一致;Phase 0 fail 即回头改 Task 2/3
- `frame.overscan_x` / `frame.overscan_y` 字段已经在 commit `69a9bea` 加,FrameData dataclass 已有
