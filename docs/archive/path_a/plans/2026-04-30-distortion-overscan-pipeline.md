# Distortion Over-scan Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Round 2 K1 sweep 在 4K 直渲下, K1>0 帧的"枕形畸变把源像素拉到 LED 屏幕外面"导致 ~1% 像素是 fallback 脏数据 (max residual 76-97 px). 引入 1.5× over-scan probe (5760×3240) 让源采样始终落在有效区, 把 fit 残差从 76 px 拉回到 K1- side 同水平 (~3 px @ 4K).

**Architecture:**
- 数据流不变: EXR → analyze_renders → displacements.csv → fit_distortion_models → distortion_math.py 系数 → LensFile
- 关键变化: probe 尺寸 5760×3240 (over-scan factor S=1.5), camera 仍是 3840×2160 名义上. analyze_renders 将 R/G ∈ [0,1] of probe 换算到 camera-normalized 坐标 (R*2S - S = R*3 - 1.5), 这样 fit 系数仍跟 UE BrownConrady 形态一致, 也不破坏既有 distortion_math.py 转换公式
- 兼容旧探针: truth npz 缺 camera_width 时默认为 probe_width (over-scan factor S=1, 老路径行为不变)

**Tech Stack:**
- 已就位: numpy 2.4 / scipy 1.17 / cv2 4.13 / Mac venv `scripts/distortion_calibration/.venv/`
- 已就位 4K probe: `uv_probe_3840x2160.exr` + `uv_probe_truth_3840x2160.npz` (commit `98eb839`)
- 已就位 51 帧 4K K1 sweep (但因为黑边问题需要重渲): `validation_results/k1_sweep/disguise_K1_*.exr`
- 待生成: `uv_probe_5760x3240.exr` + 新版 `uv_probe_truth_5760x3240.npz` (含 camera_width/camera_height 字段)
- 待 Disguise 工程师重渲: 51 帧 5760×3240 over-scan K1 sweep

**前置条件 (本计划开始执行前必须满足):**
- ✅ Round 2 4K K1 sweep fit 已诊断: K1+ 帧 max=76-97 px 因 K1>0 拉源像素出 LED 边界 (commit `8d4019d` 之后)
- ✅ USER_INSTRUCTIONS.md 已更新到 over-scan 渲染指引 (本 session 内做的)
- ⏳ Disguise 工程师按 USER_INSTRUCTIONS 新指引重渲 51 帧 5760×3240 → `validation_results/k1_sweep_overscan/`
- 数据未到时 Task 1-5 (代码 + 探针生成) 仍可独立做完, 等数据到再做 Task 6-7

---

## 文件结构 (改动一览)

| 路径 | 改动类型 | 用途 |
|---|---|---|
| `scripts/distortion_calibration/generate_uv_probe.py` | 修改 | 生成 truth npz 时写入 camera_width/camera_height 字段; CLI 支持 `--camera-resolution WxH` 参数 |
| `scripts/distortion_calibration/uv_probe_5760x3240.exr` | 新建 (生成产物) | 1.5× over-scan 探针 EXR |
| `scripts/distortion_calibration/uv_probe_truth_5760x3240.npz` | 新建 (生成产物) | over-scan 探针真值 + camera dims |
| `scripts/distortion_calibration/_exr.py` | 修改 | `load_probe_meta` 返回 4-tuple `(probe_W, probe_H, camera_W, camera_H)`; 加 `PROBE_OVERSCAN` 常量 |
| `scripts/distortion_calibration/analyze_renders.py` | 修改 | `compute_displacements` 用 `cx=probe_W/2` 但 `half_w=camera_W/2` 做 camera-normalized 坐标 |
| `scripts/distortion_calibration/fit_distortion_models.py` | 修改 | `main()` 里 `half_w` 默认从 `camera_W/2` 来 (不是 `probe_W/2`); 输出加 over-scan factor 标注 |
| `scripts/distortion_calibration/_test_overscan_coords.py` | 新建 (临时, Task 5 末删) | 单元测试覆盖坐标换算公式 |

**不动**: `distortion_math.py` (production 用 fx-normalized 系数, 跟 probe 尺寸无关), `distortion_packing.py`, 任何 `Content/Python/` 下的代码.

---

## Task 1: `generate_uv_probe.py` 加 camera-resolution 参数 + 输出 camera dims 到 npz

**Files:**
- Modify: `scripts/distortion_calibration/generate_uv_probe.py`

- [ ] **Step 1: Read 现状**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
sed -n '1,80p' generate_uv_probe.py
```

期望看到 `build_probe(W, H)` + main argparse `--resolution WxH` + np.savez 写入 width/height/B0/4-corner truth values.

- [ ] **Step 2: 加 `--camera-resolution` argparse + 写 npz 字段**

定位 `def main()` (大概 line 50+), 在 argparse 区域追加:

```python
    ap.add_argument(
        "--camera-resolution", type=str, default=None,
        help="Camera frame resolution as WxH (e.g., '3840x2160'). 默认等于 --resolution "
             "(no over-scan). Over-scan factor 隐式由 probe_W / camera_W 推出.",
    )
