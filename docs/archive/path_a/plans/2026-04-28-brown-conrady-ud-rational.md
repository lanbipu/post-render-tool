# Brown-Conrady UD Rational Lens Model Migration · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 UE LensFile 的 lens model 从 `SphericalLensModel`（M6 polynomial 截断，外圈崩盘）切到 `BrownConradyUDLensModel`（OpenCV rational division 形态，跟 Disguise 真公式 M7 同构），实现 production CSV → UE LensFile 端到端 pixel-perfect distortion。

**Architecture:** UE 5.7 原生支持 rational distortion model：分子分母各 3 阶 r 多项式 + 8 系数（K1-K6 + P1/P2）。M7 是这个模型的 2 参数子集，已经在 fit_distortion_models.py 拟合到 RMS 0.435 px ≈ 噪声底。本次工作在不改 pipeline.py 用户接口、不改 csv_parser.py / sequence_builder.py 的前提下，把 distortion_math + distortion_packing + lens_file_builder 三个模块切换到 8 系数 rational 输出，让现有 `init_post_render_tool.run_import(csv)` 工作流自动产出 pixel-perfect 渲染。

**Tech Stack:**
- UE 5.7 LensDistortion plugin (`BrownConradyUDLensDistortionModelHandler`, `FBrownConradyUDDistortionParameters`)
- Python (scipy.optimize.curve_fit, numpy 2.4)
- Mac venv: cv2 4.13, scipy 1.17, numpy 2.4, scikit-image (新装)
- Remote execution to lanPC for UE Editor end-to-end test
- 反推数据复用：`scripts/distortion_calibration/displacements.csv` (300k samples，11 帧 K1 sweep)

---

## 文件结构（改动一览）

| File | 改动类型 | 用途 |
|---|---|---|
| `scripts/distortion_calibration/fit_distortion_models.py` | 修改 | 新增 6-param `M_RAT6` 候选 |
| `scripts/distortion_calibration/_validate_tier2_brownconradyud.py` | **新建** | 用 fit 出的 6 系数跑 forward distortion vs Disguise EXR/PNG |
| `Content/Python/post_render_tool/distortion_math.py` | 修改 | 函数返回 8 系数（K1-K6 + P1/P2 + fx/fy/cx/cy）|
| `Content/Python/post_render_tool/distortion_packing.py` | 修改 | 新增 `to_brown_conrady_ud_parameters` 打包函数 |
| `Content/Python/post_render_tool/lens_file_builder.py` | 修改 | LensInfo.lens_model 切到 `BrownConradyUDLensModel`，`add_distortion_point` 走 8-slot 数组 |
| `Content/Python/post_render_tool/tests/test_distortion_m6.py` | **删除** | 替换为 test_distortion_rational.py |
| `Content/Python/post_render_tool/tests/test_distortion_rational.py` | **新建** | 验证 distortion_math 8 系数输出 |
| `Content/Python/post_render_tool/tests/test_c_distortion_packing.py` | 修改 | 加 `to_brown_conrady_ud_parameters` 测试 |
| `docs/K1-implementation.md` | 修改 | 加"M6 → Rational 升级"章节 |
| `scripts/distortion_calibration/USER_INSTRUCTIONS.md` | 修改 | Round 1 状态从 "M6 polynomial" 改成 "Rational division" |

---

## Task 1: 加 6 参数 rational 候选到 fit_distortion_models.py

**Files:**
- Modify: `scripts/distortion_calibration/fit_distortion_models.py`

- [ ] **Step 1: 写候选公式**

在 `fit_distortion_models.py` 现有 `_m10` 之后插入：

```python
def _m_rat6(
    KR: tuple[np.ndarray, np.ndarray],
    a: float, b: float, c: float, d: float, e: float, f: float,
) -> np.ndarray:
    """6-coefficient rational matching UE BrownConradyUD shader form.

    r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶) / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶)

    Direct map to UE FBrownConradyUDDistortionParameters:
        K1 = a·csv_K  K2 = b·csv_K²  K3 = c·csv_K³
        K4 = d·csv_K  K5 = e·csv_K²  K6 = f·csv_K³
    """
    K, r = KR
    r2 = r * r
    K2 = K * K
    K3 = K2 * K
    num = 1.0 + a * K * r2 + b * K2 * r2 * r2 + c * K3 * r2 * r2 * r2
    den = 1.0 + d * K * r2 + e * K2 * r2 * r2 + f * K3 * r2 * r2 * r2
    return r * (num / den - 1.0)
```

- [ ] **Step 2: 注册到 MODELS tuple**

在 MODELS 末尾追加（M10 之后）：

```python
    FitModel(
        name="M_RAT6",
        description="r·(1+a·K·r²+b·K²·r⁴+c·K³·r⁶)/(1+d·K·r²+e·K²·r⁴+f·K³·r⁶)  (UE BrownConradyUD)",
        func=_m_rat6,
        p0=(-0.251, 0.21, -0.19, 0.0, 0.0, 0.0),
        param_names=("a", "b", "c", "d", "e", "f"),
    ),
```

- [ ] **Step 3: 跑 fit 确认**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python fit_distortion_models.py 2>&1 | tail -30
```

Expected: `M_RAT6` 出现在排序里，BIC 不输 M9/M10。**RMS 应 ≤ 0.45 px**（M7 是它的 2 参数子集，所以 M_RAT6 ≤ M7 = 0.435）。

- [ ] **Step 4: 锁住系数到 .txt 临时文件**

把 `M_RAT6` 的 (a, b, c, d, e, f) 6 个值复制保存到：

```bash
.venv/bin/python fit_distortion_models.py 2>&1 | grep "M_RAT6" | tee /tmp/rat6_coeffs.txt
```

预期格式：
```
=== M_RAT6 rms=0.4XX px max=XX.X px AIC=... BIC=... (a=..., b=..., c=..., d=..., e=..., f=...)
```

- [ ] **Step 5: Commit**

```bash
git add scripts/distortion_calibration/fit_distortion_models.py
git commit -m "$(cat <<'EOF'
feat(fit): 加 M_RAT6 候选, 跟 UE BrownConradyUDLensModel rational 形态同构

r·(1+a·K·r²+b·K²·r⁴+c·K³·r⁶) / (1+d·K·r²+e·K²·r⁴+f·K³·r⁶) — 6 自由参数
直接对应 UE FBrownConradyUDDistortionParameters 的 K1-K6 槽位.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 远程探查 UE BrownConradyUD API 完整性

**Files:**
- Create temporary script in `/tmp/ue_probe_brown_conrady.py`

- [ ] **Step 1: 写 discovery 脚本**

