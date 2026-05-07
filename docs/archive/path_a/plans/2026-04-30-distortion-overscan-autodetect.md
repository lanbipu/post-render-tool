# Distortion Over-scan Auto-detect & Compensate Plan (简化版)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **重要**: 这个 plan **修改** 上一 session 已完成的 plan `2026-04-30-distortion-overscan-pipeline.md` 的部分实现, 不是从零开始。先读上一 plan 的实施成果, 再按本 plan 调整。

**Goal:** 用实测数据替换上一 plan 关于 Disguise over-scan 行为的假设。实测发现 Disguise over-scan 1.5× 输出 EXR 仍是相机 nominal 分辨率 (3840×2160), R/G 通道被**仿射拉伸到 [0.1667, 0.8333]**。不需要 5760×3240 大探针图, 改用 K=0 anchor 自动检测 + R/G 反仿射补偿。

**Architecture 修订:**
- 上一 plan 假设 (作废): Disguise over-scan 1.5× 输出 5760×3240 全尺寸 EXR, 探针图也要 5760×3240, 用 camera-normalized 坐标 (cx=probe_W/2, half_w=camera_W/2)
- 实测确认 (新基准):
  - 输出 EXR 仍是 3840×2160 (nominal 4K), 不是 5760×3240
  - K=0 anchor R 范围 [0.1667, 0.8330], G 范围 [0.1667, 0.8330], 完美仿射拉伸
  - K1=+0.5 帧 R 范围 [0.1119, 0.8877], 无黑边 (over-scan 给 K1+ 留了合法缓冲)
  - over-scan 是**纯线性缩放 + 偏移**, 数学上完全可逆补偿
- 简化方案:
  - **不需要** 5760×3240 大探针图 (commit 6063e74 后那张可删可留, 不影响)
  - **保留** 上一 plan 的 4-tuple metadata API (`_exr.load_probe_meta` 返回 (probe_W, probe_H, camera_W, camera_H)), 简化场景下 camera_W == probe_W
  - **新增** over-scan 自动检测 (从 K=0 anchor R/G 范围反推 S 和 margin)
  - **新增** R/G 反仿射补偿 (`R_corrected = (R - margin) / (1 - 2*margin)`), 在 compute_displacements 内计算 src_*_norm 之前应用

**Tech Stack:**
- 已就位: Mac venv `scripts/distortion_calibration/.venv/` (numpy 2.4 / scipy 1.17 / cv2 4.13)
- 已就位 探针: `uv_probe_3840x2160.exr` + truth npz (commit `98eb839` 加的 4K 探针)
- 已就位 上一 plan 实施: 上一 session 已跑完 `2026-04-30-distortion-overscan-pipeline.md` Tasks 1-5 (代码改造, 探针生成 等)
- 实测基准 (2026-04-30): 用户用 5760×3240 相机 + over-scan 1.5× 渲了两张测试帧, EXR 实际 3840×2160, R/G 范围确认仿射规律

**前置条件:**
- ✅ 上一 plan 实施已完成 (新 session 跑过, 假设 commit 6a21efd 之后有一连串 over-scan 相关 commit)
- ✅ 实测数据确认: 用户跑了 K1=0 + K1=+0.5 测试帧 (`/Users/bip.lan/Downloads/screen_live camera 01 transmission_00051.exr` 和 `00052.exr`)
- ⏳ 用户按本 plan Task 6 用 over-scan 1.5× 重渲完整 51 帧, 上传

---

## 文件结构 (相比上一 plan 的差异)

| 路径 | 上一 plan 改动 | 本 plan 进一步改动 |
|---|---|---|
| `scripts/distortion_calibration/generate_uv_probe.py` | 加 `--camera-resolution` 参数 | **保留, 无改动** (no harm) |
| `scripts/distortion_calibration/uv_probe_5760x3240.exr` | 已生成 | **可删 (没用了)** 或保留作 deprecated |
| `scripts/distortion_calibration/uv_probe_truth_5760x3240.npz` | 已生成 | **可删** |
| `scripts/distortion_calibration/_exr.py` | `load_probe_meta` 返回 4-tuple | **保留, 无改动** (camera_W == probe_W 时退化等价) |
| `scripts/distortion_calibration/analyze_renders.py` | `compute_displacements` cx=probe_W/2 + half_w=camera_W/2 | **revert** 回简单 cx=W/2 + half_w=W/2 + **加 over-scan 自动检测 + R/G 补偿** |
| `scripts/distortion_calibration/fit_distortion_models.py` | half_w 从 camera_W/2 取 | **保留, 无改动** (camera_W == probe_W = 3840 时跟旧代码等价) |
| `scripts/distortion_calibration/USER_INSTRUCTIONS.md` | Round 2.1 over-scan 重渲指引 | **revise** 改成"用 Disguise over-scan 1.5×, 输出仍是 4K, 不需要换探针图" |