```

定位 npz savez 调用 (大概 `np.savez(out_npz, ...)`), 改成:

```python
    if args.camera_resolution is not None:
        cam_w, cam_h = (int(s) for s in args.camera_resolution.lower().split("x"))
    else:
        cam_w, cam_h = W, H
    np.savez(
        out_npz,
        width=W, height=H,
        camera_width=cam_w, camera_height=cam_h,
        # ... existing 4-corner truth keys 保留 ...
    )
```

具体 4-corner keys 跟现有保持不变, 只追加 camera_width/camera_height.

- [ ] **Step 3: 跑生成 1.5× over-scan probe**

```bash
.venv/bin/python generate_uv_probe.py --resolution 5760x3240 --camera-resolution 3840x2160
```

期望:
- 产出 `uv_probe_5760x3240.exr` (~50-100 MB)
- 产出 `uv_probe_truth_5760x3240.npz` (含 width=5760, height=3240, camera_width=3840, camera_height=2160)

- [ ] **Step 4: 验证 npz 内容**

```bash
.venv/bin/python -c "
import numpy as np
truth = np.load('uv_probe_truth_5760x3240.npz', allow_pickle=True)
for k in sorted(truth.files):
    v = truth[k]
    print(f'{k}: shape={v.shape if v.ndim else \"scalar\"} value={v}')
"
```

期望: `width=5760`, `height=3240`, `camera_width=3840`, `camera_height=2160`, plus existing 4-corner truth keys.

- [ ] **Step 5: 回归生成 1× 探针确认 backward-compat**

```bash
.venv/bin/python generate_uv_probe.py --resolution 1920x1080
.venv/bin/python -c "
import numpy as np
t = np.load('uv_probe_truth_1920x1080.npz', allow_pickle=True)
print('camera_width' in t.files, dict((k, t[k]) for k in ('width', 'height', 'camera_width', 'camera_height') if k in t.files))
"
```

期望: 1× 模式下 camera_width 默认 = width, camera_height 默认 = height. (这次重新生成会覆盖现有 1080p 探针 npz, 内容应当一致 + 多 2 个字段)

- [ ] **Step 6: Commit**

```bash
git add scripts/distortion_calibration/generate_uv_probe.py \
        scripts/distortion_calibration/uv_probe_5760x3240.exr \
        scripts/distortion_calibration/uv_probe_truth_5760x3240.npz \
        scripts/distortion_calibration/uv_probe_truth_1920x1080.npz \
        scripts/distortion_calibration/uv_probe_truth_3840x2160.npz
git commit -m "$(cat <<'EOF'
feat(distortion-probe): 1.5× over-scan probe 生成 (5760×3240) + camera_resolution 字段

generate_uv_probe.py 加 --camera-resolution WxH 参数, npz 同时记录 probe 物理尺寸
(width/height) 和相机画面名义尺寸 (camera_width/camera_height). 默认 camera = probe
(no over-scan), 显式传 --camera-resolution 后 over-scan factor = probe_W / camera_W.

Round 2 K1+ 因为 K1>0 把源像素拉到 LED 范围外 (3840 边界外) 导致 ~1% 像素 fallback
脏数据, max residual 76-97 px. 1.5× over-scan 把 LED 范围扩到 5760×3240, K1>0 时
源仍落在有效区, 黑边问题消除.

回填 1080p 和 4K 旧探针 npz 同时加 camera_width/camera_height (= probe_W/probe_H,
backward-compat 行为不变).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `_exr.py` `load_probe_meta` 返回 4-tuple

**Files:**
- Modify: `scripts/distortion_calibration/_exr.py:29-46`

- [ ] **Step 1: Read 现状**

```bash
sed -n '17,50p' scripts/distortion_calibration/_exr.py
```

期望看到 PROBE_4K / PROBE_1080P / PROBE_LEGACY_TRUTH 常量 + `load_probe_meta(truth_path)` 返回 `tuple[int, int]`.

- [ ] **Step 2: 加 PROBE_OVERSCAN 常量**

在 PROBE 常量列表 (line 21-25 附近) 加:

```python
PROBE_OVERSCAN = HERE / "uv_probe_5760x3240.exr"
PROBE_OVERSCAN_TRUTH = HERE / "uv_probe_truth_5760x3240.npz"
```

把 PROBE_OVERSCAN_TRUTH 加到 `load_probe_meta` 默认 fallback 顺序最前 (4K → 1080p → legacy 之前):