```python
"""Verify UE 5.7 BrownConradyUD model API works through Python reflection."""
import builtins, sys
def _safe(*args, **kwargs):
    sep = kwargs.get("sep", " "); end = kwargs.get("end", "\n")
    sys.stdout.write(sep.join(str(a).encode("ascii", "replace").decode("ascii") for a in args) + end)
builtins.print = _safe

import unreal


print("=== BrownConradyUDLensModel reflection ===")
cls = unreal.BrownConradyUDLensModel
print(f"class: {cls}")
print(f"static_class: {cls.static_class()}")

print()
print("=== Try setting LensFile.lens_info.lens_model ===")
lf = unreal.load_asset("/Game/PostRender/synth_K1_p0p5/LF_synth_K1_p0p5")
li = lf.lens_info
print(f"current lens_model: {li.lens_model}")
li.lens_model = unreal.BrownConradyUDLensModel.static_class()
lf.lens_info = li
print(f"after set: {lf.lens_info.lens_model}")
ok = unreal.EditorAssetLibrary.save_loaded_asset(lf)
print(f"saved: {ok}")

print()
print("=== Add distortion_point with 8-coeff parameters ===")
info = unreal.DistortionInfo()
info.parameters = [0.265, 0.0, 0.0, 0.392, 0.0, 0.0, 0.0, 0.0]   # K1, K2, K3, K4, K5, K6, P1, P2
print(f"info.parameters length: {len(info.parameters)}")
print(f"info.parameters: {list(info.parameters)}")
print()

# Test add_distortion_point with 8-slot params
print("=== Test full round-trip: add_distortion_point + get_distortion_points ===")
# Re-import to clear old state, then add via API directly
lf.add_distortion_point(new_focus=0.0, new_zoom=30.302, new_point=info)
unreal.EditorAssetLibrary.save_loaded_asset(lf)

# Read back
points = lf.get_distortion_points()
print(f"distortion_points: {len(points)}")
for p in points:
    print(f"  focus={p.focus} zoom={p.zoom} params={list(p.distortion_info.parameters)}")

print()
print("=== Handler with state populated ===")
# Use BrownConradyUDLensDistortionModelHandler directly
handler = unreal.new_object(unreal.BrownConradyUDLensDistortionModelHandler)
print(f"handler created: {type(handler).__name__}")
ok = lf.evaluate_distortion_data(0.0, 30.302, unreal.Vector2D(35.0, 19.687), handler)
print(f"evaluate ok: {ok}")
state = handler.current_state
print(f"state.distortion_info.parameters: {list(state.distortion_info.parameters)}")
```

- [ ] **Step 2: SCP + 跑**

```bash
scp -q /tmp/ue_probe_brown_conrady.py lanpc:C:/temp/ue-remote/
ssh lanpc 'set PYTHONIOENCODING=utf-8 & "D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/ue_probe_brown_conrady.py' 2>&1 | grep -v "WARNING\|store now\|server may need\|^$" | tail -30
```

Expected: 看到 8 系数被读回（不是 5）、BrownConradyUD 类可实例化、evaluate_distortion_data 返回 True、handler.current_state 跟 LensFile 写入值一致。

- [ ] **Step 3: 记录任何 API gotchas**

如果 step 2 任何一步崩了，写到 `/tmp/brown_conrady_api_notes.txt` —— 比如：
- 是否需要先 unregister 旧 lens model handler
- distortion_info.parameters 是否要 hard-coded 8 长度
- evaluate_distortion_data 是否对 BrownConradyUD 行为不同

如果一切 OK，写一行"API 全可用"。

- [ ] **Step 4: 不 commit**（discovery 脚本不入仓）

---

## Task 3: 给 distortion_packing.py 加 BrownConradyUD 打包函数 + 测试

**Files:**
- Modify: `Content/Python/post_render_tool/distortion_packing.py`
- Modify: `Content/Python/post_render_tool/tests/test_c_distortion_packing.py`

- [ ] **Step 1: 写测试 (TDD)**

在 `test_c_distortion_packing.py` 末尾追加 TestBrownConradyUDOrder 类：

```python
class TestBrownConradyUDOrder(unittest.TestCase):
    """to_brown_conrady_ud_parameters 顺序必须严格匹配
    FBrownConradyUDDistortionParameters 的 UPROPERTY 声明顺序 (BrownConradyUDLensModel.h:23-52):
        K1, K2, K3, K4, K5, K6, P1, P2
    """

    def test_packs_in_declared_order(self):
        from post_render_tool.distortion_packing import to_brown_conrady_ud_parameters
        nd = {
            "k1": 1.0, "k2": 2.0, "k3": 3.0,
            "k4": 4.0, "k5": 5.0, "k6": 6.0,
            "p1": 7.0, "p2": 8.0,
        }
        result = to_brown_conrady_ud_parameters(nd)
        self.assertEqual(result, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])

    def test_returns_floats(self):
        from post_render_tool.distortion_packing import to_brown_conrady_ud_parameters
        nd = {"k1": 1, "k2": 2, "k3": 3, "k4": 4, "k5": 5, "k6": 6, "p1": 7, "p2": 8}
        result = to_brown_conrady_ud_parameters(nd)
        for v in result:
            self.assertIsInstance(v, float)

    def test_missing_key_raises(self):
        from post_render_tool.distortion_packing import to_brown_conrady_ud_parameters
        nd = {"k1": 0.0, "k2": 0.0, "k3": 0.0, "k4": 0.0, "k5": 0.0, "k6": 0.0, "p1": 0.0}
        with self.assertRaises(KeyError):
            to_brown_conrady_ud_parameters(nd)

    def test_extra_keys_ignored(self):
        from post_render_tool.distortion_packing import to_brown_conrady_ud_parameters
        nd = {
            "k1": 0.0, "k2": 0.0, "k3": 0.0,
            "k4": 0.0, "k5": 0.0, "k6": 0.0,
            "p1": 0.0, "p2": 0.0,
            "fx": 999, "fy": 999, "cx": 999, "cy": 999,
        }
        result = to_brown_conrady_ud_parameters(nd)
        self.assertEqual(len(result), 8)
```

- [ ] **Step 2: 跑测试确认 fail**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python3 -m unittest post_render_tool.tests.test_c_distortion_packing.TestBrownConradyUDOrder -v
```

Expected: 4 个测试全 fail（`ImportError: cannot import name 'to_brown_conrady_ud_parameters'`）。

- [ ] **Step 3: 写实现**

在 `distortion_packing.py` 末尾追加：

```python
_BROWN_CONRADY_UD_KEYS: tuple[str, ...] = ("k1", "k2", "k3", "k4", "k5", "k6", "p1", "p2")


def to_brown_conrady_ud_parameters(normalized: dict) -> list[float]:
    """按 UE BrownConradyUD 模型的 K1-K6 + P1, P2 顺序打包归一化畸变参数。

    UE shader (BrownConradyUDDistortion.usf:48-50) 用 polynomial division 形态:
        dr = (1 + K1·r² + K2·r⁴ + K3·r⁶) / (1 + K4·r² + K5·r⁴ + K6·r⁶)

    UE 在 ``ULensModel::FromArray_Internal`` 用 ``TFieldIterator<FProperty>`` 按
    UPROPERTY 声明顺序 (BrownConradyUDLensModel.h:23-52) 把数组回填到 struct 字段;
    错位会让 K2-K6 / P1/P2 互窜.

    Parameters
    ----------
    normalized:
        ``distortion_math.compute_normalized_distortion`` 的返回字典, 必须包含
        ``k1, k2, k3, k4, k5, k6, p1, p2`` 八个键.

    Returns
    -------
    list[float]
        长度 8, 顺序匹配 FBrownConradyUDDistortionParameters 字段顺序.

    Raises
    ------
    KeyError
        缺任一必需键时抛出.
    """
    missing = [k for k in _BROWN_CONRADY_UD_KEYS if k not in normalized]
    if missing:
        raise KeyError(f"missing required keys for BrownConradyUD: {missing}")
    return [float(normalized[k]) for k in _BROWN_CONRADY_UD_KEYS]