---

## Task 1: 盘点上一 plan 的实施成果 + 决定保留/revert

**Files:** N/A (诊断 + 决策)

- [ ] **Step 1: 看上一 plan 实施的 commit 链**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git log --oneline 9ae06b0..HEAD scripts/distortion_calibration/ docs/
```

期望: 一连串 (~5-7 个) Round 2.1 over-scan probe 相关 commit, 应当包含 generate_uv_probe.py / _exr.py / analyze_renders.py / fit_distortion_models.py 改动 + uv_probe_5760x3240 生成。

- [ ] **Step 2: 验证上一 plan 改动跟实测数据兼容性**

读上一 plan 改完的 `analyze_renders.py compute_displacements`, 看签名是 `(R, G, W_probe, H_probe, W_camera, H_camera, axis, K_value, ...)` 还是其他。

跑下面命令测当前代码在简化场景 (W_probe = W_camera = 3840) 下行为:

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts/distortion_calibration')
from analyze_renders import compute_displacements
import numpy as np

# Identity probe at 4K (假设没有 over-scan 拉伸)
W, H = 3840, 2160
xs = (np.arange(W, dtype=np.float32) + 0.5) / W
ys = (np.arange(H, dtype=np.float32) + 0.5) / H
R = np.broadcast_to(xs, (H, W)).copy()
G = np.broadcast_to(ys[:, None], (H, W)).copy()
rng = np.random.default_rng(42)

# 调用 compute_displacements (上一 plan 签名是 6 个 dim 参数 + axis + K_value + rng + n_samples)
result = compute_displacements(R, G, W, H, W, H, axis=1, K_value=0.5, rng=rng, n_samples=100)

# Identity 数据下 src_x_norm 应该 = R*2 - 1, 即 [-1, +1]
print(f'src_x_norm range: [{result[\"src_x_norm\"].min():.3f}, {result[\"src_x_norm\"].max():.3f}]')
print(f'expected: [~ -1.0, ~ +1.0]')
"
```

- 如果 src_x_norm 范围 ≈ [-1, +1]: 上一 plan 代码在 W_probe == W_camera 简化场景下行为正确, 只需要再加 over-scan 检测 + 补偿
- 如果范围不对: 上一 plan 代码有 bug, Step 3 要修

- [ ] **Step 3: 决策 — 留保留, 改的改**

| 上一 plan 实施 | 本 plan 决策 |
|---|---|
| `generate_uv_probe.py --camera-resolution` 参数 | 保留 (no harm) |
| `uv_probe_5760x3240.exr` + npz | **删除** (没用了, 留着误导) |
| `_exr.load_probe_meta` 4-tuple 返回 | 保留 (向后兼容好) |
| `analyze_renders.compute_displacements` 6 dim 参数 | 保留签名 + 在内部加 over-scan 补偿 (Task 3) |
| `fit_distortion_models.py` half_w from camera_W | 保留 (camera_W == probe_W = 3840 时等价) |

- [ ] **Step 4: 删除 5760×3240 探针 (没用)**

```bash
rm scripts/distortion_calibration/uv_probe_5760x3240.exr scripts/distortion_calibration/uv_probe_truth_5760x3240.npz
```

如果上一 plan 改了 `_exr.py` 的 `PROBE_OVERSCAN`/`PROBE_OVERSCAN_TRUTH` 默认 fallback 顺序, 这次也要把 over-scan 探针从 fallback 列表移除, 否则 auto-detect 会找不到文件报 FileNotFoundError 或者 silently 走 4K. 检查 + 修:

```python
# _exr.py load_probe_meta auto-detect 顺序应当是:
# 4K → 1080p → legacy
# 不再有 over-scan 探针
```

- [ ] **Step 5: Commit decision (清理 5760×3240 探针)**