```python
def load_probe_meta(truth_path: Path | None = None) -> tuple[int, int, int, int]:
    """Returns (probe_width, probe_height, camera_width, camera_height) from probe truth npz.

    If truth_path is None, tries over-scan 5760×3240 first, then 4K, then 1080p, then legacy.

    camera_* defaults to probe_* if absent in npz (backward compat with pre-overscan
    npz generated by older generate_uv_probe.py).
    """
    if truth_path is None:
        for cand in (PROBE_OVERSCAN_TRUTH, PROBE_4K_TRUTH, PROBE_1080P_TRUTH, PROBE_LEGACY_TRUTH):
            if cand.exists():
                truth_path = cand
                break
        if truth_path is None:
            raise FileNotFoundError("no probe truth npz found")
    truth = np.load(truth_path, allow_pickle=True)
    probe_w = int(truth["width"])
    probe_h = int(truth["height"])
    camera_w = int(truth["camera_width"]) if "camera_width" in truth.files else probe_w
    camera_h = int(truth["camera_height"]) if "camera_height" in truth.files else probe_h
    return probe_w, probe_h, camera_w, camera_h
```

- [ ] **Step 3: 更新 alias (PROBE_EXR / PROBE_TRUTH_NPZ) 也偏好 over-scan**

```python
# alias for legacy scripts (over-scan-preferred to match auto-detect)
if PROBE_OVERSCAN.exists():
    PROBE_EXR = PROBE_OVERSCAN
    PROBE_TRUTH_NPZ = PROBE_OVERSCAN_TRUTH
elif PROBE_4K.exists():
    PROBE_EXR = PROBE_4K
    PROBE_TRUTH_NPZ = PROBE_4K_TRUTH
else:
    PROBE_EXR = PROBE_1080P
    PROBE_TRUTH_NPZ = PROBE_1080P_TRUTH
```

替换现有 line 45-46 (那个 `PROBE_EXR = PROBE_4K if PROBE_4K.exists() else PROBE_1080P` 一行赋值).

- [ ] **Step 4: 跑测试**

```bash
.venv/bin/python -c "
from _exr import load_probe_meta, PROBE_OVERSCAN_TRUTH, PROBE_4K_TRUTH
# Auto-detect (over-scan 优先)
pw, ph, cw, ch = load_probe_meta()
print(f'auto: probe={pw}x{ph} camera={cw}x{ch} overscan={pw/cw:.2f}x')
# 显式 over-scan
pw, ph, cw, ch = load_probe_meta(PROBE_OVERSCAN_TRUTH)
print(f'overscan explicit: probe={pw}x{ph} camera={cw}x{ch}')
# 显式 4K (no over-scan)
pw, ph, cw, ch = load_probe_meta(PROBE_4K_TRUTH)
print(f'4K explicit: probe={pw}x{ph} camera={cw}x{ch}')
"
```

期望:
- `auto: probe=5760x3240 camera=3840x2160 overscan=1.50x`
- `overscan explicit: probe=5760x3240 camera=3840x2160`
- `4K explicit: probe=3840x2160 camera=3840x2160` (no over-scan, camera = probe)

- [ ] **Step 5: 跑老 self-test 验证回归**

```bash
.venv/bin/python _self_test_truth.py 2>&1 | tail -8
```

注意: `_self_test_truth.py` 用 `load_probe_meta()` no-arg, 现在拿到 4-tuple 不是 2-tuple, **可能 ValueError**. 看下 self-test 是怎么 unpacking 的:

```bash
grep -n "load_probe_meta" _self_test_truth.py _self_test_analyze.py
```

如果 self-test 写的是 `W, H = load_probe_meta()`, 改成 `W, H, _, _ = load_probe_meta()` 或 `*_, = load_probe_meta(); W, H = _[:2]`. 最简洁: 改 self-test 接 4 个变量 (这是 self-test 自身, 不是 production 代码, 直接改).

替换 self-test 里的 unpacking (大概 1-2 处):
```python
# Before: W, H = load_probe_meta()
# After:
W, H, _, _ = load_probe_meta()
```

- [ ] **Step 6: 重跑 self-test**

```bash
.venv/bin/python _self_test_truth.py 2>&1 | tail -5
```

期望: `self-test PASS` (因为现在 alias 偏好 over-scan probe, self-test 跑的是 5760×3240 数据, anchor 应该 < 1e-5).

- [ ] **Step 7: Commit**