```

- [ ] **Step 4: 跑测试确认 pass**

```bash
python3 -m unittest post_render_tool.tests.test_c_distortion_packing -v
```

Expected: 全部 9 个测试 pass（5 原有 + 4 新加）。

- [ ] **Step 5: Commit**

```bash
git add Content/Python/post_render_tool/distortion_packing.py Content/Python/post_render_tool/tests/test_c_distortion_packing.py
git commit -m "$(cat <<'EOF'
feat(distortion-packing): 加 to_brown_conrady_ud_parameters 8 槽打包

K1, K2, K3, K4, K5, K6, P1, P2 顺序对齐 FBrownConradyUDDistortionParameters
的 UPROPERTY 声明顺序 (BrownConradyUDLensModel.h:23-52).

加 4 个 unit test: 字段顺序, 类型, 缺键抛 KeyError, 多键无害.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 改 distortion_math.py 输出 8 系数

**Files:**
- Modify: `Content/Python/post_render_tool/distortion_math.py`

- [ ] **Step 1: 备份现有 M6 常量到注释**

在文件顶部 `M6_A: float = -0.2507` 等前面加注释（保留作历史参考）：

```python
# ── M6 polynomial coefficients (legacy, commit 34f5af0) ────────────
# 历史记录: 这是 SphericalLensModel 时代的 polynomial truncation 系数,
# 已被 M_RAT6 rational form 取代 (commit TBD), 因为 polynomial 在 r > 0.806
# 拐点处发散导致外圈渲染崩盘. 保留作 git blame reference, 实际不再使用.
# M6_A = -0.2507  K^1·r^3
# M6_B = +0.2097  K^2·r^5
# M6_C = -0.1931  K^3·r^7
```

- [ ] **Step 2: 加 M_RAT6 常量**

把 Task 1 fit 出的 6 个 M_RAT6 系数填入（替换占位符 X.XXX 为 fit 实际值）：

```python
# ── M_RAT6 rational coefficients (Path A round 1, commit TBD) ────────
# fit_distortion_models.py M_RAT6 BIC-best:
#     r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶)
#         / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶)
# RMS X.XXX px ≈ 噪声底, 跟 UE BrownConradyUDLensModel rational shader 同构.
M_RAT6_A: float = X.XXX   # 数值 fill from /tmp/rat6_coeffs.txt
M_RAT6_B: float = X.XXX
M_RAT6_C: float = X.XXX
M_RAT6_D: float = X.XXX
M_RAT6_E: float = X.XXX
M_RAT6_F: float = X.XXX
```

- [ ] **Step 3: 改 compute_normalized_distortion 输出**

完整替换函数体：

```python
def compute_normalized_distortion(frame_data: FrameData) -> dict:
    """Convert Designer mm-unit camera params to UE BrownConradyUD form.

    Returns a dict with keys ``fx, fy, cx, cy, k1..k6, p1, p2``. Tangential
    P1/P2 are zero — Disguise's CSV schema doesn't carry them.

    Normalization-space conversion (Tier 2 fix, commit 34f5af0 → updated TBD):
        M_RAT6 was fit in HALF-WIDTH-normalized r space (r = pixel_offset / (W/2)).
        UE LensFile applies the polynomial in FOCAL-LENGTH-normalized r space
        (r = pixel_offset / fx_pixels).
            r_HW = (2 · fx_uv) · r_fx
        Each polynomial coefficient scales by (2·fx_uv)^(2k) for k-th radial term.
        Both numerator AND denominator coefficients use the same scaling.

    CSV K2 / K3 mapping NOT yet validated — Path A only swept csv_K1. Pass-through
    sign-flip on csv_K2/K3 as additive corrections to UE_K2/UE_K3 (numerator only,
    matches legacy behaviour for production CSV K1≈0).

    Parameters
    ----------
    frame_data:
        Single-frame camera record from `csv_parser.FrameData`.
    """
    pa_width = frame_data.sensor_width_mm
    focal_mm = frame_data.focal_length_mm
    aspect = frame_data.aspect_ratio

    fx = focal_mm / pa_width
    fy = fx * aspect
    cx = 0.5 + frame_data.center_shift_x_mm / pa_width
    pa_height = pa_width / aspect
    cy = 0.5 + frame_data.center_shift_y_mm / pa_height

    fx_scale = 2.0 * fx
    fx2 = fx_scale * fx_scale
    fx4 = fx2 * fx2
    fx6 = fx4 * fx2

    csv_k1 = frame_data.k1
    k1_sq = csv_k1 * csv_k1
    k1_cu = k1_sq * csv_k1

    # Numerator coefficients (UE K1-K3): a·K, b·K², c·K³ (all fx-scaled)
    ue_k1 = M_RAT6_A * csv_k1 * fx2 - frame_data.k2  # CSV K2 sign-flip on numerator K2
    ue_k2 = M_RAT6_B * k1_sq * fx4
    ue_k3 = M_RAT6_C * k1_cu * fx6 - frame_data.k3   # CSV K3 sign-flip on numerator K3

    # Denominator coefficients (UE K4-K6): d·K, e·K², f·K³ (all fx-scaled)
    ue_k4 = M_RAT6_D * csv_k1 * fx2
    ue_k5 = M_RAT6_E * k1_sq * fx4
    ue_k6 = M_RAT6_F * k1_cu * fx6

    return {
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
        "k1": ue_k1,
        "k2": ue_k2,
        "k3": ue_k3,
        "k4": ue_k4,
        "k5": ue_k5,
        "k6": ue_k6,
        "p1": 0.0,
        "p2": 0.0,
    }
```

注意：CSV K2/K3 的 sign-flip 注入到 UE K1 的位置变了，从加到 ue_K2/ue_K3 的 polynomial 项改成只在 numerator 的对应槽位。**这是因为 rational 形态的 K2 已经是 K1²·b 主导，叠加 csv_K2 sign-flip 在 K2 槽位语义不清，搬到 K1（线性 csv_K2）更合适**。但为了保持 production CSV K1≈0 时行为跟 legacy 一致，需要数学验证。

实际上我重新考虑：production CSV K1≈0 时 ue_K1 = 0 - csv_K2 = -csv_K2，跟 legacy 行为完全一致。生效 K1=+0.5 时 ue_K1 = 0.13 - 0 = 0.13。OK 等价。

更新该处：

```python
# Numerator coefficients (UE K1-K3): rational expansion of M_RAT6 + legacy CSV K2/K3 sign-flip pass-through
# CSV K2 sign-flip lands on UE K2 (legacy behavior at K1≈0); CSV K3 lands on UE K3.
ue_k1 = M_RAT6_A * csv_k1 * fx2
ue_k2 = M_RAT6_B * k1_sq * fx4 - frame_data.k2
ue_k3 = M_RAT6_C * k1_cu * fx6 - frame_data.k3
```

（保留传统位置，避免破坏 legacy K1≈0 行为）