```bash
git add scripts/distortion_calibration/uv_probe_5760x3240.exr scripts/distortion_calibration/uv_probe_truth_5760x3240.npz scripts/distortion_calibration/_exr.py
git commit -m "$(cat <<'EOF'
revert(distortion-probe): 删 5760×3240 over-scan 探针 (实测 Disguise 输出 4K, 不需要大探针)

实测发现 Disguise over-scan 1.5× 渲染输出仍是 nominal 4K (3840×2160), R/G 被
仿射拉伸到 [0.1667, 0.8330] 范围. 不需要换大探针图, 简化方案是 K=0 anchor
自动检测 over-scan factor + R/G 反向补偿. 删除上一 plan 生成但用不到的 5760×3240
探针 + 同步从 _exr.py auto-detect fallback 移除.

保留 _exr.load_probe_meta 4-tuple API 跟 generate_uv_probe.py --camera-resolution
参数 (向后兼容, 未来需要时仍可用).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 加 over-scan 自动检测函数到 `analyze_renders.py`

**Files:**
- Modify: `scripts/distortion_calibration/analyze_renders.py`

- [ ] **Step 1: 加 detect_overscan_from_anchor 函数**

定位 `compute_displacements` 函数前 (大概 line 80-100 附近), 加新函数:

```python
def detect_overscan_from_anchor(
    R: np.ndarray, G: np.ndarray, edge_margin_px: int = 4,
) -> tuple[float, float]:
    """从 K=0 anchor 帧 R/G 通道反推 Disguise over-scan 比例和 margin.

    Disguise 1.5× over-scan 在导出 EXR 时把渲染范围裁回 nominal, R/G 范围被
    仿射拉伸: R_observed = R_uncorrected * (1/S) + margin, 其中 S 是
    over-scan factor, margin = (1 - 1/S) / 2.

    实测 1.5× over-scan: R 范围 [0.1667, 0.8330], margin = 1/6 ≈ 0.1667, S = 1.5
    无 over-scan (S=1.0): R 范围 [0, 1], margin = 0

    Returns
    -------
    (overscan_factor, margin) — overscan_factor ∈ [1.0, 2.0+], margin ∈ [0, 0.5)

    Raises
    ------
    ValueError if R/G shapes mismatch or detection failure (e.g., over-scan
    detected as < 1.0 means probe data 损坏).
    """
    if R.shape != G.shape:
        raise ValueError(f"R/G shape mismatch: {R.shape} vs {G.shape}")
    H, W = R.shape

    # 用中心行 R 通道 (整行避开 边缘 像素 noise) 推 R 范围
    cr = H // 2
    R_row = R[cr, edge_margin_px : W - edge_margin_px]
    R_min = float(R_row.min())
    R_max = float(R_row.max())

    # 用中心列 G 通道推 G 范围 (理论上应当跟 R 范围对称)
    cc = W // 2
    G_col = G[edge_margin_px : H - edge_margin_px, cc]
    G_min = float(G_col.min())
    G_max = float(G_col.max())

    # 取 R/G 范围中位 (避免某一通道有 noise)
    span_R = R_max - R_min
    span_G = G_max - G_min
    span = (span_R + span_G) / 2.0

    if span < 0.5:
        raise ValueError(
            f"detected R/G span = {span:.3f} < 0.5, over-scan factor would be > 2× "
            f"(R: [{R_min:.4f}, {R_max:.4f}], G: [{G_min:.4f}, {G_max:.4f}]). "
            f"Probe data likely corrupted."
        )
    overscan_factor = 1.0 / span
    margin = (R_min + G_min) / 2.0  # 平均 X/Y margin (理论一致)

    # Sanity: margin = (1 - span) / 2 应当接近 R_min
    expected_margin = (1.0 - span) / 2.0
    if abs(margin - expected_margin) > 0.01:
        # 可能 over-scan 不是对称的 (X 跟 Y margin 不同), 警告但不报错
        print(f"  [warn] margin asymmetry: detected {margin:.4f}, expected {expected_margin:.4f}")

    return overscan_factor, margin
```

- [ ] **Step 2: 改 main 把 detect_overscan_from_anchor 接进 anchor sanity check**

定位 main 里 anchor sanity check 区段 (大概 line 220+, 在 `for axis_name in ("K1", "K2", ...)` 那段附近):

```python
    # Anchor sanity + over-scan 自动检测
    overscan_factor = 1.0  # default no over-scan
    overscan_margin = 0.0
    for cand in sorted(exr_files):
        try:
            axis, K_value = parse_k_value(cand.stem)
        except ValueError:
            continue
        if abs(K_value) < 1e-9 and axis == 1:  # K1=0 anchor (优先用 K1=0)
            R_anchor, G_anchor = read_uvprobe_exr(cand)
            anchor_sanity_check(cand, W_probe, H_probe)
            try:
                overscan_factor, overscan_margin = detect_overscan_from_anchor(R_anchor, G_anchor)
                print(f"  [over-scan] detected factor = {overscan_factor:.3f}× , margin = {overscan_margin:.4f}")
                if overscan_factor > 1.01:
                    print(f"  [over-scan] R/G 通道将做反仿射补偿: R_corrected = (R - {overscan_margin:.4f}) / {1 - 2*overscan_margin:.4f}")
            except ValueError as e:
                print(f"  [over-scan] detection failed: {e}, 假设 no over-scan (factor=1.0)")
                overscan_factor = 1.0
                overscan_margin = 0.0
            break
    # 如果遍历完没找到 K1=0 anchor, 默认 no over-scan