```bash
git add scripts/distortion_calibration/_exr.py \
        scripts/distortion_calibration/_self_test_truth.py \
        scripts/distortion_calibration/_self_test_analyze.py
git commit -m "$(cat <<'EOF'
refactor(distortion-exr): load_probe_meta 返回 4-tuple (probe + camera dims)

加 PROBE_OVERSCAN/PROBE_OVERSCAN_TRUTH 常量, load_probe_meta auto-detect 顺序
改 over-scan → 4K → 1080p → legacy. 返回签名扩为 (probe_w, probe_h, camera_w,
camera_h); npz 缺 camera_width 字段时默认 = probe_width (backward-compat).

PROBE_EXR / PROBE_TRUTH_NPZ alias 同步改为偏好 over-scan probe (跟 auto-detect
顺序保持一致).

Self-test 脚本同步改 unpacking (W, H -> W, H, _, _).

Round 2 over-scan 路线代码改造的第一步.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `analyze_renders.py` 用 camera-normalized 坐标

**Files:**
- Modify: `scripts/distortion_calibration/analyze_renders.py:108-160` (compute_displacements 函数), 216 (load_probe_meta 调用)

- [ ] **Step 1: 改 main 里 load_probe_meta unpack**

定位 line 216:

```python
W, H = load_probe_meta(args.probe_truth)
```

改为:

```python
W_probe, H_probe, W_camera, H_camera = load_probe_meta(args.probe_truth)
overscan = W_probe / W_camera
print(f"[probe] {W_probe}x{H_probe}  camera={W_camera}x{H_camera}  overscan={overscan:.2f}x")
```

后续所有 `W` / `H` 引用要分清是 probe (用 `W_probe` / `H_probe`) 还是 camera (`W_camera` / `H_camera`).

- [ ] **Step 2: 改 anchor sanity check 调用 (line 224 附近)**

`anchor_sanity_check(cand, W, H)` 接收 probe shape, 改为:

```python
anchor_sanity_check(cand, W_probe, H_probe)
```

(anchor sanity 是验 EXR R/G 通道是否 ≈ identity grid, 用 probe shape 没问题)

- [ ] **Step 3: 改 main 里 shape guard (line 222 附近)**

```python
if R.shape != (H_probe, W_probe):
    print(f"  [skip] {exr_path.name}: shape {R.shape} ≠ probe {(H_probe, W_probe)}")
    continue
```

- [ ] **Step 4: 改 compute_displacements 签名 + 函数体**

定位 `def compute_displacements(R, G, axis, K_value, rng, n_samples=...)` (大概 line 108).

改成接收 4 个尺寸参数:

```python
def compute_displacements(
    R: np.ndarray, G: np.ndarray,
    W_probe: int, H_probe: int, W_camera: int, H_camera: int,
    axis: int, K_value: float, rng: np.random.Generator,
    n_samples: int = SAMPLES_PER_FRAME,
) -> dict[str, np.ndarray] | None:
    """Sample-first per-pixel (K1, K2, K3, r, dr) extraction.

    Coordinates: r is normalized to camera half-width (W_camera/2), centered
    on probe center (W_probe/2). For 1× (no over-scan), W_probe == W_camera
    so this reduces to traditional [-1, +1] normalization. For 1.5× over-scan
    (W_probe = 1.5 × W_camera), R/G ∈ [0, 1] of probe maps to camera-normalized
    [-1.5, +1.5]; output pixels still cover the same range since render = probe.
    """
    H, W = R.shape
    if (H, W) != (H_probe, W_probe):
        raise ValueError(f"R/G shape {R.shape} ≠ probe {(H_probe, W_probe)}")

    # Probe-centered output coords, normalized by CAMERA half-width
    cx = W_probe / 2.0
    cy = H_probe / 2.0
    half_w = W_camera / 2.0
    # ... rest of function uses cx/cy/half_w as before ...
```

把现有 `cx = W / 2.0`, `cy = H / 2.0`, `half_w = W / 2.0` 三行替换成上面 (注意 cx/cy 仍是 probe 中心, half_w 改成 camera/2).

- [ ] **Step 5: 改 main 里 compute_displacements 调用 (line 235 附近)**

```python
result = compute_displacements(
    R, G,
    W_probe, H_probe, W_camera, H_camera,
    axis, K_value, rng, args.samples_per_frame,
)
```

- [ ] **Step 6: 改 main 里 print 用 W_camera 计算物理像素覆盖**

```python
print(f"  {exr_path.name}: axis K{axis}={K_value:+.3f}, sampled {n}/{W_probe * H_probe} pixels "
      f"(r ∈ [{r_lo:.3f}, {r_hi:.3f}], dr ∈ [{dr_lo:+.4f}, {dr_hi:+.4f}])")
```

(就把 `W * H` 改成 `W_probe * H_probe`)

- [ ] **Step 7: 跑回归 — 用现有 4K (no over-scan) 数据 (existing 51 帧 K1 sweep)**

```bash
.venv/bin/python analyze_renders.py \
    --input-dir validation_results/k1_sweep \
    --output /tmp/displacements_4k_regression.csv \
    --probe-truth uv_probe_truth_3840x2160.npz \
    --samples-per-frame 100000 2>&1 | tail -8