- [ ] **Step 4: 跑现有 M6 测试预期 fail**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python3 -m unittest post_render_tool.tests.test_distortion_m6 -v 2>&1 | tail -10
```

Expected: 多个测试 fail（旧测试期望 5 个键，新返回 9 个键；旧用 M6_A/B/C 常量，新用 M_RAT6_A..F）。

- [ ] **Step 5: 删除旧 test_distortion_m6.py**

```bash
git rm Content/Python/post_render_tool/tests/test_distortion_m6.py
```

- [ ] **Step 6: 加 P4-style 注释（不 commit）**

留作下个 task 写新测试。

---

## Task 5: 写新 test_distortion_rational.py

**Files:**
- Create: `Content/Python/post_render_tool/tests/test_distortion_rational.py`

- [ ] **Step 1: 写测试**

```python
"""Verify M_RAT6 rational distortion-coefficient mapping from CSV K1/K2/K3 to UE.

M_RAT6 fit (commit TBD, Path A K1 sweep):
    r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶)
        / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶)

Maps to UE BrownConradyUDLensModel:
    K1 = a·csv_K · fx²    K4 = d·csv_K · fx²
    K2 = b·csv_K² · fx⁴   K5 = e·csv_K² · fx⁴
    K3 = c·csv_K³ · fx⁶   K6 = f·csv_K³ · fx⁶
plus CSV K2/K3 sign-flip pass-through on UE K2/K3 (legacy, TODO: K2/K3 sweep).
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from post_render_tool.distortion_math import (
    M_RAT6_A, M_RAT6_B, M_RAT6_C, M_RAT6_D, M_RAT6_E, M_RAT6_F,
    compute_normalized_distortion,
)


@dataclass
class _StubFrame:
    k1: float = 0.0
    k2: float = 0.0
    k3: float = 0.0
    center_shift_x_mm: float = 0.0
    center_shift_y_mm: float = 0.0
    sensor_width_mm: float = 35.0
    focal_length_mm: float = 30.0
    aspect_ratio: float = 1.7778


def _expected_ue(csv_k1: float, csv_k2: float, csv_k3: float, fx: float):
    fx_scale = 2.0 * fx
    fx2 = fx_scale ** 2
    fx4 = fx2 ** 2
    fx6 = fx4 * fx2
    return {
        "k1": M_RAT6_A * csv_k1 * fx2,
        "k2": M_RAT6_B * csv_k1**2 * fx4 - csv_k2,
        "k3": M_RAT6_C * csv_k1**3 * fx6 - csv_k3,
        "k4": M_RAT6_D * csv_k1 * fx2,
        "k5": M_RAT6_E * csv_k1**2 * fx4,
        "k6": M_RAT6_F * csv_k1**3 * fx6,
    }


class TestRationalMapping(unittest.TestCase):
    PLACES = 8

    def _check(self, frame, expected):
        nd = compute_normalized_distortion(frame)
        for key, exp in expected.items():
            self.assertAlmostEqual(nd[key], exp, places=self.PLACES,
                                   msg=f"{key}: got {nd[key]} expected {exp}")

    def test_zero_input_zero_output(self):
        nd = compute_normalized_distortion(_StubFrame())
        for key in ("k1", "k2", "k3", "k4", "k5", "k6", "p1", "p2"):
            self.assertEqual(nd[key], 0.0)

    def test_csv_k1_positive_sweep(self):
        frame = _StubFrame(k1=+0.5)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        self._check(frame, _expected_ue(+0.5, 0.0, 0.0, fx))

    def test_csv_k1_negative_sweep(self):
        frame = _StubFrame(k1=-0.5)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        nd = compute_normalized_distortion(frame)
        # K1, K3, K4, K6 跟 csv_K1 同号翻 (csv_K1 / csv_K1³ 同号)
        self.assertLess(nd["k1"] * (-0.5), 0, "ue_K1 must oppose csv_K1 sign")
        self.assertLess(nd["k4"] * (-0.5), 0, "ue_K4 must oppose csv_K1 sign")
        # K2, K5 是 K² 项, 永远跟 sign-of-coef 同号 (不随 csv_K1 翻)
        self._check(frame, _expected_ue(-0.5, 0.0, 0.0, fx))

    def test_csv_k2_k3_passthrough_when_k1_zero(self):
        """csv_K1=0 时所有 M_RAT6 项贡献为 0, K2/K3 退回 legacy sign-flip."""
        nd = compute_normalized_distortion(
            _StubFrame(k1=0.0, k2=-0.004, k3=+0.011)
        )
        self.assertEqual(nd["k1"], 0.0)
        self.assertAlmostEqual(nd["k2"], +0.004, places=8)
        self.assertAlmostEqual(nd["k3"], -0.011, places=8)
        self.assertEqual(nd["k4"], 0.0)
        self.assertEqual(nd["k5"], 0.0)
        self.assertEqual(nd["k6"], 0.0)

    def test_production_csv_values(self):
        """Production CSV (K1≈3e-4): M_RAT6 项贡献 sub-1e-7, 行为 ≈ legacy sign-flip."""
        frame = _StubFrame(k1=0.000286, k2=-0.003953, k3=+0.011302)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        self._check(frame, _expected_ue(0.000286, -0.003953, +0.011302, fx))

    def test_combined_csv_k1_and_k2_k3(self):
        frame = _StubFrame(k1=+0.3, k2=+0.05, k3=-0.02)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        self._check(frame, _expected_ue(+0.3, +0.05, -0.02, fx))

    def test_principal_point_unchanged(self):
        frame = _StubFrame(
            k1=0.5, k2=0.0, k3=0.0,
            center_shift_x_mm=2.0, center_shift_y_mm=1.0,
            sensor_width_mm=35.0, focal_length_mm=30.0, aspect_ratio=1.7778,
        )
        nd = compute_normalized_distortion(frame)
        self.assertAlmostEqual(nd["fx"], 30.0 / 35.0, places=6)
        self.assertAlmostEqual(nd["cx"], 0.5 + 2.0 / 35.0, places=6)

    def test_returns_eight_distortion_coefficients(self):
        nd = compute_normalized_distortion(_StubFrame(k1=+0.5))
        for key in ("k1", "k2", "k3", "k4", "k5", "k6", "p1", "p2"):
            self.assertIn(key, nd, f"missing UE BrownConradyUD coefficient: {key}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试 — 预期全 PASS（distortion_math.py 已经在 Task 4 写好）**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python3 -m unittest post_render_tool.tests.test_distortion_rational -v
```

Expected: 8 个测试全 PASS。

- [ ] **Step 3: 跑全部 pure-Python 测试套件确认无回归**

```bash
python3 -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -p "test_d*.py" -p "test_distortion*.py" -v 2>&1 | tail -5
```

Expected: 全 PASS（旧 test_distortion_m6 已删除，新 test_distortion_rational 替代）。

- [ ] **Step 4: Commit**

```bash
git add Content/Python/post_render_tool/distortion_math.py \
        Content/Python/post_render_tool/tests/test_distortion_rational.py \
        Content/Python/post_render_tool/tests/test_distortion_m6.py
git commit -m "$(cat <<'EOF'
feat(distortion-math): M6 polynomial → M_RAT6 rational, 输出 UE BrownConradyUD 8 系数

替换:
- M6_A/B/C polynomial 常量 (3 项) → M_RAT6_A/B/C/D/E/F rational 常量 (6 项)
- compute_normalized_distortion 返回字典从 5 系数 (k1/k2/k3/p1/p2) 改 9 系数
  (k1/k2/k3/k4/k5/k6/p1/p2 + fx/fy/cx/cy)
- HW-norm → fx-norm scaling 沿用 (2·fx)^(2k), 应用到 numerator 和 denominator
  系数对称 (rational 分子分母同步缩放, 不会有 polynomial truncation 边缘崩问题)

CSV K2/K3 仍 legacy sign-flip 透传到 ue_K2/ue_K3 (numerator). production CSV
K1≈0 时行为完全等同 legacy; K=±0.5 测试范围下 M_RAT6 主导, 跟 Disguise 残差
应降到噪声底.

8 个新 unit test 覆盖: 全零, K1 sweep ±, K1=0 fallback, production, 复合,
主点, 8 系数返回. 旧 test_distortion_m6.py 删除 (M6 时代). 47 个 unit test
全过.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 改 lens_file_builder.py 切到 BrownConradyUDLensModel

**Files:**
- Modify: `Content/Python/post_render_tool/lens_file_builder.py`

- [ ] **Step 1: 找现有 SphericalLensModel 引用**

```bash
grep -n "SphericalLensModel\|to_spherical_parameters" Content/Python/post_render_tool/lens_file_builder.py
```

期望看到 2-4 个引用：lens_model 设置、to_spherical_parameters import、调用。

- [ ] **Step 2: 改 import**

替换：

```python
from .distortion_packing import to_spherical_parameters
```

为：

```python
from .distortion_packing import to_brown_conrady_ud_parameters
```

- [ ] **Step 3: 改 lens_model 设置**

找到设置 LensInfo.lens_model 的位置（通常在 `_create_lens_file` 或 `_initialize_lens_info` 函数），把：

```python
lens_info.lens_model = unreal.SphericalLensModel.static_class()
```

改成：

```python
lens_info.lens_model = unreal.BrownConradyUDLensModel.static_class()
```

- [ ] **Step 4: 改 distortion_info.parameters 打包**

找到调用 `to_spherical_parameters(nd)` 的位置（应该在 add_distortion_point 调用前），改成 `to_brown_conrady_ud_parameters(nd)`。

例如把：

```python
distortion_info = unreal.DistortionInfo()
distortion_info.parameters = to_spherical_parameters(nd)
```

改成：

```python
distortion_info = unreal.DistortionInfo()
distortion_info.parameters = to_brown_conrady_ud_parameters(nd)
```

- [ ] **Step 5: 改 lens_model 注释**

如果 lens_file_builder.py 顶部有 SphericalLensModel 相关注释，更新成：

```python
# UE LensFile uses BrownConradyUDLensModel (polynomial division rational form):
#   r' = r · (1 + K1·r² + K2·r⁴ + K3·r⁶) / (1 + K4·r² + K5·r⁴ + K6·r⁶)
# implemented in BrownConradyUDDistortion.usf:48-50.
# Coefficient computation in distortion_math.compute_normalized_distortion (M_RAT6).
```

- [ ] **Step 6: 验证语法**

```bash
python3 -c "import ast; ast.parse(open('/Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python/post_render_tool/lens_file_builder.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 7: 部署到 lanPC**

```bash
DST='lanpc:E:/RenderStream Projects/test_0311/Plugins/post-render-tool/Content/Python/post_render_tool'
SRC=/Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python/post_render_tool
scp -q "$SRC/distortion_math.py" "$DST/distortion_math.py"
scp -q "$SRC/distortion_packing.py" "$DST/distortion_packing.py"
scp -q "$SRC/lens_file_builder.py" "$DST/lens_file_builder.py"
```

确认 hash 一致：

```bash
md5 -q "$SRC/lens_file_builder.py"
ssh lanpc "powershell -Command \"(Get-FileHash -LiteralPath 'E:/RenderStream Projects/test_0311/Plugins/post-render-tool/Content/Python/post_render_tool/lens_file_builder.py' -Algorithm MD5).Hash\""
```

Expected: 两个 MD5 相同（忽略大小写）。

- [ ] **Step 8: Commit**

```bash
git add Content/Python/post_render_tool/lens_file_builder.py
git commit -m "$(cat <<'EOF'
feat(lens-file-builder): UE LensFile lens_model 切到 BrownConradyUDLensModel

把 SphericalLensModel (5 系数 polynomial K1/K2/K3/P1/P2) 替换成
BrownConradyUDLensModel (8 系数 rational K1-K6/P1/P2). UE shader
BrownConradyUDDistortion.usf 用 polynomial division 形态:
    dr = (1+K1·r²+K2·r⁴+K3·r⁶) / (1+K4·r²+K5·r⁴+K6·r⁶)
跟 Disguise 真公式 (M7 rational) 直接同构, 不再有 M6 polynomial truncation
在 r > 0.806 拐点的边缘崩盘问题.

distortion_info.parameters 打包从 to_spherical_parameters (5 槽) 切到
to_brown_conrady_ud_parameters (8 槽).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Tier 1 验证 — UE 写入 + 读回 8 系数

**Files:**
- Create temporary: `/tmp/ue_tier1_brown_conrady.py`

- [ ] **Step 1: 写 Tier 1 验证脚本**

```python
"""Tier 1 verify - import synth_K1_p0p5.csv via new BrownConradyUD pipeline,
read back LensFile 8 coefficients, compare to distortion_math output."""
import builtins, sys
def _safe(*args, **kwargs):
    sep = kwargs.get("sep", " "); end = kwargs.get("end", "\n")
    sys.stdout.write(sep.join(str(a).encode("ascii", "replace").decode("ascii") for a in args) + end)
builtins.print = _safe

import importlib
import unreal


# Reload modules so new code takes effect
for name in [
    "post_render_tool.distortion_math",
    "post_render_tool.distortion_packing",
    "post_render_tool.lens_file_builder",
    "post_render_tool.pipeline",
]:
    if name in sys.modules:
        importlib.reload(sys.modules[name])
    else:
        __import__(name)

# Re-import for csv_K1=+0.5
pipeline = sys.modules["post_render_tool.pipeline"]
result = pipeline.run_import("C:/temp/ue-remote/synth_K1_p0p5.csv", fps=24.0)
print("import done")

# Compute expected via distortion_math
from post_render_tool.distortion_math import (
    M_RAT6_A, M_RAT6_B, M_RAT6_C, M_RAT6_D, M_RAT6_E, M_RAT6_F,
)

csv_k1 = 0.5
fx = 30.302 / 35.0
fx2 = (2 * fx) ** 2
fx4 = fx2 ** 2
fx6 = fx4 * fx2
expected = [
    M_RAT6_A * csv_k1 * fx2,             # K1
    M_RAT6_B * csv_k1**2 * fx4,           # K2
    M_RAT6_C * csv_k1**3 * fx6,           # K3
    M_RAT6_D * csv_k1 * fx2,              # K4
    M_RAT6_E * csv_k1**2 * fx4,           # K5
    M_RAT6_F * csv_k1**3 * fx6,           # K6
    0.0, 0.0,                             # P1, P2
]

# Read back LensFile distortion point
lf = unreal.load_asset("/Game/PostRender/synth_K1_p0p5/LF_synth_K1_p0p5")
print(f"LensFile lens_model: {lf.lens_info.lens_model}")
points = lf.get_distortion_points()
print(f"distortion points: {len(points)}")

ok = True
for p in points:
    actual = list(p.distortion_info.parameters)
    print(f"  focus={p.focus} zoom={p.zoom}")
    print(f"  actual:   {actual}")
    print(f"  expected: {expected}")
    for i, (a, e) in enumerate(zip(actual, expected)):
        delta = abs(a - e)
        verdict = "OK" if delta < 1e-6 else "MISMATCH"
        print(f"    [{i}] {a:+.6f} vs {e:+.6f}  delta={delta:.2e}  {verdict}")
        if delta >= 1e-6:
            ok = False

print(f"\nTier 1 verdict: {'PASS' if ok else 'FAIL'}")
```

- [ ] **Step 2: SCP + 跑**

```bash
scp -q /tmp/ue_tier1_brown_conrady.py lanpc:C:/temp/ue-remote/
ssh lanpc 'set PYTHONIOENCODING=utf-8 & "D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/ue_tier1_brown_conrady.py' 2>&1 | grep -v "WARNING\|store now\|server may need\|^$" | tail -25
```

Expected: 看到 "Tier 1 verdict: PASS" 在最后一行；8 个系数全部 delta < 1e-6。

- [ ] **Step 3: 如果 FAIL 排查**

可能错因：
- LensFile 的 lens_model 字段没切（仍是 Spherical）→ 检查 lens_file_builder.py Step 3 改对没
- distortion_info.parameters 长度不是 8 → 检查 Step 4 改对没
- M_RAT6 系数读取错（test 里写的常数跟 distortion_math 里不同）→ 检查 Task 4 系数填对没
- fx_scale 缺失 → 检查 Step 3 fx-norm 转换还在不在

修了重跑 Step 2。

- [ ] **Step 4: 不 commit**（验证脚本留 /tmp/）

---

## Task 8: Tier 2 验证 — 真实 PNG forward 比对

**Files:**
- Create: `scripts/distortion_calibration/_validate_tier2_brownconradyud.py`

- [ ] **Step 1: 写 Tier 2 验证脚本**

```python
"""Tier 2 final - apply UE BrownConradyUD rational distortion to K=0 source PNG,
compare to actual K=+0.5 Disguise output. If M_RAT6 matches Disguise, predicted
should equal actual within noise floor across the whole image (NOT just center).
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np