```

(具体 anchor sanity check 调用细节按上一 plan 实施的代码风格调整)

- [ ] **Step 3: 把 over-scan 参数传给 compute_displacements**

在 main 里调用 compute_displacements 的地方, 加 overscan_factor 和 overscan_margin 参数:

```python
result = compute_displacements(
    R, G,
    W_probe, H_probe, W_camera, H_camera,
    axis, K_value, rng, args.samples_per_frame,
    overscan_factor=overscan_factor, overscan_margin=overscan_margin,  # 新增
)
```

- [ ] **Step 4: Commit**

```bash
git add scripts/distortion_calibration/analyze_renders.py
git commit -m "$(cat <<'EOF'
feat(distortion-analyze): 加 over-scan 自动检测函数

detect_overscan_from_anchor 从 K=0 anchor 帧的 R/G 通道反推 Disguise
over-scan factor (S) 和 margin. 实测 1.5× over-scan 给出 R 范围 [0.1667,
0.8333], margin = (1 - 1/S) / 2 = 1/6, 完美仿射规律.

main 流程在 anchor sanity check 阶段调用, 把 (factor, margin) 传给
compute_displacements 做后续 R/G 反仿射补偿. 默认 fallback no over-scan
(S=1.0, margin=0), 跟旧数据兼容.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 在 `compute_displacements` 内加 R/G 反仿射补偿

**Files:**
- Modify: `scripts/distortion_calibration/analyze_renders.py:compute_displacements`

- [ ] **Step 1: 加 overscan 参数到签名**

```python
def compute_displacements(
    R: np.ndarray, G: np.ndarray,
    W_probe: int, H_probe: int, W_camera: int, H_camera: int,
    axis: int, K_value: float, rng: np.random.Generator,
    n_samples: int = SAMPLES_PER_FRAME,
    overscan_factor: float = 1.0, overscan_margin: float = 0.0,  # 新增
) -> dict[str, np.ndarray] | None:
```

- [ ] **Step 2: 在采样后, src_x_norm/src_y_norm 计算前, 加 R/G 反仿射补偿**

定位 `R_s = R.ravel()[sample]` `G_s = G.ravel()[sample]` 之后, `src_x_norm = ...` 之前:

```python
    R_s = R.ravel()[sample]
    G_s = G.ravel()[sample]

    # Over-scan 反仿射补偿: 当 Disguise over-scan 1.5× 时 R/G 被拉伸到
    # [margin, 1 - margin], 这里把它映射回 [0, 1] 等价坐标. no over-scan
    # (factor=1, margin=0) 时本步骤是恒等变换.
    if overscan_factor > 1.01 or abs(overscan_margin) > 1e-6:
        usable_span = 1.0 - 2.0 * overscan_margin
        R_s = (R_s - overscan_margin) / usable_span
        G_s = (G_s - overscan_margin) / usable_span

    # 后续 src_x_norm / src_y_norm 计算照旧
    out_x_norm = (xs.astype(np.float64) + 0.5 - cx) / half_w
    out_y_norm = (ys.astype(np.float64) + 0.5 - cy) / half_w
    src_x_norm = (R_s * W - cx) / half_w  # ← R_s 已经是补偿后的 [0,1] 等价值
    src_y_norm = (G_s * H - cy) / half_w
    ...
```

注意: 这里 `cx = W / 2` 跟 `half_w = W / 2` 仍是用 probe 的 W (= 3840 在简化场景下), 因为补偿后的 R_s 本身就是相对 probe 的 [0,1] 坐标。

- [ ] **Step 3: 验证补偿正确性 (Identity 数据 + 1.5× 拉伸数据)**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts/distortion_calibration')
from analyze_renders import compute_displacements
import numpy as np

W, H = 3840, 2160
rng = np.random.default_rng(42)