```

期望:
- `[probe] 3840x2160 camera=3840x2160 overscan=1.00x` 一行 (no over-scan)
- 产出 5M rows CSV (51 帧 × 100k samples)
- K1 values 51 个跟以前一致
- **数据应该跟 commit `8d4019d` 之前产出的 displacements_round2_k1.csv byte-for-byte 一致** (over-scan factor 1.0 时坐标公式跟旧代码等价)

回归对比命令:

```bash
diff <(head -3 /tmp/displacements_4k_regression.csv) <(head -3 /tmp/displacements_round2_k1.csv)
md5 -q /tmp/displacements_4k_regression.csv /tmp/displacements_round2_k1.csv
```

期望: head 一样 + MD5 完全一致. 如果 MD5 不一致, 检查是不是 cx/cy/half_w 公式没保持等价.

- [ ] **Step 8: Commit**

```bash
git add scripts/distortion_calibration/analyze_renders.py
git commit -m "$(cat <<'EOF'
refactor(distortion-analyze): camera-normalized 坐标支持 over-scan probe

compute_displacements 接收 probe + camera 双尺寸. cx/cy 用 probe 中心, half_w
用 camera/2 做 r 归一化. 1× (no over-scan) 时 W_probe == W_camera, 公式
退化到原来 (R*W - W/2)/(W/2) = R*2 - 1, 行为等价.

1.5× over-scan 时 W_probe=5760, W_camera=3840:
  src_x_norm = (R*5760 - 2880) / 1920 = R*3 - 1.5  (而非 R*2 - 1)
意味着 R/G ∈ [0,1] of probe 映射到 camera-normalized [-1.5, +1.5], camera
中心 [-1, +1] 是 inner 3840×2160 范围. K1>0 把源像素拉到 [-1.5, -1] / [+1, +1.5]
缓冲带也在 probe 内, 不再越界.

main 改 unpack 4-tuple, 加 over-scan factor print 行.

回归: 用现有 4K (no over-scan) 数据重跑, 输出 CSV 跟 commit 8d4019d 之前
完全一致 (MD5 match), 证明 1× 路径行为不变.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `fit_distortion_models.py` half_w 用 camera dims

**Files:**
- Modify: `scripts/distortion_calibration/fit_distortion_models.py:415-422`

- [ ] **Step 1: 改 main 里 half_w 自动**

定位 line 415-422 (auto-detect half_w 区段):

```python
    if args.half_width_px is None:
        # Auto-detect from probe metadata (matching what analyze_renders.py used)
        W, H = load_probe_meta(args.probe_truth)
        half_w = W / 2.0
        print(f"[auto] half_width_px = {half_w:.1f} (from probe {W}x{H})")
    else:
        half_w = args.half_width_px
```

改成:

```python
    if args.half_width_px is None:
        # Auto-detect from probe metadata. 用 CAMERA half-width (不是 probe), 保持
        # over-scan probe 跟 1× probe 的 fit 系数都在同一物理参考系下.
        W_probe, H_probe, W_camera, H_camera = load_probe_meta(args.probe_truth)
        half_w = W_camera / 2.0
        overscan = W_probe / W_camera
        print(f"[auto] half_width_px = {half_w:.1f} (from camera {W_camera}x{H_camera}, "
              f"probe {W_probe}x{H_probe}, overscan={overscan:.2f}x)")
    else:
        half_w = args.half_width_px
```

- [ ] **Step 2: 跑回归 — 用现有 4K 数据**

```bash
.venv/bin/python fit_distortion_models.py \
    --input /tmp/displacements_round2_k1.csv \
    --probe-truth uv_probe_truth_3840x2160.npz \
    2>&1 | head -5
```

期望:
- `[auto] half_width_px = 1920.0 (from camera 3840x2160, probe 3840x2160, overscan=1.00x)` 一行
- 后续 BIC / RMS 数字 byte-for-byte 跟 Round 2 K1 fit 历史输出一致 (因为 4K 数据 over-scan=1.0, half_w 还是 1920)

- [ ] **Step 3: 跑 over-scan probe 的 sanity (此时 over-scan EXR 还没渲, 但 npz 已生成)**

```bash
.venv/bin/python -c "
from _exr import load_probe_meta, PROBE_OVERSCAN_TRUTH
pw, ph, cw, ch = load_probe_meta(PROBE_OVERSCAN_TRUTH)
print(f'over-scan probe: {pw}x{ph}, camera: {cw}x{ch}, half_w_camera = {cw/2:.1f}')
"
```

期望: `over-scan probe: 5760x3240, camera: 3840x2160, half_w_camera = 1920.0` (跟 4K 一样, 因为 camera 没变)

- [ ] **Step 4: Commit**