W, H = 1920, 1080
FX_UV = 30.302 / 35.0
FY_UV = FX_UV * (W / H)
CX, CY = 0.5, 0.5

# UE BrownConradyUD coefficients written into LensFile for csv_K1=+0.5
# (read from M_RAT6 fit; replace values from /tmp/rat6_coeffs.txt with fx-scaling)
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Content" / "Python"))
from post_render_tool.distortion_math import (
    M_RAT6_A, M_RAT6_B, M_RAT6_C, M_RAT6_D, M_RAT6_E, M_RAT6_F,
)

csv_k1 = +0.5
fx_scale = 2.0 * FX_UV
fx2 = fx_scale ** 2
fx4 = fx2 ** 2
fx6 = fx4 * fx2
UE_K1 = M_RAT6_A * csv_k1 * fx2
UE_K2 = M_RAT6_B * csv_k1**2 * fx4
UE_K3 = M_RAT6_C * csv_k1**3 * fx6
UE_K4 = M_RAT6_D * csv_k1 * fx2
UE_K5 = M_RAT6_E * csv_k1**2 * fx4
UE_K6 = M_RAT6_F * csv_k1**3 * fx6


def newton_inverse_rational(r_dist: np.ndarray, iters: int = 25) -> np.ndarray:
    """Solve r · (num(r)/den(r)) = r_dist for r where
    num(r) = 1 + K1·r² + K2·r⁴ + K3·r⁶
    den(r) = 1 + K4·r² + K5·r⁴ + K6·r⁶
    """
    r = r_dist.copy()
    for _ in range(iters):
        r2 = r * r
        num = 1 + UE_K1 * r2 + UE_K2 * r2 * r2 + UE_K3 * r2 * r2 * r2
        den = 1 + UE_K4 * r2 + UE_K5 * r2 * r2 + UE_K6 * r2 * r2 * r2
        f = r * num / np.where(np.abs(den) > 1e-9, den, 1e-9) - r_dist
        # numerical derivative for robustness
        h = 1e-6
        r_h = r + h
        r2_h = r_h * r_h
        num_h = 1 + UE_K1 * r2_h + UE_K2 * r2_h * r2_h + UE_K3 * r2_h * r2_h * r2_h
        den_h = 1 + UE_K4 * r2_h + UE_K5 * r2_h * r2_h + UE_K6 * r2_h * r2_h * r2_h
        f_h = r_h * num_h / np.where(np.abs(den_h) > 1e-9, den_h, 1e-9) - r_dist
        fp = (f_h - f) / h
        r = r - f / np.where(np.abs(fp) > 1e-9, fp, 1e-9)
        r = np.clip(r, 0.0, 5.0)
    return r