# 场景 1: identity probe, no over-scan, 应当 src_x_norm ∈ [-1, +1]
xs = (np.arange(W, dtype=np.float32) + 0.5) / W
R = np.broadcast_to(xs, (H, W)).copy()
G = np.broadcast_to(((np.arange(H, dtype=np.float32) + 0.5) / H)[:, None], (H, W)).copy()
res = compute_displacements(R, G, W, H, W, H, axis=1, K_value=0.5, rng=rng, n_samples=1000,
                            overscan_factor=1.0, overscan_margin=0.0)
print(f'no over-scan: src_x_norm range = [{res[\"src_x_norm\"].min():.3f}, {res[\"src_x_norm\"].max():.3f}]')

# 场景 2: 1.5× over-scan 拉伸 (R/G 从 [0,1] 缩到 [0.1667, 0.8333])
margin = 1.0 / 6.0
R_oscan = R / 1.5 + margin
G_oscan = G / 1.5 + margin
res2 = compute_displacements(R_oscan, G_oscan, W, H, W, H, axis=1, K_value=0.5, rng=rng, n_samples=1000,
                              overscan_factor=1.5, overscan_margin=margin)
print(f'1.5× over-scan after correction: src_x_norm range = [{res2[\"src_x_norm\"].min():.3f}, {res2[\"src_x_norm\"].max():.3f}]')

# 两者应当几乎一致 (identity 探针, 任何 over-scan 补偿后 src ≡ output 的 r 关系)
print(f'差异 (理论应 < 1e-3): {abs(res[\"src_x_norm\"].max() - res2[\"src_x_norm\"].max()):.6f}')
"
```

期望: 两个场景的 src_x_norm 范围都接近 [-1, +1], 差异 < 0.001。

- [ ] **Step 4: Commit**

```bash
git add scripts/distortion_calibration/analyze_renders.py
git commit -m "$(cat <<'EOF'
feat(distortion-analyze): compute_displacements 加 R/G 反仿射补偿

接收 overscan_factor + overscan_margin 参数. 在采样后、src_*_norm 计算前,
对 R/G 通道做反仿射: R_corrected = (R - margin) / (1 - 2*margin), 把
Disguise over-scan 拉伸的 R/G 通道还原到 [0,1] 等价坐标. no over-scan
(factor=1.0, margin=0) 时是恒等变换, 跟旧数据兼容.

Verify: identity probe 在 no over-scan 跟 1.5× over-scan + 补偿后, src_x_norm
范围都收敛到 [-1, +1], 差异 < 1e-3. 物理畸变系数跟 over-scan 设置无关.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 单元测试 over-scan 检测 + 补偿

**Files:**
- Create temporary: `scripts/distortion_calibration/_test_overscan_detect.py` (Step 4 末删, 不入仓)

- [ ] **Step 1: 写测试**

```python
"""Verify detect_overscan_from_anchor 检测 over-scan factor + margin 正确,
以及 compute_displacements R/G 反仿射补偿不破坏 identity 关系.
"""
from __future__ import annotations

import numpy as np

from analyze_renders import detect_overscan_from_anchor, compute_displacements


def assert_close(actual, expected, label, tol=1e-3):
    if abs(actual - expected) > tol:
        raise AssertionError(f"{label}: got {actual:.6f}, expected {expected:.6f}, delta {actual-expected:.6f}")
    print(f"  ✓ {label}: {actual:.6f} (expected {expected:.6f})")


W, H = 3840, 2160

# Test 1: no over-scan (S=1.0, margin=0)
xs = (np.arange(W, dtype=np.float32) + 0.5) / W
ys = (np.arange(H, dtype=np.float32) + 0.5) / H
R = np.broadcast_to(xs, (H, W)).copy()
G = np.broadcast_to(ys[:, None], (H, W)).copy()
factor, margin = detect_overscan_from_anchor(R, G)
print("=== Test 1: identity (no over-scan) ===")
assert_close(factor, 1.0, "factor")
assert_close(margin, 0.0, "margin", tol=1e-3)

# Test 2: 1.5× over-scan
S = 1.5
exp_margin = (1 - 1/S) / 2  # = 1/6 ≈ 0.16667
R_oscan = R / S + exp_margin
G_oscan = G / S + exp_margin
factor, margin = detect_overscan_from_anchor(R_oscan, G_oscan)
print()
print("=== Test 2: 1.5× over-scan ===")
assert_close(factor, 1.5, "factor")
assert_close(margin, exp_margin, "margin", tol=1e-3)

# Test 3: 2.0× over-scan (极端情况)
S = 2.0
exp_margin = 0.25
R_oscan2 = R / S + exp_margin
G_oscan2 = G / S + exp_margin
factor, margin = detect_overscan_from_anchor(R_oscan2, G_oscan2)
print()
print("=== Test 3: 2.0× over-scan ===")
assert_close(factor, 2.0, "factor")
assert_close(margin, exp_margin, "margin", tol=1e-3)

# Test 4: compute_displacements 在 1.5× over-scan + 补偿后等价于 no over-scan
print()
print("=== Test 4: compute_displacements 补偿后 src_x_norm 一致性 ===")
rng = np.random.default_rng(42)
res_clean = compute_displacements(R, G, W, H, W, H, axis=1, K_value=0.0, rng=rng, n_samples=10000)
rng = np.random.default_rng(42)  # same seed
res_oscan = compute_displacements(R_oscan, G_oscan, W, H, W, H, axis=1, K_value=0.0, rng=rng,
                                   n_samples=10000, overscan_factor=1.5, overscan_margin=1/6)
diff = np.abs(res_clean["src_x_norm"] - res_oscan["src_x_norm"]).max()
assert_close(diff, 0.0, "src_x_norm max diff (clean vs over-scan-compensated)", tol=1e-3)

print()
print("ALL OVER-SCAN DETECT/COMPENSATE TESTS PASSED")
```