```bash
git add scripts/distortion_calibration/fit_distortion_models.py
git commit -m "$(cat <<'EOF'
refactor(distortion-fit): half_w 用 camera 尺寸 (不是 probe)

auto-detect half_w 改成从 camera_width 取 (= load_probe_meta 4-tuple 第 3 项),
不是从 probe_width. 1× probe (no over-scan) 时 camera_w == probe_w, 行为不变.
1.5× over-scan probe 时 probe_w=5760 但 camera_w=3840, half_w=1920 跟 4K 时一致,
保证 fit 系数 (a, b, c, d, e, f) 跟相机参考系绑定, over-scan 仅扩源数据有效区
不影响系数物理意义.

打印增加 overscan factor 标注便于诊断.

Round 2 K1 4K 数据回归: half_w=1920 跟之前一致, BIC / RMS 输出 byte-for-byte
不变.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 单元测试 over-scan 坐标换算

**Files:**
- Create temporary: `scripts/distortion_calibration/_test_overscan_coords.py` (Step 5 末删, 不入仓)

- [ ] **Step 1: 写测试**

新建 `scripts/distortion_calibration/_test_overscan_coords.py`:

```python
"""Verify analyze_renders.compute_displacements 在 1× 和 1.5× over-scan 下的
坐标换算公式. 1× 路径必须跟 commit 8d4019d 之前等价 (R*2 - 1 形式),
1.5× 路径 R/G ∈ [0,1] → camera-normalized [-1.5, +1.5].
"""
from __future__ import annotations

import numpy as np

from analyze_renders import compute_displacements


def make_identity_RG(W, H):
    """Identity probe: R=(x+0.5)/W, G=(y+0.5)/H, B=0."""
    xs = (np.arange(W, dtype=np.float32) + 0.5) / W
    ys = (np.arange(H, dtype=np.float32) + 0.5) / H
    R = np.broadcast_to(xs, (H, W)).copy()
    G = np.broadcast_to(ys[:, None], (H, W)).copy()
    return R, G


def assert_close(actual, expected, label, tol=1e-6):
    if abs(actual - expected) > tol:
        raise AssertionError(f"{label}: got {actual} expected {expected} (delta {actual-expected})")
    print(f"  ✓ {label}: {actual:+.6f}")


# ============================================================
# Test 1: 1× probe (no over-scan), 探针中心像素 → r=0
# ============================================================
W, H = 3840, 2160
R, G = make_identity_RG(W, H)
rng = np.random.default_rng(42)
res = compute_displacements(
    R, G, W, H, W, H,  # probe = camera (1×)
    axis=1, K_value=0.1, rng=rng, n_samples=100,
)
# 找最接近中心的 sample
idx_center = np.argmin(res["r_anchor"])
r_anchor_center = res["r_anchor"][idx_center]
print("=== 1× probe (3840×2160 = 3840×2160) identity probe ===")
assert_close(r_anchor_center, 0.0, "r_anchor at center sample", tol=2e-3)
# 中心像素的 src_x_norm 应当 ≈ 0 (probe 中心 R=0.5 → R*2-1=0)
src_x_center = res["src_x_norm"][idx_center]
assert_close(src_x_center, 0.0, "src_x_norm at center sample", tol=2e-3)


# ============================================================
# Test 2: 1.5× over-scan, 探针中心像素 → r=0 (不论 over-scan)
# ============================================================
W_probe, H_probe = 5760, 3240
W_camera, H_camera = 3840, 2160
R, G = make_identity_RG(W_probe, H_probe)
rng = np.random.default_rng(42)
res = compute_displacements(
    R, G, W_probe, H_probe, W_camera, H_camera,
    axis=1, K_value=0.1, rng=rng, n_samples=200,
)
# 中心像素 (probe 几何中心) 的 r 应当 ≈ 0
idx_center = np.argmin(res["r_anchor"])
print()
print("=== 1.5× over-scan probe (5760×3240, camera 3840×2160) identity probe ===")
assert_close(res["r_anchor"][idx_center], 0.0, "r_anchor at center", tol=2e-3)
assert_close(res["src_x_norm"][idx_center], 0.0, "src_x_norm at center", tol=2e-3)


# ============================================================
# Test 3: 1.5× over-scan, probe 右上角像素 → r ≈ 1.5 * sqrt(1 + (9/16)²)
# ============================================================
# 单独构造一帧把右上角 (x=W-1, y=0) 提取
xs_corner = np.array([W_probe - 1])
ys_corner = np.array([0])
R_corner = (xs_corner + 0.5) / W_probe  # ≈ 0.99991
G_corner = (ys_corner + 0.5) / H_probe  # ≈ 0.000154
# 期望 src_x_norm = R*3 - 1.5 ≈ 0.99991*3 - 1.5 = 1.4997
expected_src_x = R_corner[0] * 3 - 1.5
expected_src_y = G_corner[0] * 3 - 1.5  # *3 because 3240 = 3*1080? wait 3240/1080 = 3 也对, S 同 X
# 实际上 over-scan factor 是各方向独立, 但我们 1.5× 同时应用 X/Y, 所以 H_probe/H_camera = 3240/2160 = 1.5 一致
print()
print("=== 1.5× over-scan, 极右上像素手动验证 ===")
print(f"  R = {R_corner[0]:.6f}, G = {G_corner[0]:.6f}")
print(f"  expected src_x_norm = R*3 - 1.5 = {expected_src_x:+.6f}")
print(f"  expected src_y_norm = G*3 - 1.5 = {expected_src_y:+.6f}")
# manually compute via the formula in compute_displacements
cx = W_probe / 2.0  # 2880
cy = H_probe / 2.0  # 1620
half_w = W_camera / 2.0  # 1920
src_x_norm = (R_corner[0] * W_probe - cx) / half_w  # (0.99991*5760 - 2880)/1920
src_y_norm = (G_corner[0] * H_probe - cy) / half_w  # (0.000154*3240 - 1620)/1920
print(f"  computed src_x_norm = {src_x_norm:+.6f}")
print(f"  computed src_y_norm = {src_y_norm:+.6f}")
assert_close(src_x_norm, expected_src_x, "right-edge src_x_norm", tol=1e-5)
assert_close(src_y_norm, expected_src_y, "top-edge src_y_norm", tol=1e-5)