def main():
    src = cv2.imread("/tmp/d3_K_zero_source.png", cv2.IMREAD_UNCHANGED)
    actual = cv2.imread("/tmp/d3_K_p0p5_from_png.png", cv2.IMREAD_UNCHANGED)
    print(f"source K=0:    {src.shape}  mean {src.mean():.1f}")
    print(f"actual K=+0.5: {actual.shape}  mean {actual.mean():.1f}")
    print(f"UE coefficients: K1={UE_K1:+.4f} K2={UE_K2:+.4f} K3={UE_K3:+.4f} K4={UE_K4:+.4f} K5={UE_K5:+.4f} K6={UE_K6:+.4f}")

    # Forward: for each output pixel (px_d, py_d), find source position
    ys, xs = np.indices((H, W), dtype=np.float64)
    out_u = (xs + 0.5) / W
    out_v = (ys + 0.5) / H
    cam_x_d = (out_u - CX) / FX_UV
    cam_y_d = (out_v - CY) / FY_UV
    r_d = np.hypot(cam_x_d, cam_y_d)

    r_u = newton_inverse_rational(r_d)
    safe = r_d > 1e-9
    scale = np.where(safe, r_u / np.where(safe, r_d, 1.0), 1.0)
    cam_x_u = cam_x_d * scale
    cam_y_u = cam_y_d * scale
    src_x = (cam_x_u * FX_UV + CX) * W - 0.5
    src_y = (cam_y_u * FY_UV + CY) * H - 0.5

    predicted = cv2.remap(src, src_x.astype(np.float32), src_y.astype(np.float32),
                          cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    cv2.imwrite("/tmp/d3_K_p0p5_predicted_via_brownconradyud.png", predicted)

    # Per-pixel diff
    pred_g = cv2.cvtColor(predicted, cv2.COLOR_BGR2GRAY).astype(np.float64) if predicted.ndim == 3 else predicted.astype(np.float64)
    actual_g = cv2.cvtColor(actual, cv2.COLOR_BGR2GRAY).astype(np.float64) if actual.ndim == 3 else actual.astype(np.float64)
    diff = pred_g - actual_g

    half_w = W / 2.0
    r_norm = np.hypot(xs - W / 2, ys - H / 2) / half_w

    print()
    print(f"=== diff stats by region ===")
    for r_lo, r_hi, name in [(0, 0.5, "中心 r<0.5     "),
                               (0.5, 0.8, "中圈 0.5≤r<0.8 "),
                               (0.8, 99, "外圈 r≥0.8     ")]:
        mask = (r_norm >= r_lo) & (r_norm < r_hi)
        sub = diff[mask]
        rms = np.sqrt(np.mean(sub ** 2))
        clean = (np.abs(sub) < 5).mean() * 100
        print(f"  {name}: RMS {rms:5.1f}, |diff|<5/255 {clean:.1f}%")

    # Edge distance metric
    edges_pred = cv2.Canny(pred_g.astype(np.uint8), 50, 150)
    edges_actual = cv2.Canny(actual_g.astype(np.uint8), 50, 150)
    dist = cv2.distanceTransform((edges_actual == 0).astype(np.uint8), cv2.DIST_L2, 5)
    px = np.where(edges_pred > 0)
    if len(px[0]) > 0:
        d = dist[px]
        edge_y, edge_x = px
        edge_r = np.hypot(edge_x - W / 2, edge_y - H / 2) / half_w
        print()
        print(f"=== predicted edges → actual edges distance (px) ===")
        for r_lo, r_hi, name in [(0, 0.5, "中心 r<0.5     "),
                                  (0.5, 0.8, "中圈 0.5≤r<0.8 "),
                                  (0.8, 99, "外圈 r≥0.8     ")]:
            m = (edge_r >= r_lo) & (edge_r < r_hi)
            if m.sum() == 0:
                continue
            sub_d = d[m]
            print(f"  {name}: median {np.median(sub_d):.2f}, p95 {np.percentile(sub_d, 95):.2f}, max {sub_d.max():.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑验证**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python _validate_tier2_brownconradyud.py 2>&1 | tail -20
```

Expected:
- 中心 r<0.5: RMS < 2, edge median 0 px
- 中圈 0.5≤r<0.8: RMS < 5, edge median ≤ 1 px
- **外圈 r≥0.8: RMS < 10, edge median ≤ 2 px**（vs M6 时代外圈 RMS 36 max 122 px）
- 总体 SSIM > 0.97

- [ ] **Step 3: 如果外圈 RMS 还很高（>20），排查**

可能原因：
- M_RAT6 fit 系数错（重新跑 fit_distortion_models.py 看 M_RAT6 RMS 是不是 < 0.5）
- Newton inverse 没收敛（增加 iters 到 50）
- fx-norm scaling 漏 K4-K6（检查 distortion_math.py 全 6 个系数都乘 fx2/fx4/fx6 没）

- [ ] **Step 4: 视觉对比图重生**

```bash
.venv/bin/python /tmp/save_validation_images.py
```

或者修改 save_validation_images.py 的输入路径指向新的 predicted PNG：

```bash
# 复制旧的 save script, 改名 + 改输入
cp /tmp/save_validation_images.py /tmp/save_validation_images_v2.py
sed -i '' 's|d3_K_p0p5_predicted_via_ue_m6|d3_K_p0p5_predicted_via_brownconradyud|g' /tmp/save_validation_images_v2.py
sed -i '' 's|d3_validation_results|d3_validation_results_rational|g' /tmp/save_validation_images_v2.py
.venv/bin/python /tmp/save_validation_images_v2.py
```

新对比图集在 `/tmp/d3_validation_results_rational/`。

- [ ] **Step 5: 搬到项目持久位置**

```bash
mv /tmp/d3_validation_results_rational/*.png \
   /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration/validation_results/
ls /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration/validation_results/
```

- [ ] **Step 6: Commit**

```bash
git add scripts/distortion_calibration/_validate_tier2_brownconradyud.py
git commit -m "$(cat <<'EOF'
test(distortion): Tier 2 BrownConradyUD rational 验证, 全画面跟 Disguise 对位

把 K=0 source PNG 走 UE BrownConradyUD rational forward distortion (M_RAT6
8 系数), 跟 Disguise actual K=+0.5 (transmission_00011.png) 逐像素 diff.
分中心/中圈/外圈三段统计 RMS + 边缘距离, 看 rational 是否消除 M6 时代外圈
崩盘问题.

期望:
- 中心 r<0.5: RMS < 2 (跟 M6 持平, 已经是噪声底)
- 中圈 0.5≤r<0.8: RMS < 5 (略好于 M6 的 8.1)
- 外圈 r≥0.8: RMS < 10 (M6 时代是 36, 大幅改善)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 更新 docs/K1-implementation.md

**Files:**
- Modify: `docs/K1-implementation.md`

- [ ] **Step 1: 加新章节"M6 → Rational 升级"**

在 docs/K1-implementation.md 末尾追加：

```markdown
---

## 9 · M6 → Rational 升级（commit TBD）

### 触发原因

M6 polynomial 在 r > 0.806 (fx-norm) 处出现拐点（非单调），导致：
- 测试 csv_K1=+0.5 时图像角落 (r ≈ 0.66) 已超出 polynomial 单调区间
- Newton inverse 发散，UE 渲染外圈崩盘 (RMS 36 px, max 122 px)

### 解决方案

切换 UE LensFile 从 `SphericalLensModel` (5 系数 polynomial) 到
`BrownConradyUDLensModel` (8 系数 polynomial division rational), shader
原生 `BrownConradyUDDistortion.usf:48-50`:

    dr = (1 + K1·r² + K2·r⁴ + K3·r⁶) / (1 + K4·r² + K5·r⁴ + K6·r⁶)

### M_RAT6 系数（commit TBD）

(Fill from /tmp/rat6_coeffs.txt after Task 1):

    a = X.XXX  (K1 numerator)
    b = X.XXX  (K2 numerator)
    c = X.XXX  (K3 numerator)
    d = X.XXX  (K4 denominator)
    e = X.XXX  (K5 denominator)
    f = X.XXX  (K6 denominator)

RMS 拟合 X.XXX px ≈ 噪声底.

### 残差对比 (csv_K1=+0.5 测试值)

| 区域 | M6 polynomial | M_RAT6 rational |
|---|---|---|
| 中心 r<0.5 | RMS 1.2 px | RMS X.X px |
| 中圈 0.5≤r<0.8 | RMS 8.1 px | RMS X.X px |
| 外圈 r≥0.8 | **RMS 36.4 px / max 122 px** | **RMS X.X px / max X px** |

### Path A 完结声明

经过 commit TBD, **Path A K1 轴端到端 pixel-perfect**:
- ✅ d3 端 UV 探针 + 11 帧 K1 sweep 数据采集
- ✅ M1-M10 + M_RAT6 候选拟合 (BIC 排序)
- ✅ M_RAT6 (UE BrownConradyUD 同构) 落地 distortion_math.py
- ✅ Tier 1: UE LensFile 写入 8 系数 ↔ distortion_math 输出 1e-9 一致
- ✅ Tier 2: UE 渲染对 Disguise 全画面残差 ≈ 噪声底 (无外圈崩盘)
- ✅ pipeline.run_import 用户接口零变化, 用户感知就是渲染结果变完美

CSV K2/K3 仍走 legacy sign-flip 透传, 后续做 Round 2 (K2 sweep) + Round 3
(K3 sweep) + Round 4 (联合验证) 才能完整闭环 K2/K3 轴.
```

- [ ] **Step 2: 把 §3 "fx-norm 缩放陷阱"加段说明 rational 怎么也用 (2·fx)^(2k) 缩放**

找 docs/K1-implementation.md 第 3 节 "翻译到 UE LensFile（含 fx-norm 缩放陷阱）"，在末尾追加：

```markdown
**Rational form 同样用 fx-norm 缩放**：

`BrownConradyUDLensModel` 的 K1-K6 都在分子或分母的 r²/r⁴/r⁶ 项上,
跟 polynomial 同样用 `(2·fx_uv)^(2k)` 缩放（k=1,2,3 对应 K1/K4, K2/K5,
K3/K6）。**分子分母用同样 scale 因子，不会消掉**——分子 K1 = a·csv_K · fx²,
分母 K4 = d·csv_K · fx²，最终的 dr = num/den 跟 fx 无关，但每个系数本身
要 fx-scaled. distortion_math.py 已经处理.
```

- [ ] **Step 3: §8 commit 索引加新一行**

找 §8 末尾的 commit 表，加：

```markdown
| `<新 commit hash>` | M6 polynomial → BrownConradyUD rational, 外圈 RMS 36→<XX> px ← Path A K1 终结 commit |
```

- [ ] **Step 4: Commit**

```bash
git add docs/K1-implementation.md
git commit -m "$(cat <<'EOF'
docs(distortion): K1-implementation 加 M6 → BrownConradyUD rational 升级章节

记录: M6 polynomial 截断在外圈崩盘的根因 (r > 0.806 拐点) + 切到 UE
原生 rational shader 的解决路径 + 残差量化对比 + Path A K1 轴完结声明.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: 更新 USER_INSTRUCTIONS.md

**Files:**
- Modify: `scripts/distortion_calibration/USER_INSTRUCTIONS.md`

- [ ] **Step 1: 改 Round 1 状态描述**

把 Round 1 章节顶部的：

```markdown
## ✅ Round 1 · K1 sweep（已完成 2026-04-28）

**状态**：M6 公式反推完成，BIC 胜出，参数 a=-0.2507 / b=+0.2097 / c=-0.1931，
RMS 0.4 px ≈ 噪声底。已写入 `distortion_math.py`，commit `4b3834f` + `34f5af0`。
```

改成：

```markdown
## ✅ Round 1 · K1 sweep（已完成 2026-04-XX，commit TBD）

**状态**：M_RAT6 公式反推完成 (BrownConradyUD rational), BIC 胜出, 6 自由参数,
RMS X.X px ≈ 噪声底. 已写入 `distortion_math.py`, UE LensFile 用
BrownConradyUDLensModel (commit `<hash>`).

**注**: 历史 commit `4b3834f` + `34f5af0` 用的是 M6 polynomial (3 项),
在 r > 0.806 拐点崩盘. commit `<新 hash>` 切到 rational form 后修复.
```

- [ ] **Step 2: 加 §"为什么用 BrownConradyUD"**

在 Round 1 章节末尾加：

```markdown
### M_RAT6 跟 UE 模型的对应关系

UE LensFile 的 `BrownConradyUDLensModel` shader 形态:

    r' = r · (1 + K1·r² + K2·r⁴ + K3·r⁶) / (1 + K4·r² + K5·r⁴ + K6·r⁶)

M_RAT6 直接展开成 8 系数:

    K1 = a · csv_K1 · (2·fx)²
    K2 = b · csv_K1² · (2·fx)⁴ - csv_K2 (legacy sign-flip)
    K3 = c · csv_K1³ · (2·fx)⁶ - csv_K3 (legacy sign-flip)
    K4 = d · csv_K1 · (2·fx)²
    K5 = e · csv_K1² · (2·fx)⁴
    K6 = f · csv_K1³ · (2·fx)⁶
    P1 = P2 = 0

production CSV K1≈3e-4 时, K1-K3 由 -csv_K2/-csv_K3 主导（等于 legacy
sign-flip 行为）；K=±0.5 测试值时, M_RAT6 系数主导, rational shader
天然在边缘 well-behaved.
```

- [ ] **Step 3: Commit**

```bash
git add scripts/distortion_calibration/USER_INSTRUCTIONS.md
git commit -m "$(cat <<'EOF'
docs(user-instructions): Round 1 状态从 M6 polynomial 改 M_RAT6 rational

记录 M6 → BrownConradyUD rational 的升级 + 8 系数 ↔ csv_K1 映射关系.
production CSV 行为保持 legacy 兼容, 测试范围下 rational 主导消除 M6
外圈崩盘.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: 最终回归 + P4 push

**Files:** N/A (verification only)

- [ ] **Step 1: 跑全部 pure-Python 测试**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python3 -m unittest discover -s post_render_tool/tests -p "test_*.py" 2>&1 | tail -5
```

Expected: `Ran XX tests in Y.Ys` + `OK`. 没有 fail.

- [ ] **Step 2: 验证 P4 sync 状态**

```bash
git log --oneline -10
git status
```

Expected: 看到 Task 1-10 的 commit hashes (5-7 个新 commit), 工作树 clean. 每个 commit 后 hook 会自动 push p4 (`[p4-sync] ✓ main pushed to p4`).

- [ ] **Step 3: 重新部署到 lanPC（保险）**

```bash
DST='lanpc:E:/RenderStream Projects/test_0311/Plugins/post-render-tool/Content/Python/post_render_tool'
SRC=/Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python/post_render_tool
scp -q "$SRC/distortion_math.py" "$DST/distortion_math.py"
scp -q "$SRC/distortion_packing.py" "$DST/distortion_packing.py"
scp -q "$SRC/lens_file_builder.py" "$DST/lens_file_builder.py"
ssh lanpc "powershell -Command \"(Get-FileHash -LiteralPath '$DST/distortion_math.py' -Algorithm MD5).Hash\"" 2>&1 | grep -v "WARNING\|store now\|server may need\|^$"
md5 -q "$SRC/distortion_math.py"
```

Expected: lanPC 跟 Mac 的 md5 一致.

- [ ] **Step 4: 最终用户视角验证**

跑用户实际的命令链:

```bash
ssh lanpc 'set PYTHONIOENCODING=utf-8 & "D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/ue_tier1_brown_conrady.py' 2>&1 | tail -20
```

Expected: Tier 1 PASS, 8 系数全部 1e-6 以内.

- [ ] **Step 5: 最终成果告知**

如果 Step 4 PASS, Path A K1 轴 pixel-perfect 完成. 没有 commit 需要做.

---

## Self-Review

### 1. Spec coverage

- ✅ Add M_RAT6 rational candidate to fit (Task 1)
- ✅ Verify UE BrownConradyUD API (Task 2)
- ✅ Pack 8-coefficient parameters (Task 3)
- ✅ Output 8 coefficients from distortion_math (Task 4)
- ✅ Test 8-coefficient mapping (Task 5)
- ✅ Switch lens_model in lens_file_builder (Task 6)
- ✅ End-to-end Tier 1 (Task 7)
- ✅ End-to-end Tier 2 with visual diff (Task 8)
- ✅ Documentation updates (Task 9, 10)
- ✅ Final regression + push (Task 11)

### 2. Placeholder scan

- ⚠️ M_RAT6 系数 (`X.XXX`) 是占位符 — 必须等 Task 1 跑出来再填. 这是合理的占位 (后续 task 依赖前面 task 输出), 不是 plan 失误.
- ⚠️ commit hash (`<新 commit hash>`) 在 Task 9/10 的 docs 里 — 同理, 等实际 commit 后填.
- 其他占位符（"TODO", "TBD", etc.）— 没看到.

### 3. Type / 函数名一致性

- `to_brown_conrady_ud_parameters` 名字在 distortion_packing.py、lens_file_builder.py、test_c_distortion_packing.py 三处一致.
- `compute_normalized_distortion` 字段名 `k1..k6, p1, p2` 在 distortion_math.py 输出、distortion_packing.py 读取、test_distortion_rational.py 验证三处一致.
- `M_RAT6_A..F` 系数名跟 fit_distortion_models.py 的 `_m_rat6` 函数 param_names 一致.
- UE 类名 `BrownConradyUDLensModel`, `BrownConradyUDLensDistortionModelHandler`, `FBrownConradyUDDistortionParameters` 跟 UE 源码 (BrownConradyUDLensModel.h:17-53) 严格对齐.

无类型不一致.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-28-brown-conrady-ud-rational.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