- [ ] **Step 2: 跑测试**

```bash
cd scripts/distortion_calibration && .venv/bin/python _test_overscan_detect.py
```

期望: 全 ✓ 通过。

- [ ] **Step 3: 删测试**

```bash
rm scripts/distortion_calibration/_test_overscan_detect.py
```

- [ ] **Step 4: 不 commit (无文件改动)**

---

## Task 5: 用实测两帧 + 旧 51 帧验证

**Files:**
- Run only

- [ ] **Step 1: 实测两帧验证 (用户上传的 K1=0 / K1=+0.5)**

```bash
mkdir -p /tmp/oscan_test
cp "/Users/bip.lan/Downloads/screen_live camera 01 transmission_00051.exr" /tmp/oscan_test/disguise_K1_zero.exr
cp "/Users/bip.lan/Downloads/screen_live camera 01 transmission_00052.exr" /tmp/oscan_test/disguise_K1_p0p50.exr
.venv/bin/python analyze_renders.py --input-dir /tmp/oscan_test --output /tmp/oscan_test_displacements.csv --samples-per-frame 100000 2>&1 | tail -15
```

期望:
- `[over-scan] detected factor = 1.500× , margin = 0.1667` 一行
- 输出 100000 行 (1 个非 zero 帧 × 100k samples)
- K1=+0.5 帧采样统计无 ValueError

- [ ] **Step 2: 旧 51 帧回归 (无 over-scan, factor 应当检测为 1.0)**

```bash
.venv/bin/python analyze_renders.py --input-dir validation_results/k1_sweep --output /tmp/round2_legacy_check.csv --samples-per-frame 100000 2>&1 | tail -10
```

期望:
- `[over-scan] detected factor = 1.000× , margin = 0.0000`
- 输出 5,000,000 行 (50 非 zero × 100k)
- 跟 commit `8d4019d` 之前的 displacements_round2_k1.csv MD5 完全一致 (no over-scan path 行为不变)

```bash
md5 -q /tmp/round2_legacy_check.csv /tmp/displacements_round2_k1.csv
```

如果 MD5 不一致, 说明 Task 3 的补偿代码在 factor=1.0 分支不是恒等, 修。

- [ ] **Step 3: 不 commit (诊断输出不入仓)**

---

## Task 6: 等数据 — 用户用 over-scan 1.5× 重渲完整 51 帧 (BLOCKED)

**Files:**
- Create temporary: `validation_results/k1_sweep_overscan/disguise_K1_*.exr` (新数据, 不入仓 — `.gitignore` 已兜)

**前置条件**: 用户在 Disguise 端用 over-scan 1.5× 配置渲完整 51 帧 K1 sweep, 上传到 `validation_results/k1_sweep_overscan/`。

- [ ] **Step 1: 通知用户开始重渲**

参考新版 `USER_INSTRUCTIONS.md` Round 2.1 章节 (Task 7 会更新), 渲 51 帧 4K K1 sweep + over-scan 1.5×。

- [ ] **Step 2: smoke 检查上传完整性**

```bash
ls validation_results/k1_sweep_overscan/disguise_K1_*.exr | wc -l   # 期望 51
.venv/bin/python -c "
import os; os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
import cv2
from pathlib import Path
for f in sorted(Path('validation_results/k1_sweep_overscan').glob('*.exr')):
    img = cv2.imread(str(f), cv2.IMREAD_UNCHANGED)
    print(f'{f.name}: shape={img.shape}, dtype={img.dtype}')
" | head -10
```