# ============================================================
# Test 4: 1× and 1.5× 在中心区给出相同 r_anchor (camera-normalized invariant)
# ============================================================
print()
print("=== 1× vs 1.5× r_anchor invariant (识 camera-normalized 是否一致) ===")
# 1× probe 第 (W/4, H/4) 像素 R = 0.25, src_x_norm = 0.25*2 - 1 = -0.5
# 1.5× probe 同 camera 位置 (x=960, y=540 from over-scan top-left, 即 camera 左上)
# 在 1.5× probe 中 R = 960.5/5760 = 0.16675, src_x_norm = 0.16675*3 - 1.5 = -1.0
# 对应 1× 中 camera (x=0, y=0): R = 0.5/3840 ≈ 0.000130, src_x_norm = 0.000130*2 - 1 ≈ -1.0
# 两个其实都是 camera 左上, src_x_norm 都应当 ≈ -1.0
# (这测试主要是确认 over-scan 不破坏 camera 内部坐标语义)

# 1× 在 camera 左上 (px=0, py=0)
R_1x_topleft = 0.5 / 3840
src_x_1x = (R_1x_topleft * 3840 - 1920) / 1920
# 1.5× 在 camera 左上 (probe px=960, probe py=540)
R_15x_camera_topleft = (960 + 0.5) / 5760
src_x_15x = (R_15x_camera_topleft * 5760 - 2880) / 1920
print(f"  1× camera 左上 src_x_norm = {src_x_1x:+.6f}")
print(f"  1.5× camera 左上 src_x_norm = {src_x_15x:+.6f}")
assert_close(src_x_15x, src_x_1x, "1.5× camera 左上 ≡ 1× camera 左上", tol=1e-5)

print()
print("ALL OVER-SCAN COORD TESTS PASSED")
```

- [ ] **Step 2: 跑测试**

```bash
.venv/bin/python _test_overscan_coords.py
```

期望: 全 ✓ 通过, 末尾 "ALL OVER-SCAN COORD TESTS PASSED".

如果某个 assert fail, 检查 compute_displacements 公式是不是 cx 用了 probe 中心 + half_w 用了 camera 半宽.

- [ ] **Step 3: 删测试 (调试用, 不入仓)**

```bash
rm _test_overscan_coords.py
```

- [ ] **Step 4: 不 commit (无文件改动)**

---

## Task 6: 等数据来 — 用真实 over-scan 51 帧跑 fit (BLOCKED)

**前置条件:** Disguise 工程师按 USER_INSTRUCTIONS over-scan 指引重渲了 51 帧 5760×3240 EXR, 上传到 `validation_results/k1_sweep_overscan/` 或 `/tmp/disguise_renders_round2_overscan/`.

**Files:**
- Create temporary: `/tmp/displacements_round2_k1_overscan.csv` (诊断输出, 不入仓)
- Create temporary: `/tmp/round2_overscan_fit.log` (诊断输出, 不入仓)

- [ ] **Step 1: smoke 检查 over-scan EXR 格式**

```bash
.venv/bin/python -c "
import os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
import cv2, numpy as np
from pathlib import Path
base = Path('validation_results/k1_sweep_overscan')  # 或工程师上传的实际路径
for k in ['p0p02', 'p0p10', 'p0p50', 'n0p50', 'zero']:
    p = base / f'disguise_K1_{k}.exr'
    if not p.exists():
        print(f'MISSING: {p}')
        continue
    img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    print(f'{p.name}: shape={img.shape}, dtype={img.dtype}, R range=[{img[...,2].min():.4f}, {img[...,2].max():.4f}]')
"
```

期望: 所有 5 张帧 shape=(3240, 5760, 3 or 4), dtype=float32, R range ≈ [0, 1].

如果 shape 不是 (3240, 5760, ...) → Disguise 工程师渲错分辨率, STOP, 让他们重渲.

- [ ] **Step 2: 跑 analyze_renders 全 51 帧**

```bash
.venv/bin/python analyze_renders.py \
    --input-dir validation_results/k1_sweep_overscan \
    --output /tmp/displacements_round2_k1_overscan.csv \
    --samples-per-frame 100000 \
    --probe-truth uv_probe_truth_5760x3240.npz \
    2>&1 | tail -10