期望: 全部 51 帧 shape=(2160, 3840, 3 or 4), dtype=float32。

- [ ] **Step 3: 跑 analyze_renders 全 51 帧 over-scan**

```bash
.venv/bin/python analyze_renders.py \
    --input-dir validation_results/k1_sweep_overscan \
    --output /tmp/displacements_round2_k1_overscan.csv \
    --samples-per-frame 100000 2>&1 | tail -15
```

期望:
- `[over-scan] detected factor = 1.500× , margin = 0.1667`
- 51 帧 anchor sanity 通过
- 5,000,000 rows 写入 CSV
- K1 values 51 个

- [ ] **Step 4: 跑 fit 14 候选**

```bash
.venv/bin/python fit_distortion_models.py \
    --input /tmp/displacements_round2_k1_overscan.csv \
    --trim-pct 5 2>&1 | tee /tmp/round2_overscan_fit.log | tail -50
```

期望对比 (vs commit `8d4019d` 之前的 K1+ 黑边数据):

| 指标 | 旧数据 (无 over-scan) | over-scan 数据 |
|---|---|---|
| K1- max residual | ~3 px @ 4K | 应当持平 ~3 px |
| **K1+ max residual** | **76-97 px** | **应当回到 ~3 px** ← 主要改善 |
| 整体 RMS | 0.731 px | 应当显著下降 |
| M_RAT6 系数 a/b/c | -0.66 / -1.24 / -0.40 (飘了) | 应当回到 Round 1 量级 -3.18 / +7.24 / +5.12 附近 |

如果 K1+ max 仍 > 10 px → over-scan 1.5× 不够, 让用户尝试 2.0×。

- [ ] **Step 5: 不 commit (诊断输出不入仓)**

---

## Task 7: 更新 `USER_INSTRUCTIONS.md` Round 2.1 → over-scan 1.5× 简化指引

**Files:**
- Modify: `scripts/distortion_calibration/USER_INSTRUCTIONS.md`

- [ ] **Step 1: 把上一 plan 写的 "5760×3240 over-scan probe" 段落改成 "Disguise over-scan 1.5× + 4K 输出"**

定位 `## ⏳ Round 2.1 · 1.5× over-scan K1 sweep` 章节 (上一 plan 改的), 替换:

```markdown
## ⏳ Round 2.1 · Disguise over-scan 1.5× K1 sweep（51 帧 4K, 当前要做）

**目的**：用 Disguise lens over-scan 1.5× 修复 Round 2.0 直渲 4K 时 K1>0 帧的黑边问题, 不需要换探针图。

**Disguise 端配置 (已实测确认)**:
- **相机分辨率**: 5760×3240 (over-scan 内部渲染分辨率, 自动)
- **导出 EXR 分辨率**: 仍是 3840×2160 (4K, Disguise 自动裁回 nominal)
- **lens over-scan ratio**: 1.5
- **探针图**: 仍用现有 `uv_probe_3840x2160.exr` (4K 探针, 不需要换)
- 其他 (sensor / focal_length / FOV / CenterShift): 全部跟 Round 2.0 一致

**实测验证 (2026-04-30)**:
- K=0 anchor 帧: R/G 范围 [0.1667, 0.8330] (1.5× over-scan 仿射规律)
- K1=+0.5 帧: R/G 范围 [0.1119, 0.8877], 全画面无黑边 ✓

**Mac 端处理**:
- `analyze_renders.py` 自动从 K=0 anchor 检测 over-scan factor (1.5×) + margin (0.1667)
- 对所有帧 R/G 通道做反仿射补偿, 把 over-scan 拉伸还原到 [0, 1] 等价坐标
- fit pipeline 不用改, 直接跑

**输出目录** (跟之前一致):
```
validation_results/k1_sweep_overscan/
├── disguise_K1_zero.exr
├── disguise_K1_p0p02.exr
... (51 帧 4K, 文件名跟 Round 2.0 一致)
└── disguise_K1_n0p50.exr
```

**Note**: 这跟上一版 plan 描述的 "5760×3240 探针图" 路线**不一样**。实测确认 Disguise 端不需要换探针图, 仅靠 lens over-scan 1.5× 设置就够。
```

- [ ] **Step 2: 删除上一 plan 写的 "Disguise 工程师必须用 5760×3240 LED + 5760×3240 渲染输出" 那段**

USER_INSTRUCTIONS 里如果有这段 (上一 plan 改的), 删除或改成"用 4K 探针 + 开 over-scan 1.5×"。

- [ ] **Step 3: 提醒 sanity check 验证**

加一段:

```markdown
### 渲染前 sanity 验证

先单渲 K1=0 + K1=+0.5 两张, 上传 Mac 给我用 OpenCV 验证:

```python
import cv2, numpy as np, os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'

# K=0 帧应当 R/G 范围 [0.1667, 0.8333] (1.5× over-scan 仿射规律)
img = cv2.imread('disguise_K1_zero.exr', cv2.IMREAD_UNCHANGED)
print(f'K=0 R range: [{img[..., 2].min():.4f}, {img[..., 2].max():.4f}]')
# 期望: [0.1667, 0.8333]

# K1=+0.5 帧应当无黑边 (R/G 全 > 0.005)
img = cv2.imread('disguise_K1_p0p50.exr', cv2.IMREAD_UNCHANGED)
center_R = img[540:1620, 960:2880, 2]
print(f'K1=+0.5 中心区 R 范围: [{center_R.min():.4f}, {center_R.max():.4f}]')
# 期望: [~0.11, ~0.89], 无 R<0.005 黑边
```

Sanity 通过再渲全套 51 帧。
```

- [ ] **Step 4: Commit**

```bash
git add scripts/distortion_calibration/USER_INSTRUCTIONS.md
git commit -m "$(cat <<'EOF'
docs(user-instructions): Round 2.1 改 Disguise lens over-scan 1.5× + 4K 输出

实测确认 Disguise lens over-scan 1.5× 渲染输出仍是 nominal 4K (3840×2160), R/G
通道被仿射拉伸到 [0.1667, 0.8333]. 不需要换 5760×3240 大探针图.

USER_INSTRUCTIONS Round 2.1 章节改成: 用现有 4K 探针 + 开 lens over-scan 1.5×,
导出 4K EXR. Mac 端自动检测 + 补偿.

替换上一 plan 写的 "5760×3240 LED + 5760×3240 渲染输出" 那一套 (实测发现
Disguise 不需要那么折腾, lens over-scan 开关即可).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 复用原 plan 2026-04-29 §Task 6-12 完成 deploy + Tier 1/2 验证

**前置条件**: Task 6 完成, BIC-best 系数 + RMS 实测就绪.

跟 plan `2026-04-29-distortion-fit-harness-round2.md` Tasks 6-12 一致 (本 plan 不重复):
- §Task 6: distortion_math.py 系数填入
- §Task 9: lanPC Tier 1 deploy + verify
- §Task 10: Tier 2 EXR-based displacement field validation
- §Task 11: UE 4K render + Lanczos compare
- §Task 12: docs 更新

---

## Self-Review

### 1. Spec coverage

- ✅ 删 5760×3240 探针 + npz (Task 1)
- ✅ over-scan 自动检测函数 (Task 2)
- ✅ R/G 反仿射补偿 (Task 3)
- ✅ 单元测试 (Task 4)
- ✅ 实测两帧 + 旧 51 帧回归验证 (Task 5)
- ✅ 等数据 + over-scan fit (Task 6)
- ✅ USER_INSTRUCTIONS 更新 (Task 7)
- ✅ deploy + Tier 1/2 验证 (Task 8, 复用原 plan)

### 2. Placeholder scan

无 TBD / TODO / "implement later".

### 3. Type / 函数名一致性

- `detect_overscan_from_anchor(R, G, edge_margin_px=4) -> tuple[float, float]`
- `compute_displacements(..., overscan_factor=1.0, overscan_margin=0.0)` — 默认值 = no over-scan, 跟旧数据兼容
- main 流程: anchor sanity → detect → 传给 compute_displacements
- 4-tuple metadata API (上一 plan 加的) 保留, 简化场景 camera_W == probe_W

无类型不一致.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-30-distortion-overscan-autodetect.md`.**

**两种执行方式:**

**1. Subagent-Driven (推荐)** - 每个 Task dispatch fresh subagent, 任务间 spec + code quality 双 review

**2. Inline Execution** - 当前 session executing-plans skill, 批量执行 + checkpoint review

**这个 plan 是 *修改* 上一 plan 的实施成果, 不是从零开始.**
- Tasks 1-4 是代码改造 (本地不依赖数据), 在新 session 一口气做完
- Task 5 用实测两帧 + 旧 51 帧验证, 也不依赖新数据
- Task 6 BLOCKED 等用户用 over-scan 1.5× 重渲完整 51 帧
- Task 7 是 docs 更新, 跟 Tasks 1-4 同 session 做完
- Task 8 复用原 plan 2026-04-29 §Task 6-12 流程, 等 Task 6 完成后开始