```

期望:
- `[probe] 5760x3240 camera=3840x2160 overscan=1.50x` 一行
- 51 帧 anchor sanity 通过 (max deviation < 0.01)
- 5,000,000 rows 写入 CSV
- K1 values 51 个

如果 anchor sanity 任一帧 max > 0.01 → Disguise 那边 LED gamma / color transform 出问题, 让工程师排查再继续.

- [ ] **Step 3: 跑 fit 14 候选**

```bash
.venv/bin/python fit_distortion_models.py \
    --input /tmp/displacements_round2_k1_overscan.csv \
    --probe-truth uv_probe_truth_5760x3240.npz \
    --trim-pct 5 \
    2>&1 | tee /tmp/round2_overscan_fit.log | tail -50
```

期望:
- `[auto] half_width_px = 1920.0 (from camera 3840x2160, probe 5760x3240, overscan=1.50x)`
- 14 候选 fit, 无 FAIL
- **K1+ 帧 max residual 应回到 K1- side 同水平 (~3 px @ 4K)**, 不再是 76-97 px
- M_RAT6 / M_RAT8 / M_BCUD_FULL BIC 跟 RMS 显著改善
- BIC 排序: 期望 M_RAT6 或 M_RAT8 BIC 最优, 系数收敛到合理量级 (-3.18, +7.24, +5.12 等 Round 1 同量级)

- [ ] **Step 4: 验证 K1+ outlier 已修复**

```bash
grep "K1=+" /tmp/round2_overscan_fit.log | head -30
grep "K1=-" /tmp/round2_overscan_fit.log | head -30
```

期望: K1+ 25 帧 max 跟 K1- 25 帧 max **同量级** (前者 ~3 px, 后者 ~3 px). 之前 K1+ max 76-97 px, 现在应当退到 1-5 px 范围.

如果 K1+ max 仍 > 10 px → over-scan 1.5× 不够, 需要更大 over-scan (2×) 或排查别的 Disguise 问题.

- [ ] **Step 5: 不 commit (诊断输出不入仓)**

---

## Task 7: 把 BIC-best 系数 + production deploy + Tier 1/2 验证

**前置条件:** Task 6 完成, BIC-best 系数 + RMS 实测就绪.

This task 流程跟原 plan `2026-04-29-distortion-fit-harness-round2.md` Tasks 6-12 一致:
- Task 6 of 那 plan: distortion_math.py 系数填入
- Task 9: lanPC Tier 1 deploy + verify
- Task 10: Tier 2 EXR-based displacement field validation
- Task 11: UE 4K render + Lanczos compare
- Task 12: docs 更新

**这些 task 在 over-scan 数据来后, 走原 plan 即可** (over-scan 不改动 distortion_math.py 系数填入逻辑, 只是数据更干净, 系数会更准).

---

## Self-Review

### 1. Spec coverage

- ✅ 1.5× over-scan probe 生成 (Task 1)
- ✅ _exr.py 4-tuple load_probe_meta (Task 2)
- ✅ analyze_renders.py camera-normalized 坐标 (Task 3)
- ✅ fit_distortion_models.py half_w 用 camera (Task 4)
- ✅ 单元测试覆盖 1× / 1.5× 坐标换算 (Task 5)
- ✅ 等数据 + over-scan fit (Task 6)
- ✅ 把 over-scan fit 接到现有 deploy 流程 (Task 7, 复用原 plan)

### 2. Placeholder scan

无 TBD / TODO / "implement later". Task 6 的 BIC-best 系数填入是真实数据驱动的, 写明等数据.

### 3. Type / 函数名一致性

- `load_probe_meta` 在 _exr.py 改成 4-tuple, analyze_renders.py + fit_distortion_models.py 同步改 unpack
- `compute_displacements` 签名扩到 `(R, G, W_probe, H_probe, W_camera, H_camera, axis, K_value, rng, n_samples)`, main 里调用对齐
- `cx` / `cy` 用 probe dims, `half_w` 用 camera dim, 在 compute_displacements 里命名清晰
- `PROBE_OVERSCAN` / `PROBE_OVERSCAN_TRUTH` 加到 _exr.py, analyze_renders 默认 fallback 顺序更新

无类型不一致.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-30-distortion-overscan-pipeline.md`.**

**两种执行方式:**

**1. Subagent-Driven (推荐)** - controller 每个 Task dispatch fresh subagent, 任务间 spec + code quality 双 review, 快速迭代

**2. Inline Execution** - 当前 session executing-plans skill, 批量执行 + checkpoint review

**Tasks 1-5 是代码改造, 不依赖 Disguise 数据, 可以独立做完.**
**Task 6 BLOCKED 等 Disguise 工程师重渲 51 帧 5760×3240 over-scan EXR.**
**Task 7 复用原 plan 2026-04-29 §Task 6-12 流程, 等 Task 6 完成后开始.**
