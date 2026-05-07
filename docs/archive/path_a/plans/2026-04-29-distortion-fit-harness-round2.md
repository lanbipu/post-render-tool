# Distortion Fit Harness Round 2 Upgrade · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Round 2 高密度 4K 数据 (153 帧 K1/K2/K3 sweep) 来了之后, 升级 fit harness + distortion_math, 把 K=0.5 测试残差从 max 3.2 px 推到 max ~0.5-1 px (VFX 旗舰/影视后期级), 不破坏 PostRenderTool 用户接口.

**Architecture:** 数据流仍是 EXR → analyze_renders → displacements.csv → fit_distortion_models → distortion_math.py 系数 → LensFile + LensComponent BCUD shader → MRQ render. 升级点: (1) 三轴命名识别 + 4K 支持; (2) 加 M_RAT8 / M_RAT_K1K2K3_CROSS / M_BCUD_FULL 三个新候选公式, 联合 fit; (3) distortion_math.py 用全新 BCUD 8 系数 + 真实 P1/P2 切向项 (不再 P1=P2=0); (4) UE MRQ 渲 4K + Mac Lanczos 下采 1080p 提供 sub-pixel 精度.

**Tech Stack:**
- 已就位: numpy 2.4 / scipy 1.17 / cv2 4.13 / Mac venv `scripts/distortion_calibration/.venv/`
- 已就位 4K probe: `uv_probe_3840x2160.exr` + `uv_probe_truth_3840x2160.npz` (commit `98eb839`)
- 已就位 USER_INSTRUCTIONS: 153 帧渲染清单 (commit `51f9167`)
- 待用户提供: 153 帧 4K EXR (~6-8 GB) 上传到 Mac 任意目录

**前置条件 (本计划开始执行前必须满足):**
- ✅ 4K UV probe 已生成
- ✅ USER_INSTRUCTIONS 已更新, 渲染清单完整
- ⏳ 用户/Disguise 工程师已提交 153 帧 4K EXR → 假设上传到 `/tmp/disguise_renders_round2/`
  - `k1_sweep/` — 51 帧 disguise_K1_*.exr
  - `k2_sweep/` — 51 帧 disguise_K2_*.exr
  - `k3_sweep/` — 51 帧 disguise_K3_*.exr
- 如果数据未到, Task 7 (跑 fit) 会因为缺数据 BLOCKED, 其他 task (1-6, 工具升级) 仍可在等数据时做

---

## 文件结构 (改动一览)

| 路径 | 改动类型 | 用途 |
|---|---|---|
| `scripts/distortion_calibration/_exr.py` | 修改 | 参数化 probe path, 支持 1080p + 4K |
| `scripts/distortion_calibration/analyze_renders.py` | 修改 | 三轴命名识别, 输出 K1/K2/K3 三列, dense sampling 参数化 |
| `scripts/distortion_calibration/fit_distortion_models.py` | 修改 | 三列输入, 加 M_RAT8 / M_RAT_K1K2K3_CROSS / M_BCUD_FULL 候选, half_w 从 probe 自动 |
| `Content/Python/post_render_tool/distortion_math.py` | 修改 | 用新 BIC-best 系数 + 真实 P1/P2 切向项 + 联合 K1K2K3 输出 |
| `Content/Python/post_render_tool/tests/test_distortion_rational.py` | **删除** | 旧 M_RAT6 单变量测试 |
| `Content/Python/post_render_tool/tests/test_distortion_v2.py` | **新建** | 联合 K1K2K3 + tangential 单元测试 |
| `Content/Python/post_render_tool/tests/test_c_distortion_packing.py` | 修改 | 加 P1/P2 非零情况测试 |
| `docs/K1-implementation.md` | 修改 | 加 §10 Round 2 升级章节 |
| `docs/distortion-precision-analysis.md` | 修改 | §6.2 Round 2 实测残差填入 |
| `scripts/distortion_calibration/_validate_tier2_round2.py` | **新建** | 用 4K EXR 直接做 displacement-field diff (32-bit float 精度) |

---

## Task 1: `_exr.py` 参数化 probe path

**Files:**
- Modify: `scripts/distortion_calibration/_exr.py:18-24`

- [ ] **Step 1: Read 现状**

```bash
sed -n '17,25p' scripts/distortion_calibration/_exr.py
```

应看到硬编码 `PROBE_EXR = HERE / "uv_probe_1920x1080.exr"` 和 `load_probe_meta()` 单一路径.

- [ ] **Step 2: 改成参数化**

完整替换 `_exr.py` 第 17-24 行:

```python
HERE = Path(__file__).resolve().parent

# Round 1 (1080p, 11 帧 K1 sweep) 和 Round 2 (4K, 153 帧 K1/K2/K3 sweep) 共存.
# 默认查找顺序: 4K 优先 → 1080p fallback. 跑分析脚本时通过 --probe 显式指定.
PROBE_4K = HERE / "uv_probe_3840x2160.exr"
PROBE_4K_TRUTH = HERE / "uv_probe_truth_3840x2160.npz"
PROBE_1080P = HERE / "uv_probe_1920x1080.exr"
PROBE_1080P_TRUTH = HERE / "uv_probe_truth_1920x1080.npz"
# 兼容旧脚本 (commit 5311d4f 以前)
PROBE_LEGACY_TRUTH = HERE / "uv_probe_truth.npz"


def load_probe_meta(truth_path: Path | None = None) -> tuple[int, int]:
    """Returns (width, height) from probe truth npz.

    If truth_path is None, tries 4K first, then 1080p, then legacy.
    """
    if truth_path is None:
        for cand in (PROBE_4K_TRUTH, PROBE_1080P_TRUTH, PROBE_LEGACY_TRUTH):
            if cand.exists():
                truth_path = cand
                break
        if truth_path is None:
            raise FileNotFoundError("no probe truth npz found")
    truth = np.load(truth_path, allow_pickle=True)
    return int(truth["width"]), int(truth["height"])
```

注: `PROBE_EXR` 这个全局名字保留不动 (旧 `_self_test_*` 脚本可能引用), 加成 alias 兼容:

```python
PROBE_EXR = PROBE_1080P  # alias for legacy scripts
PROBE_TRUTH_NPZ = PROBE_1080P_TRUTH  # alias
```

把 alias 加在 `load_probe_meta` 定义之后.

- [ ] **Step 3: 跑现有 self-test 确认兼容**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python _self_test_truth.py 2>&1 | tail -10
```

期望: 旧 1080p self-test 仍 pass.

- [ ] **Step 4: 验证新 4K load_probe_meta**

```bash
.venv/bin/python -c "
from _exr import load_probe_meta, PROBE_4K_TRUTH
w, h = load_probe_meta(PROBE_4K_TRUTH)
print(f'4K: {w}x{h}')
w, h = load_probe_meta()  # auto detect
print(f'auto: {w}x{h}')
"
```

期望: `4K: 3840x2160`, `auto: 3840x2160` (4K 优先).

- [ ] **Step 5: Commit**

```bash
git add scripts/distortion_calibration/_exr.py
git commit -m "$(cat <<'EOF'
refactor(distortion-exr): _exr.py probe path 参数化, 同时支持 1080p 和 4K

加 PROBE_4K / PROBE_1080P / PROBE_LEGACY_TRUTH 常量, load_probe_meta
接受可选 truth_path 参数, 不指定时按 4K → 1080p → legacy 顺序自动找.
保留 PROBE_EXR / PROBE_TRUTH_NPZ alias 兼容旧 _self_test_* 脚本.

Round 2 4K 数据消费需要这个升级.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `analyze_renders.py` 三轴命名识别 + K1/K2/K3 三列输出

**Files:**
- Modify: `scripts/distortion_calibration/analyze_renders.py`

- [ ] **Step 1: 改 _K_PATTERN regex 支持 disguise_K[1-3]_***

定位现有 line 67-69:

```python
_K_PATTERN = re.compile(
    r"^disguise_K_(?:(zero)|([pn])(\d+(?:p\d+)?))$", re.IGNORECASE,
)
```

替换为:

```python
# 支持 Round 1 (单轴: disguise_K_zero / disguise_K_p0p1) 和
# Round 2 (三轴: disguise_K1_zero / disguise_K2_p0p02 / disguise_K3_n0p50).
# 命名约定: 'p' = positive, 'n' = negative, 'p' (after digit) = decimal point.
_K_PATTERN = re.compile(
    r"^disguise_K(?P<axis>[123]?)_(?:(?P<zero>zero)|(?P<sign>[pn])(?P<value>\d+(?:p\d+)?))$",
    re.IGNORECASE,
)
```

- [ ] **Step 2: 改 parse_k_value 返回 (axis, value)**

替换 line 72-78:

```python
def parse_k_value(stem: str) -> tuple[int, float]:
    """Returns (axis, value). axis ∈ {1, 2, 3}; Round 1 命名无 axis 数字, 默认 axis=1."""
    m = _K_PATTERN.match(stem)
    if not m:
        raise ValueError(f"cannot parse K from filename stem: {stem}")
    axis_str = m.group("axis") or "1"  # Round 1 命名缺 axis 数字, 默认 K1
    axis = int(axis_str)
    if m.group("zero"):
        return axis, 0.0
    sign = +1.0 if m.group("sign").lower() == "p" else -1.0
    return axis, sign * float(m.group("value").replace("p", "."))
```

- [ ] **Step 3: 写测试 (TDD)**

新建 `scripts/distortion_calibration/_test_parse_k.py`:

```python
"""Quick tests for analyze_renders.parse_k_value tri-axis support."""
from analyze_renders import parse_k_value


def assert_eq(actual, expected, label):
    assert actual == expected, f"{label}: got {actual}, want {expected}"
    print(f"  ✓ {label}: {actual}")


# Round 1 (legacy single-axis K1)
assert_eq(parse_k_value("disguise_K_zero"), (1, 0.0), "legacy zero")
assert_eq(parse_k_value("disguise_K_p0p1"), (1, +0.1), "legacy p0p1")
assert_eq(parse_k_value("disguise_K_n0p5"), (1, -0.5), "legacy n0p5")

# Round 2 K1 axis
assert_eq(parse_k_value("disguise_K1_zero"), (1, 0.0), "K1 zero")
assert_eq(parse_k_value("disguise_K1_p0p02"), (1, +0.02), "K1 p0p02")
assert_eq(parse_k_value("disguise_K1_n0p50"), (1, -0.50), "K1 n0p50")

# Round 2 K2 axis
assert_eq(parse_k_value("disguise_K2_zero"), (2, 0.0), "K2 zero")
assert_eq(parse_k_value("disguise_K2_p0p20"), (2, +0.20), "K2 p0p20")

# Round 2 K3 axis
assert_eq(parse_k_value("disguise_K3_n0p36"), (3, -0.36), "K3 n0p36")

print("all parse_k_value tests passed")
```

- [ ] **Step 4: 跑测试**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python _test_parse_k.py
```

期望: 全部 ✓ 通过.

- [ ] **Step 5: 改 compute_displacements 输出三列 K**

替换 line 81-127 的 `compute_displacements` 函数:

```python
def compute_displacements(
    R: np.ndarray, G: np.ndarray, axis: int, K_value: float, rng: np.random.Generator,
    n_samples: int = SAMPLES_PER_FRAME,
) -> dict[str, np.ndarray] | None:
    """Sample-first per-pixel (K1, K2, K3, r, dr) extraction.

    Builds the validity mask on R/G only, draws n_samples indices,
    then computes the 8 normalized scalars on the sample. Avoids the
    full-resolution np.indices + r_dist + r_undist arrays that would peak
    at ~120 MB for a 1920x1080 float64 frame (4K = 4× larger, MUST sample).

    Parameters
    ----------
    axis: 1, 2, or 3 — which K axis is non-zero in this frame.
    K_value: the non-zero K coefficient for that axis (other two = 0).
    n_samples: per-frame random subsample size (default SAMPLES_PER_FRAME = 30000).
    """
    H, W = R.shape
    cx = W / 2.0
    cy = H / 2.0
    half_w = W / 2.0

    valid = (
        (R > VALID_UV_MIN) & (R < VALID_UV_MAX) &
        (G > VALID_UV_MIN) & (G < VALID_UV_MAX)
    )
    valid_idx = np.flatnonzero(valid.ravel())
    if len(valid_idx) == 0:
        return None

    n_sample = min(n_samples, len(valid_idx))
    sample = rng.choice(valid_idx, size=n_sample, replace=False)
    ys, xs = np.unravel_index(sample, (H, W))
    R_s = R.ravel()[sample]
    G_s = G.ravel()[sample]

    out_x_norm = (xs.astype(np.float64) + 0.5 - cx) / half_w
    out_y_norm = (ys.astype(np.float64) + 0.5 - cy) / half_w
    src_x_norm = (R_s * W - cx) / half_w
    src_y_norm = (G_s * H - cy) / half_w
    r_dist = np.hypot(out_x_norm, out_y_norm)
    r_undist = np.hypot(src_x_norm, src_y_norm)

    K1 = np.full(n_sample, K_value if axis == 1 else 0.0)
    K2 = np.full(n_sample, K_value if axis == 2 else 0.0)
    K3 = np.full(n_sample, K_value if axis == 3 else 0.0)

    return {
        "K1": K1, "K2": K2, "K3": K3,
        "pixel_id": sample.astype(np.int32),
        "src_x_norm": src_x_norm,
        "src_y_norm": src_y_norm,
        "out_x_norm": out_x_norm,
        "out_y_norm": out_y_norm,
        "r_anchor": r_undist,
        "r_dist": r_dist,
        "dr": r_dist - r_undist,
    }
```

- [ ] **Step 6: 改 CSV_FIELDS**

替换 line 53-57:

```python
CSV_FIELDS = (
    "K1", "K2", "K3", "pixel_id",
    "src_x_norm", "src_y_norm", "out_x_norm", "out_y_norm",
    "r_anchor", "r_dist", "dr",
)
```

- [ ] **Step 7: 改 main() 处理三组 sweep + 三组 sanity**

替换 line 149-211 的 `main()` 函数:

```python
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input-dir", type=Path, default=Path("/tmp/disguise_renders_round2"),
        help="directory of disguise_K[1-3]_*.exr renders. "
             "Round 1 layout (flat dir of disguise_K_*.exr) also supported.",
    )
    ap.add_argument(
        "--output", type=Path, default=HERE / "displacements.csv",
        help="output CSV path",
    )
    ap.add_argument(
        "--samples-per-frame", type=int, default=SAMPLES_PER_FRAME,
        help=f"per-frame random subsample size (default {SAMPLES_PER_FRAME})",
    )
    ap.add_argument(
        "--probe-truth", type=Path, default=None,
        help="probe truth npz (auto-detect 4K → 1080p → legacy if omitted)",
    )
    ap.add_argument(
        "--seed", type=int, default=42,
        help="reproducible per-frame subsample",
    )
    args = ap.parse_args()

    if not args.input_dir.is_dir():
        raise SystemExit(f"input dir not found: {args.input_dir}")

    W, H = load_probe_meta(args.probe_truth)
    rng = np.random.default_rng(args.seed)

    # 收集所有 disguise_K*_*.exr (递归 + flat 都支持)
    exr_files = list(args.input_dir.rglob("disguise_K*.exr"))
    if not exr_files:
        raise SystemExit(f"no disguise_K*.exr in {args.input_dir}")

    # Anchor sanity check for each axis (zero frame)
    for axis_name in ("K1", "K2", "K3", "K"):  # K = legacy Round 1
        for cand in args.input_dir.rglob(f"disguise_{axis_name}_zero.exr"):
            anchor_sanity_check(cand, W, H)
            break  # 一组只查一张

    batches: list[dict[str, np.ndarray]] = []
    seen_axes: dict[int, list[float]] = {1: [], 2: [], 3: []}
    for exr_path in sorted(exr_files):
        try:
            axis, K_value = parse_k_value(exr_path.stem)
        except ValueError as exc:
            print(f"  [skip] {exr_path.name}: {exc}")
            continue
        seen_axes[axis].append(K_value)
        if abs(K_value) < 1e-9:
            continue
        R, G = read_uvprobe_exr(exr_path)
        if R.shape != (H, W):
            print(f"  [skip] {exr_path.name}: shape {R.shape} ≠ probe {(H, W)}")
            continue
        result = compute_displacements(R, G, axis, K_value, rng, args.samples_per_frame)
        if result is None:
            print(f"  [warn] {exr_path.name}: no valid pixels (whole frame masked?)")
            continue
        batches.append(result)
        n = len(result["K1"])
        r_lo, r_hi = float(result["r_anchor"].min()), float(result["r_anchor"].max())
        dr_lo, dr_hi = float(result["dr"].min()), float(result["dr"].max())
        print(f"  {exr_path.name}: axis K{axis}={K_value:+.3f}, sampled {n}/{W * H} pixels "
              f"(r ∈ [{r_lo:.3f}, {r_hi:.3f}], dr ∈ [{dr_lo:+.4f}, {dr_hi:+.4f}])")

    if not batches:
        raise SystemExit("no rows emitted — check input directory and EXR validity")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    all_rows = np.concatenate(
        [np.column_stack([b[name] for name in CSV_FIELDS]) for b in batches]
    )
    np.savetxt(
        args.output, all_rows,
        delimiter=",", fmt="%.8g",
        header=",".join(CSV_FIELDS), comments="",
    )
    print(f"wrote {all_rows.shape[0]} rows to {args.output}")
    for axis in (1, 2, 3):
        if seen_axes[axis]:
            ks = sorted(set(seen_axes[axis]))
            print(f"  K{axis} values ({len(ks)}): {ks[:5]}...{ks[-2:]}" if len(ks) > 7 else f"  K{axis} values: {ks}")
```

- [ ] **Step 8: 跑回归测试 — 用现有 Round 1 数据 (11 帧 1080p)**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python analyze_renders.py --input-dir /tmp/disguise_renders --output /tmp/displacements_legacy_check.csv --probe-truth uv_probe_truth_1920x1080.npz 2>&1 | tail -15
```

期望: 输出 11 行 K1 sweep + 0 行 K2/K3 (legacy 数据集只有 K1). 跟之前 11 帧 fit residual 比对应该差不多 (新 CSV 有三列 K1/K2/K3, K1 列同 legacy K, K2/K3 = 0).

- [ ] **Step 9: 删测试文件**

```bash
rm scripts/distortion_calibration/_test_parse_k.py
```

测试脚本只是调试用, 不入仓.

- [ ] **Step 10: Commit**

```bash
git add scripts/distortion_calibration/analyze_renders.py
git commit -m "$(cat <<'EOF'
feat(distortion-analyze): 三轴命名识别 + K1/K2/K3 三列输出 + dense sampling 参数化

升级 analyze_renders.py 支持 Round 2 高密度采集:
- _K_PATTERN regex 支持 disguise_K[123]?_(zero|p|n)\d+ 三轴命名
- parse_k_value 返回 (axis, value) tuple, 兼容 Round 1 单轴命名 (无 axis 数字 → axis=1)
- compute_displacements 输出 K1/K2/K3 三列 (非当前 axis 的两列填 0)
- CSV_FIELDS 从 9 列扩到 11 列
- main 加 --samples-per-frame 参数 (4K → 100k+ samples per frame)
- main 加 --probe-truth 参数, 默认自动 4K → 1080p
- 三组各自 anchor sanity check (K1_zero / K2_zero / K3_zero)
- 用 rglob 递归搜索, 兼容 k1_sweep/ k2_sweep/ k3_sweep/ 子目录布局

Round 1 数据回归: 11 帧 1080p 重跑产出 K1 三列 (K2/K3=0), fit 应该一致.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `fit_distortion_models.py` 升级 load_data + half_w 自动 + dense

**Files:**
- Modify: `scripts/distortion_calibration/fit_distortion_models.py`

- [ ] **Step 1: 改 load_data 读三列 K1/K2/K3**

定位 line 197-207, 替换:

```python
def load_data(
    csv_path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load (K1, K2, K3, r_anchor, dr) columns from displacements.csv.

    Skips rows where all three K are ~0 (anchor frames contribute no signal).
    """
    K1, K2, K3, r, dr = [], [], [], [], []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            k1 = float(row.get("K1", row.get("K", 0.0)))  # backward compat: legacy "K" column = K1
            k2 = float(row.get("K2", 0.0))
            k3 = float(row.get("K3", 0.0))
            if abs(k1) < 1e-9 and abs(k2) < 1e-9 and abs(k3) < 1e-9:
                continue
            K1.append(k1); K2.append(k2); K3.append(k3)
            r.append(float(row["r_anchor"]))
            dr.append(float(row["dr"]))
    return np.array(K1), np.array(K2), np.array(K3), np.array(r), np.array(dr)
```

- [ ] **Step 2: 加 half_w 从 probe metadata 自动**

在 main() 顶部 `args = ap.parse_args()` 之后, 替换原本的 `half_w = args.half_width_px`:

```python
    if args.half_width_px is None:
        # Auto-detect from probe metadata (matching what analyze_renders.py used)
        from _exr import load_probe_meta
        W, _ = load_probe_meta(args.probe_truth)
        half_w = W / 2.0
        print(f"[auto] half_width_px = {half_w:.1f} (from {W}x*)")
    else:
        half_w = args.half_width_px
```

并把 ap.add_argument 改成:

```python
    ap.add_argument(
        "--half-width-px", type=float, default=None,
        help="r-normalization constant (W/2 in pixels). Auto-detect from "
             "probe metadata if omitted. 4K=1920, 1080p=960.",
    )
    ap.add_argument(
        "--probe-truth", type=Path, default=None,
        help="probe truth npz for half-width auto-detect (default 4K → 1080p)",
    )
```

- [ ] **Step 3: 更新 fit_one 签名传 5 个数组**

替换 line 210-219:

```python
def fit_one(model: FitModel, K1: np.ndarray, K2: np.ndarray, K3: np.ndarray,
            r: np.ndarray, dr: np.ndarray):
    """Fit a single candidate. K2, K3 only consumed by joint candidates;
    legacy K1-only candidates ignore K2/K3 via partial application."""
    try:
        if model.uses_joint_K:
            popt, _ = curve_fit(model.func, (K1, K2, K3, r), dr,
                                 p0=model.p0, maxfev=20000)
        else:
            popt, _ = curve_fit(model.func, (K1, r), dr,
                                 p0=model.p0, maxfev=20000)
    except (RuntimeError, ValueError) as exc:
        return None, None, None, None, str(exc)
    if model.uses_joint_K:
        dr_pred = model.func((K1, K2, K3, r), *popt)
    else:
        dr_pred = model.func((K1, r), *popt)
    err = dr - dr_pred
    rms = float(np.sqrt(np.mean(err ** 2)))
    max_e = float(np.max(np.abs(err)))
    return popt, rms, max_e, err, None
```

- [ ] **Step 4: 在 FitModel dataclass 加 uses_joint_K 字段**

定位 FitModel dataclass 定义 (大概 line 30-40), 加字段:

```python
@dataclass
class FitModel:
    name: str
    description: str
    func: Callable
    p0: tuple[float, ...]
    param_names: tuple[str, ...]
    uses_joint_K: bool = False  # True for joint K1/K2/K3 candidates
```

- [ ] **Step 5: per_k_breakdown 改 by-axis breakdown**

替换 line 222-228:

```python
def per_k_breakdown(K1: np.ndarray, K2: np.ndarray, K3: np.ndarray,
                    err: np.ndarray) -> list[tuple[str, float, float, float]]:
    """Group residuals by (axis, K_value) and report RMS / max per group."""
    out = []
    for axis_name, K_arr in (("K1", K1), ("K2", K2), ("K3", K3)):
        # Find unique non-zero K values along this axis (other axes should be 0)
        unique_K = sorted(set(K_arr.tolist()))
        for k in unique_K:
            if abs(k) < 1e-9:
                continue
            mask = np.abs(K_arr - k) < 1e-9
            sub = err[mask]
            if len(sub) > 0:
                out.append((f"{axis_name}={k:+.3f}",
                            k, float(np.sqrt(np.mean(sub ** 2))),
                            float(np.max(np.abs(sub)))))
    return out
```

- [ ] **Step 6: robust_filter 适配三轴**

替换 line 231-253:

```python
def robust_filter(
    K1: np.ndarray, K2: np.ndarray, K3: np.ndarray, r: np.ndarray, dr: np.ndarray,
    trim_pct: float = 5.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Drop the top `trim_pct` % of points by residual under a baseline M1 fit on K1.

    M1 baseline only uses K1 axis (single-radial). Joint-K outliers detection
    needs higher-order baseline; for our use case 5% trim removes obvious
    cornerSubPix-equivalent artifacts which are independent of joint behavior.
    """
    if trim_pct <= 0:
        return K1, K2, K3, r, dr, 0
    try:
        # Use only K1-driven samples for baseline (ignore K2/K3-only frames)
        K1_only_mask = (np.abs(K2) < 1e-9) & (np.abs(K3) < 1e-9) & (np.abs(K1) > 1e-9)
        if K1_only_mask.sum() < 10:
            return K1, K2, K3, r, dr, 0
        popt, _ = curve_fit(_m1, (K1[K1_only_mask], r[K1_only_mask]),
                              dr[K1_only_mask], p0=(1.0,), maxfev=10000)
        baseline = np.zeros_like(dr)
        baseline[K1_only_mask] = _m1((K1[K1_only_mask], r[K1_only_mask]), *popt)
        resid = np.abs(dr - baseline)
        # Only filter the K1-only subset; keep all K2/K3 samples (their outliers
        # would be filtered by their own per-axis pass, but for round 2 we
        # accept this as conservative).
        cutoff = np.percentile(resid[K1_only_mask], 100.0 - trim_pct)
        keep = ~K1_only_mask | (resid <= cutoff)
        return K1[keep], K2[keep], K3[keep], r[keep], dr[keep], int((~keep).sum())
    except (RuntimeError, ValueError) as exc:
        print(f"[warn] robust_filter baseline fit failed ({exc}); skipping outlier trim")
        return K1, K2, K3, r, dr, 0
```

- [ ] **Step 7: main 串起来**

定位 main() 的 load_data + robust_filter + 循环, 替换为:

```python
    K1, K2, K3, r, dr = load_data(args.input)
    print(f"loaded {len(K1)} samples")
    print(f"  K1 range: [{K1.min():+.3f}, {K1.max():+.3f}]  non-zero: {(np.abs(K1) > 1e-9).sum()}")
    print(f"  K2 range: [{K2.min():+.3f}, {K2.max():+.3f}]  non-zero: {(np.abs(K2) > 1e-9).sum()}")
    print(f"  K3 range: [{K3.min():+.3f}, {K3.max():+.3f}]  non-zero: {(np.abs(K3) > 1e-9).sum()}")
    print(f"  r range: [{r.min():.3f}, {r.max():.3f}]  dr range: [{dr.min():+.4f}, {dr.max():+.4f}]")
    if args.trim_pct > 0:
        K1, K2, K3, r, dr, dropped = robust_filter(K1, K2, K3, r, dr, args.trim_pct)
        print(f"robust trim: dropped {dropped} outliers (top {args.trim_pct}% by M1 K1-baseline residual)")
    print()

    N = len(K1)
    results = []
    for m in MODELS:
        popt, rms, max_e, err, fail = fit_one(m, K1, K2, K3, r, dr)
        if fail is not None:
            print(f"=== {m.name}  FAIL: {fail}")
            continue
        rms_px = rms * half_w
        max_px = max_e * half_w
        k_params = len(popt)
        ssr = float(np.sum(err ** 2))
        aic = N * np.log(max(ssr / N, 1e-30)) + 2 * k_params
        bic = N * np.log(max(ssr / N, 1e-30)) + k_params * np.log(N)
        params = ", ".join(f"{name}={val:+.5f}" for name, val in zip(m.param_names, popt))
        print(f"=== {m.name}  rms={rms_px:.3f} px  max={max_px:.3f} px  "
              f"AIC={aic:.1f}  BIC={bic:.1f}  ({params})")
        print(f"    {m.description}")
        for label, _, rms_k, max_k in per_k_breakdown(K1, K2, K3, err):
            print(f"    {label}  rms={rms_k * half_w:6.3f} px  max={max_k * half_w:6.3f} px")
        results.append({
            "name": m.name, "model": m, "popt": popt,
            "rms_px": rms_px, "max_px": max_px, "aic": aic, "bic": bic,
        })
        print()
```

- [ ] **Step 8: 给现有 _m1.._m10 + M_RAT6 标记 uses_joint_K=False**

定位 MODELS tuple, 给所有现有 FitModel 注册项加 `uses_joint_K=False` 字段 (默认值, 但显式写避免后面新候选混淆):

实际只需要给 dataclass 的默认值加上 `False`, 现有项不用改 (默认就是 False).

- [ ] **Step 9: 跑回归 — 用 Round 1 11 帧数据 + legacy CSV**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python fit_distortion_models.py \
    --input /tmp/displacements_legacy_check.csv \
    --probe-truth uv_probe_truth_1920x1080.npz \
    2>&1 | tail -30
```

期望: M_RAT6 仍 BIC 最优, RMS ≈ 0.4 px, 系数跟 Round 1 (a=-3.18, b=+7.24, ...) 一致到 4 位精度.

- [ ] **Step 10: Commit**

```bash
git add scripts/distortion_calibration/fit_distortion_models.py
git commit -m "$(cat <<'EOF'
refactor(distortion-fit): load_data 三列 + per-axis breakdown + half_w 自动

升级 fit_distortion_models.py 适配 Round 2 三轴 displacements.csv 格式:
- load_data 读 K1/K2/K3 三列 (兼容 legacy 单 K 列, 旧 CSV K → K1)
- fit_one 按 model.uses_joint_K 分发: True 喂 (K1,K2,K3,r), False 喂 (K1,r)
- per_k_breakdown 按 (axis, K_value) 分组报告 RMS / max
- robust_filter 用 M1 K1-only baseline 过滤, K2/K3 样本保留
- main --half-width-px 默认 None → 从 probe metadata 自动 (4K=1920, 1080p=960)
- main --probe-truth 参数, 默认自动检测 4K → 1080p

FitModel dataclass 加 uses_joint_K 字段 (默认 False), 现有 M1..M10 / M_RAT6
保持单变量 fit 行为. Round 1 11 帧 1080p 数据回归: M_RAT6 BIC 最优, 系数
跟 Round 1 commit 8164938 fit 一致.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 加 3 个新 fit 候选 (M_RAT8 / M_RAT_K1K2K3_CROSS / M_BCUD_FULL)

**Files:**
- Modify: `scripts/distortion_calibration/fit_distortion_models.py`

- [ ] **Step 1: 加 _m_rat8 candidate (8 参数 rational, K1 only, 高阶)**

在 `_m_rat6` 函数定义之后插入:

```python
def _m_rat8(
    KR: tuple[np.ndarray, np.ndarray],
    a: float, b: float, c: float, d: float, e: float, f: float, g: float, h: float,
) -> np.ndarray:
    """8-coefficient rational, 4 阶 numerator + 4 阶 denominator (K1 only).

    r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶ + g·K⁴·r⁸)
        / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶ + h·K⁴·r⁸)

    比 M_RAT6 多两个 r⁸ 项, 在外圈 r > 0.9 处对发散控制更精确.
    BIC 应该跟 M_RAT6 接近 (Round 1 数据范围下), 但 Round 2 高密度数据可能
    显示 M_RAT8 表面下 r⁸ 项的真实贡献.
    """
    K, r = KR
    r2 = r * r; r4 = r2 * r2; r6 = r4 * r2; r8 = r4 * r4
    K2 = K * K; K3 = K2 * K; K4 = K3 * K
    num = 1.0 + a * K * r2 + b * K2 * r4 + c * K3 * r6 + g * K4 * r8
    den = 1.0 + d * K * r2 + e * K2 * r4 + f * K3 * r6 + h * K4 * r8
    return r * (num / den - 1.0)
```

- [ ] **Step 2: 加 _m_rat_kkk_cross candidate (联合 K1/K2/K3 + cross-term)**

在 `_m_rat8` 之后插入:

```python
def _m_rat_kkk_cross(
    KR: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    a1: float, a2: float, a3: float,    # numerator 单 K 系数
    b12: float, b13: float, b23: float, # numerator cross-term 系数 K1·K2 / K1·K3 / K2·K3
    d1: float, d2: float, d3: float,    # denominator 单 K 系数
) -> np.ndarray:
    """Joint K1/K2/K3 rational with cross-terms.

    r' = r · (1 + a1·K1·r² + a2·K2·r⁴ + a3·K3·r⁶
              + b12·K1·K2·r² + b13·K1·K3·r² + b23·K2·K3·r²)
        / (1 + d1·K1·r² + d2·K2·r⁴ + d3·K3·r⁶)

    9 参数 (vs M_RAT6 的 6). 显式建模 K1/K2/K3 三轴各自贡献 + 两两 cross-term.
    如果 BIC 选这个, 说明 Disguise 内部公式不是简单 OpenCV Brown-Conrady,
    而是有 K1·K2 类 cross 项耦合.
    """
    K1, K2, K3, r = KR
    r2 = r * r; r4 = r2 * r2; r6 = r4 * r2
    num = (1.0
           + a1 * K1 * r2 + a2 * K2 * r4 + a3 * K3 * r6
           + b12 * K1 * K2 * r2 + b13 * K1 * K3 * r2 + b23 * K2 * K3 * r2)
    den = 1.0 + d1 * K1 * r2 + d2 * K2 * r4 + d3 * K3 * r6
    return r * (num / den - 1.0)
```

- [ ] **Step 3: 加 _m_bcud_full candidate (UE BCUD 8 槽完整, 含 P1/P2)**

```python
def _m_bcud_full(
    KR: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    a: float, b: float, c: float, d: float, e: float, f: float,
    p1_scale: float, p2_scale: float,
) -> np.ndarray:
    """UE BrownConradyUD 8 槽完整 fit, 含 P1/P2 切向项贡献.

    Radial part 同 M_RAT6:
        r' = r · (1 + a·K1·r² + b·K1²·r⁴ + c·K1³·r⁶)
            / (1 + d·K1·r² + e·K1²·r⁴ + f·K1³·r⁶)

    切向项贡献到 dr (径向位移上的近似投影):
        dr_tangential ≈ p1_scale · K2 · r² + p2_scale · K3 · r²

    8 参数 (a-f + p1_scale + p2_scale). 假设切向贡献只在径向投影上有效项,
    本质上是 OpenCV BrownConrady 的 P1/P2 在径向距离上的小角度近似.
    """
    K1, K2, K3, r = KR
    r2 = r * r; r4 = r2 * r2; r6 = r4 * r2
    K1_sq = K1 * K1; K1_cu = K1_sq * K1
    num = 1.0 + a * K1 * r2 + b * K1_sq * r4 + c * K1_cu * r6
    den = 1.0 + d * K1 * r2 + e * K1_sq * r4 + f * K1_cu * r6
    radial = r * (num / den - 1.0)
    tangential = p1_scale * K2 * r2 + p2_scale * K3 * r2
    return radial + tangential
```

- [ ] **Step 4: 注册到 MODELS tuple**

在 MODELS 末尾 (M_RAT6 之后) 追加:

```python
    FitModel(
        name="M_RAT8",
        description="r·(1+a·K·r²+b·K²·r⁴+c·K³·r⁶+g·K⁴·r⁸)/(1+d·K·r²+...+h·K⁴·r⁸)",
        func=_m_rat8,
        p0=(-3.18, +7.24, +5.12, -2.93, +6.30, +7.51, 0.0, 0.0),
        param_names=("a", "b", "c", "d", "e", "f", "g", "h"),
        uses_joint_K=False,
    ),
    FitModel(
        name="M_RAT_K1K2K3_CROSS",
        description="联合 K1/K2/K3 rational + cross-terms (K1·K2 / K1·K3 / K2·K3)",
        func=_m_rat_kkk_cross,
        p0=(-3.18, -1.0, +1.0, 0.0, 0.0, 0.0, -2.93, -1.0, +1.0),
        param_names=("a1", "a2", "a3", "b12", "b13", "b23", "d1", "d2", "d3"),
        uses_joint_K=True,
    ),
    FitModel(
        name="M_BCUD_FULL",
        description="UE BrownConradyUD 8 槽 (radial M_RAT6 + P1/P2 切向 K2/K3 贡献)",
        func=_m_bcud_full,
        p0=(-3.18, +7.24, +5.12, -2.93, +6.30, +7.51, -1.0, +1.0),
        param_names=("a", "b", "c", "d", "e", "f", "p1_scale", "p2_scale"),
        uses_joint_K=True,
    ),
```

- [ ] **Step 5: 跑回归 — 用 Round 1 数据**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python fit_distortion_models.py \
    --input /tmp/displacements_legacy_check.csv \
    --probe-truth uv_probe_truth_1920x1080.npz \
    2>&1 | tail -50
```

期望: 14 个候选都能 fit (no FAIL). M_RAT8 / M_RAT_K1K2K3_CROSS / M_BCUD_FULL 跟 M_RAT6 RMS 接近 (Round 1 数据 K2=K3=0, joint candidates 退化, 不 break). M_RAT6 仍 BIC 最优 (因为 Round 1 数据下 joint candidates 多余参数).

- [ ] **Step 6: Commit**

```bash
git add scripts/distortion_calibration/fit_distortion_models.py
git commit -m "$(cat <<'EOF'
feat(distortion-fit): 加 M_RAT8 / M_RAT_K1K2K3_CROSS / M_BCUD_FULL 三候选

为 Round 2 高密度三轴数据准备的新 fit 候选:

- M_RAT8: 8 参数 K1-only rational, 比 M_RAT6 多 r⁸ 项. 测试外圈
  r > 0.9 是否需要更高阶项. uses_joint_K=False.

- M_RAT_K1K2K3_CROSS: 9 参数联合 fit. numerator 含 K1/K2/K3 三个单
  K 项 + 三个两两 cross-term (K1·K2, K1·K3, K2·K3). 如果 BIC 选这个,
  说明 Disguise 内部不是 OpenCV 标准模型, 三轴有耦合. uses_joint_K=True.

- M_BCUD_FULL: 8 参数, radial 部分同 M_RAT6, 加 P1/P2 切向项的径向
  贡献近似 (p1_scale·K2·r² + p2_scale·K3·r²). 直接对应 UE BCUD 8 槽
  (K1-K6 + P1, P2) 完整使用. uses_joint_K=True.

p0 初值用 Round 1 M_RAT6 fit 系数作为 warm start, 新参数 0.0 起步.

Round 1 11 帧回归: M_RAT6 仍 BIC 最优 (Round 1 K2=K3=0, joint
candidates 退化为多余参数). Round 2 153 帧来后看哪个 BIC 最优.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 跑 fit on Round 2 数据 → 选 BIC 最优

**Files:**
- Create temporary: `/tmp/round2_coeffs.txt`

**前置条件**: Round 2 数据已上传到 `/tmp/disguise_renders_round2/{k1,k2,k3}_sweep/`. 如果没有, 这个 task BLOCKED.

- [ ] **Step 1: 跑 analyze_renders 处理 153 帧 4K**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python analyze_renders.py \
    --input-dir /tmp/disguise_renders_round2 \
    --output displacements_round2.csv \
    --samples-per-frame 100000 \
    2>&1 | tail -20
```

期望: 输出 ~15M 行 CSV (153 帧 × 100k samples). K1/K2/K3 三轴 sanity check 各 max deviation < 1%.

如果 sanity 失败 (任一轴 deviation > 1%), 报告给用户, **STOP**, 让 Disguise 工程师重渲对应轴.

- [ ] **Step 2: 跑 fit_distortion_models 14 候选**

```bash
.venv/bin/python fit_distortion_models.py \
    --input displacements_round2.csv \
    --trim-pct 5 \
    2>&1 | tee /tmp/round2_fit_output.txt | tail -50
```

期望: 14 个候选 fit 结果, BIC 排序. **预期 BIC 最优是 M_RAT_K1K2K3_CROSS 或 M_BCUD_FULL** (因为 Round 2 包含 K2/K3 真实数据), 但具体看输出.

- [ ] **Step 3: 提取 BIC-best 系数到 /tmp/round2_coeffs.txt**

```bash
grep -A 1 "^=== M_" /tmp/round2_fit_output.txt | tee /tmp/round2_coeffs.txt
```

文件应包含所有 14 候选的 RMS / max / BIC / 系数. **下一个 task 要从这个文件读 BIC 最优的系数填入 distortion_math.py**.

- [ ] **Step 4: 验证 BIC-best 候选的 RMS < 0.2 px**

```bash
grep "rms=" /tmp/round2_fit_output.txt | sort -k 4 -n | head -3
```

期望 BIC-best 候选 RMS_px < 0.2 (Round 1 是 0.4, Round 2 应该接近 cornerSubPix 物理底 0.05-0.1).

如果 RMS > 0.4 (没改善), STOP 排查: 可能 Round 2 数据有 systematic issue (LED gamma 错 / centerShift 错 / ...).

- [ ] **Step 5: 不 commit**

诊断脚本/输出不入仓. 系数会在 Task 6 写到代码里 commit.

---

## Task 6: distortion_math.py 升级用新系数 + P1/P2 切向

**Files:**
- Modify: `Content/Python/post_render_tool/distortion_math.py`

**前置条件**: Task 5 完成, `/tmp/round2_coeffs.txt` 包含 BIC-best 系数. 假设 BIC-best 是 `M_BCUD_FULL` (8 参数: a, b, c, d, e, f, p1_scale, p2_scale). 如果是 `M_RAT_K1K2K3_CROSS` (9 参数), 调整下面的填充逻辑.

- [ ] **Step 1: Read 现有 distortion_math.py**

```bash
cat Content/Python/post_render_tool/distortion_math.py | head -60
```

注意 Round 1 用的是 M_RAT6_A..F 6 系数 + ue_K2/K3 = -csv_K2/K3 (legacy sign-flip).

- [ ] **Step 2: 写新版 distortion_math.py**

完整覆盖 `Content/Python/post_render_tool/distortion_math.py`:

```python
"""Disguise CSV → UE LensFile distortion-coefficient math (Round 2, BCUD full).

Pure Python (no ``unreal`` import); UE-side caller is `lens_file_builder.py`.
All unit conversions and the BCUD full mapping live here so the math
is testable outside UE Editor.

Round 2 mapping (Path A 高密度采集, commit TBD):

    UV-gradient probe 4K + 153 帧 K1/K2/K3 sweep (51 帧/轴, K ∈ ±0.5 步长 0.02),
    14 candidate fit on ~15M pixel samples. BIC-best candidate: M_BCUD_FULL
    (8 参数 BrownConradyUD full form), RMS <BIC_BEST_RMS> px ≈ noise floor.

    Radial part (跟 Round 1 M_RAT6 等价):
        r' = r · (1 + a·K1·r² + b·K1²·r⁴ + c·K1³·r⁶)
            / (1 + d·K1·r² + e·K1²·r⁴ + f·K1³·r⁶)

    Tangential part (Round 2 新增, P1/P2 切向项径向投影):
        dr_tan = p1_scale · K2 · r² + p2_scale · K3 · r²

    全部展开成 UE BrownConradyUDLensModel 8 系数 (BrownConradyUDLensModel.h:23-52):
        K1 = a·csv_K1·(2·fx)²    K4 = d·csv_K1·(2·fx)²
        K2 = b·csv_K1²·(2·fx)⁴   K5 = e·csv_K1²·(2·fx)⁴
        K3 = c·csv_K1³·(2·fx)⁶   K6 = f·csv_K1³·(2·fx)⁶
        P1 = p1_scale·csv_K2·(2·fx)²
        P2 = p2_scale·csv_K3·(2·fx)²

History:
    Round 1 (commit 0019ad3): M_RAT6 (6 参数, K1 only), legacy K2/K3 sign-flip
        透传到 P1/P2. RMS 0.4 px, K=±0.5 测试残差 max 3.2 px.
    Round 2 (commit TBD): M_BCUD_FULL (8 参数, K1+K2+K3), 切向真实 fit.
        预期 K=±0.5 测试残差 max ~0.5-1 px.
"""
from __future__ import annotations

from .csv_parser import FrameData

# ── M_RAT6 historical reference (Round 1, commit 8164938) ─────────────
# 历史记录: 这是 Round 1 时代的 M_RAT6 6 系数, K1-only rational fit.
# Round 2 用 M_BCUD_FULL 8 参数替代 (含切向项), 但 radial 6 系数是同形式.
# M_RAT6_A = -3.18050  M_RAT6_B = +7.24462  M_RAT6_C = +5.12035
# M_RAT6_D = -2.93087  M_RAT6_E = +6.30678  M_RAT6_F = +7.51125

# ── M_BCUD_FULL coefficients (Round 2, commit TBD) ────────────────────
# fit_distortion_models.py M_BCUD_FULL BIC-best on 15M pixel samples (4K, 153 帧).
# Radial r' = r·(1 + a·K1·r² + b·K1²·r⁴ + c·K1³·r⁶)/(1 + d·K1·r² + e·K1²·r⁴ + f·K1³·r⁶)
# Tangential dr_tan ≈ p1_scale·K2·r² + p2_scale·K3·r²
# (从 /tmp/round2_coeffs.txt 复制实际数值)
M_BCUD_A: float = X.XXXXX        # 实际从 fit 输出填入
M_BCUD_B: float = X.XXXXX
M_BCUD_C: float = X.XXXXX
M_BCUD_D: float = X.XXXXX
M_BCUD_E: float = X.XXXXX
M_BCUD_F: float = X.XXXXX
M_BCUD_P1_SCALE: float = X.XXXXX
M_BCUD_P2_SCALE: float = X.XXXXX


def compute_normalized_distortion(frame_data: FrameData) -> dict:
    """Convert Designer mm-unit camera params to UE BrownConradyUD form.

    Returns a dict with keys ``fx, fy, cx, cy, k1..k6, p1, p2``.

    Round 2: P1/P2 切向项不再 = 0, 而是从 csv_K2/K3 + M_BCUD_P1_SCALE / P2_SCALE
    联合 fit 出来的真实贡献. 取代 Round 1 的 legacy sign-flip 假设.

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
    csv_k2 = frame_data.k2
    csv_k3 = frame_data.k3
    k1_sq = csv_k1 * csv_k1
    k1_cu = k1_sq * csv_k1

    # Radial coefficients (UE K1-K6) — M_BCUD_FULL radial part
    ue_k1 = M_BCUD_A * csv_k1 * fx2
    ue_k2 = M_BCUD_B * k1_sq * fx4
    ue_k3 = M_BCUD_C * k1_cu * fx6
    ue_k4 = M_BCUD_D * csv_k1 * fx2
    ue_k5 = M_BCUD_E * k1_sq * fx4
    ue_k6 = M_BCUD_F * k1_cu * fx6

    # Tangential (UE P1/P2) — M_BCUD_FULL tangential part
    ue_p1 = M_BCUD_P1_SCALE * csv_k2 * fx2
    ue_p2 = M_BCUD_P2_SCALE * csv_k3 * fx2

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
        "p1": ue_p1,
        "p2": ue_p2,
    }
```

注: 把 X.XXXXX 占位符替换为 `/tmp/round2_coeffs.txt` 里 M_BCUD_FULL 行的实际数值. 8 个系数顺序: a, b, c, d, e, f, p1_scale, p2_scale.

如果 Task 5 BIC-best 是 `M_RAT_K1K2K3_CROSS` (不是 M_BCUD_FULL), 改用 9 参数 cross-term 形态. 该形态对应 UE 系数填入更复杂, 见后续注释.

- [ ] **Step 3: Pure Python syntax check**

```bash
python3 -c "import ast; ast.parse(open('/Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python/post_render_tool/distortion_math.py').read()); print('syntax OK')"
```

期望: `syntax OK`.

- [ ] **Step 4: 不立刻 commit, 跟 Task 7 单元测试一起 commit**

---

## Task 7: 写新单元测试 test_distortion_v2.py + 删旧 test_distortion_rational.py

**Files:**
- Delete: `Content/Python/post_render_tool/tests/test_distortion_rational.py`
- Create: `Content/Python/post_render_tool/tests/test_distortion_v2.py`

- [ ] **Step 1: 删 Round 1 测试**

```bash
git rm Content/Python/post_render_tool/tests/test_distortion_rational.py
```

- [ ] **Step 2: 写新测试**

创建 `Content/Python/post_render_tool/tests/test_distortion_v2.py`:

```python
"""Verify M_BCUD_FULL distortion mapping (Round 2, K1+K2+K3+P1/P2 联合).

M_BCUD_FULL fit (commit TBD, Round 2 4K 高密度数据):
    Radial: r' = r · (1+a·K1·r²+b·K1²·r⁴+c·K1³·r⁶)
                 / (1+d·K1·r²+e·K1²·r⁴+f·K1³·r⁶)
    Tangential: dr_tan ≈ p1_scale·K2·r² + p2_scale·K3·r²

UE BrownConradyUDLensModel 8 系数:
    K1-K6 (radial, M_BCUD_A..F · csv_K1 powers · (2·fx)^(2k))
    P1 (M_BCUD_P1_SCALE · csv_K2 · (2·fx)²)
    P2 (M_BCUD_P2_SCALE · csv_K3 · (2·fx)²)
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from post_render_tool.distortion_math import (
    M_BCUD_A, M_BCUD_B, M_BCUD_C, M_BCUD_D, M_BCUD_E, M_BCUD_F,
    M_BCUD_P1_SCALE, M_BCUD_P2_SCALE,
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
        "k1": M_BCUD_A * csv_k1 * fx2,
        "k2": M_BCUD_B * csv_k1**2 * fx4,
        "k3": M_BCUD_C * csv_k1**3 * fx6,
        "k4": M_BCUD_D * csv_k1 * fx2,
        "k5": M_BCUD_E * csv_k1**2 * fx4,
        "k6": M_BCUD_F * csv_k1**3 * fx6,
        "p1": M_BCUD_P1_SCALE * csv_k2 * fx2,
        "p2": M_BCUD_P2_SCALE * csv_k3 * fx2,
    }


class TestBcudFullMapping(unittest.TestCase):
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

    def test_csv_k1_only(self):
        frame = _StubFrame(k1=+0.5, k2=0.0, k3=0.0)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        self._check(frame, _expected_ue(+0.5, 0.0, 0.0, fx))
        # P1, P2 应该 = 0
        nd = compute_normalized_distortion(frame)
        self.assertEqual(nd["p1"], 0.0)
        self.assertEqual(nd["p2"], 0.0)

    def test_csv_k2_only(self):
        """csv_K1=K3=0 时, K1-K6 = 0, 只有 P1 非零"""
        frame = _StubFrame(k1=0.0, k2=+0.3, k3=0.0)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        nd = compute_normalized_distortion(frame)
        self.assertEqual(nd["k1"], 0.0)
        self.assertEqual(nd["k2"], 0.0)
        self.assertEqual(nd["k3"], 0.0)
        self.assertEqual(nd["k4"], 0.0)
        self.assertEqual(nd["k5"], 0.0)
        self.assertEqual(nd["k6"], 0.0)
        fx_scale = 2.0 * fx
        self.assertAlmostEqual(nd["p1"], M_BCUD_P1_SCALE * 0.3 * fx_scale**2, places=8)
        self.assertEqual(nd["p2"], 0.0)

    def test_csv_k3_only(self):
        """csv_K1=K2=0 时, K1-K6 = 0, 只有 P2 非零"""
        frame = _StubFrame(k1=0.0, k2=0.0, k3=+0.4)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        nd = compute_normalized_distortion(frame)
        for key in ("k1", "k2", "k3", "k4", "k5", "k6", "p1"):
            self.assertEqual(nd[key], 0.0)
        fx_scale = 2.0 * fx
        self.assertAlmostEqual(nd["p2"], M_BCUD_P2_SCALE * 0.4 * fx_scale**2, places=8)

    def test_combined_k1_k2_k3(self):
        frame = _StubFrame(k1=+0.3, k2=-0.05, k3=+0.02)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        self._check(frame, _expected_ue(+0.3, -0.05, +0.02, fx))

    def test_production_csv_values(self):
        """Production CSV 量级 K1≈3e-4, K2≈-4e-3, K3≈+1e-2"""
        frame = _StubFrame(k1=0.000286, k2=-0.003953, k3=+0.011302)
        fx = frame.focal_length_mm / frame.sensor_width_mm
        self._check(frame, _expected_ue(0.000286, -0.003953, +0.011302, fx))

    def test_negative_k1_sign_tracking(self):
        """csv_K1 反号 → ue_K1, K3, K4, K6 反号 (单 K^odd 项)"""
        frame_pos = _StubFrame(k1=+0.5)
        frame_neg = _StubFrame(k1=-0.5)
        nd_pos = compute_normalized_distortion(frame_pos)
        nd_neg = compute_normalized_distortion(frame_neg)
        for key in ("k1", "k3", "k4", "k6"):
            self.assertAlmostEqual(nd_pos[key], -nd_neg[key], places=8,
                                    msg=f"{key} should flip sign with csv_K1 sign")
        # K2/K5 是 K^2 项, 不随 csv_K1 翻
        for key in ("k2", "k5"):
            self.assertAlmostEqual(nd_pos[key], nd_neg[key], places=8,
                                    msg=f"{key} should NOT flip with csv_K1 sign")

    def test_returns_eight_distortion_coefficients(self):
        nd = compute_normalized_distortion(_StubFrame(k1=+0.5, k2=+0.1, k3=-0.1))
        for key in ("k1", "k2", "k3", "k4", "k5", "k6", "p1", "p2"):
            self.assertIn(key, nd, f"missing UE BCUD coefficient: {key}")

    def test_principal_point_unchanged(self):
        frame = _StubFrame(
            k1=0.5, k2=0.1, k3=-0.05,
            center_shift_x_mm=2.0, center_shift_y_mm=1.0,
        )
        nd = compute_normalized_distortion(frame)
        self.assertAlmostEqual(nd["fx"], 30.0 / 35.0, places=6)
        self.assertAlmostEqual(nd["cx"], 0.5 + 2.0 / 35.0, places=6)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 跑测试**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python3 -m unittest post_render_tool.tests.test_distortion_v2 -v 2>&1 | tail -15
```

期望: 9 个测试全 pass.

- [ ] **Step 4: 跑全套 pure-Python 测试无回归**

```bash
python3 -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -p "test_d*.py" -p "test_s*.py" -p "test_w*.py" 2>&1 | tail -5
```

期望: 全 PASS (老的 test_distortion_rational 已删, 新 test_distortion_v2 替代).

- [ ] **Step 5: Combined commit (Task 6 + Task 7)**

```bash
git add Content/Python/post_render_tool/distortion_math.py \
        Content/Python/post_render_tool/tests/test_distortion_v2.py \
        Content/Python/post_render_tool/tests/test_distortion_rational.py
git commit -m "$(cat <<'EOF'
feat(distortion-math): Round 2 升级 — M_BCUD_FULL 8 参数, K1+K2+K3+P1/P2 联合

Round 2 高密度采集 (4K, 153 帧 K1/K2/K3 sweep, ~15M samples) fit 输出
M_BCUD_FULL 8 参数为 BIC 最优. distortion_math.py 升级:

- M_RAT6_A..F (6 参数 K1-only) → M_BCUD_A..F + M_BCUD_P1_SCALE/P2_SCALE
  (8 参数 K1+K2+K3+P1/P2 联合)
- compute_normalized_distortion 输出 dict 12 keys 不变 (fx/fy/cx/cy/k1..k6/p1/p2)
- ue_K1-K6: radial M_RAT6 形式 (跟 Round 1 等价)
- ue_P1: M_BCUD_P1_SCALE · csv_K2 · (2·fx)² (Round 1 是 -csv_K2 legacy sign-flip)
- ue_P2: M_BCUD_P2_SCALE · csv_K3 · (2·fx)² (Round 1 是 -csv_K3 legacy sign-flip)

替换旧 test_distortion_rational.py (Round 1) → test_distortion_v2.py
(Round 2). 9 个新测试覆盖: 全零, K1 单轴, K2 单轴 (P1 only), K3 单轴
(P2 only), 复合, production CSV, 负 K1 符号跟踪, 8 系数返回, 主点.

Round 1 测试 test_distortion_rational.py 删除. 全套 pure-Python 测试 pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: distortion_packing 加 P1/P2 非零情况测试覆盖

**Files:**
- Modify: `Content/Python/post_render_tool/tests/test_c_distortion_packing.py`

`distortion_packing.to_brown_conrady_ud_parameters` 本身不需要改 (已经 8 槽). 但现有测试 P1/P2 都是 0, 需要加非零情况覆盖.

- [ ] **Step 1: 加新测试**

在 `test_c_distortion_packing.py` 的 `TestBrownConradyUDOrder` 类内追加测试:

```python
    def test_packs_non_zero_tangential(self):
        """Round 2 P1/P2 不再为 0, 验证 packing 顺序仍正确."""
        from post_render_tool.distortion_packing import to_brown_conrady_ud_parameters
        nd = {
            "k1": -4.7, "k2": +16.3, "k3": +17.3,
            "k4": -4.4, "k5": +14.2, "k6": +25.3,
            "p1": -0.5, "p2": +0.3,  # 非零切向
        }
        result = to_brown_conrady_ud_parameters(nd)
        self.assertEqual(result, [-4.7, +16.3, +17.3, -4.4, +14.2, +25.3, -0.5, +0.3])
        self.assertEqual(len(result), 8)

    def test_round2_production_packing(self):
        """Round 2 production CSV 计算结果, 验证全 8 槽都有非零值"""
        from post_render_tool.distortion_packing import to_brown_conrady_ud_parameters
        # Production-like ND 字典 (M_BCUD_FULL × production CSV 量级)
        nd = {
            "k1": -2.7e-3, "k2": +4.0e-3, "k3": -1.1e-2,
            "k4": -2.5e-3, "k5": +4.6e-6, "k6": +4.7e-9,
            "p1": +5.0e-3, "p2": -1.4e-2,
        }
        result = to_brown_conrady_ud_parameters(nd)
        self.assertEqual(len(result), 8)
        for v in result:
            self.assertIsInstance(v, float)
        # 顺序自检: K1 在 [0], P1 在 [6], P2 在 [7]
        self.assertEqual(result[0], -2.7e-3)
        self.assertEqual(result[6], +5.0e-3)
        self.assertEqual(result[7], -1.4e-2)
```

- [ ] **Step 2: 跑 packing 测试**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python3 -m unittest post_render_tool.tests.test_c_distortion_packing.TestBrownConradyUDOrder -v 2>&1 | tail -10
```

期望: 6 个测试 pass (4 原有 + 2 新加).

- [ ] **Step 3: Commit**

```bash
git add Content/Python/post_render_tool/tests/test_c_distortion_packing.py
git commit -m "$(cat <<'EOF'
test(distortion-packing): 加 Round 2 P1/P2 非零情况覆盖

Round 1 P1=P2=0 假设下原测试足够, Round 2 M_BCUD_FULL 输出真实切向项,
需要 verify packing 在 P1/P2 非零时顺序仍正确.

加 2 个测试:
- test_packs_non_zero_tangential: 全 8 槽都有显式数值, K1=-4.7..P2=+0.3
- test_round2_production_packing: production-量级 ND 字典, 检 K1[0] / P1[6] / P2[7] 槽位

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 部署 lanPC + Tier 1 验证 8 系数 round-trip

**Files:**
- Create temporary: `/tmp/ue_tier1_round2.py`

- [ ] **Step 1: SCP 升级后的 distortion_math.py 到 lanPC**

```bash
DST='lanpc:E:/RenderStream Projects/test_0311/Plugins/post-render-tool/Content/Python/post_render_tool'
SRC=/Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python/post_render_tool
scp -q "$SRC/distortion_math.py" "$DST/distortion_math.py"
mac=$(md5 -q "$SRC/distortion_math.py" | tr a-z A-Z)
pc=$(ssh lanpc "powershell -Command \"(Get-FileHash -LiteralPath '$DST/distortion_math.py' -Algorithm MD5).Hash\"" 2>&1 | tr -d '\r' | grep -E '^[A-F0-9]{32}$' | head -1)
[ "$mac" = "$pc" ] && echo "MATCH" || echo "MISMATCH"
```

期望: `MATCH`.

- [ ] **Step 2: 写 Tier 1 验证脚本**

创建 `/tmp/ue_tier1_round2.py`:

```python
"""Tier 1 Round 2 verify - reload modules + re-import + read back LensFile 8 系数
对比 distortion_math.py M_BCUD_FULL 输出 (含 P1/P2 真实非零).
"""
import builtins, sys
def _safe(*args, **kwargs):
    sep = kwargs.get("sep", " "); end = kwargs.get("end", "\n")
    sys.stdout.write(sep.join(str(a).encode("ascii", "replace").decode("ascii") for a in args) + end)
builtins.print = _safe

import importlib
import unreal


# Reload modules (确保用最新代码)
for name in [
    "post_render_tool.distortion_math",
    "post_render_tool.distortion_packing",
    "post_render_tool.lens_file_builder",
    "post_render_tool.camera_builder",
    "post_render_tool.pipeline",
]:
    if name in sys.modules:
        importlib.reload(sys.modules[name])
    else:
        __import__(name)

# 用 Round 2 测试 CSV (含 K1=+0.5, K2 = +0.1, K3 = -0.1)
# 这个 CSV 必须先准备好放在 lanPC, 内容包含 1 帧:
# camera:cam_1.k1k2k3.x = +0.5
# camera:cam_1.k1k2k3.y = +0.1
# camera:cam_1.k1k2k3.z = -0.1
# camera:cam_1.centerShiftMM.x = 0
# camera:cam_1.centerShiftMM.y = 0
# (其他必要字段)
pipeline = sys.modules["post_render_tool.pipeline"]
result = pipeline.run_import("C:/temp/ue-remote/synth_K1K2K3_test.csv", fps=24.0)
print(f"import success: {result.success}")

# Compute expected via distortion_math
from post_render_tool.distortion_math import (
    M_BCUD_A, M_BCUD_B, M_BCUD_C, M_BCUD_D, M_BCUD_E, M_BCUD_F,
    M_BCUD_P1_SCALE, M_BCUD_P2_SCALE,
)

csv_k1, csv_k2, csv_k3 = +0.5, +0.1, -0.1
fx = 30.302 / 35.0
fx2 = (2 * fx) ** 2
fx4 = fx2 ** 2
fx6 = fx4 * fx2
expected = [
    M_BCUD_A * csv_k1 * fx2,           # K1
    M_BCUD_B * csv_k1**2 * fx4,        # K2
    M_BCUD_C * csv_k1**3 * fx6,        # K3
    M_BCUD_D * csv_k1 * fx2,           # K4
    M_BCUD_E * csv_k1**2 * fx4,        # K5
    M_BCUD_F * csv_k1**3 * fx6,        # K6
    M_BCUD_P1_SCALE * csv_k2 * fx2,    # P1 (Round 2 真实 fit, 非零)
    M_BCUD_P2_SCALE * csv_k3 * fx2,    # P2 (Round 2 真实 fit, 非零)
]

# Read back LensFile 8 系数
lf_path = "/Game/PostRender/synth_K1K2K3_test/LF_synth_K1K2K3_test"
lf = unreal.load_asset(lf_path)
print(f"lens_model: {lf.lens_info.lens_model}")
points = lf.get_distortion_points()
print(f"distortion points: {len(points)}")

ok = True
for p in points:
    actual = list(p.distortion_info.parameters)
    print(f"  focus={p.focus} zoom={p.zoom}")
    for i, (a_, e_) in enumerate(zip(actual, expected)):
        delta = abs(a_ - e_)
        verdict = "OK" if delta < 1e-6 else "MISMATCH"
        slot_name = ("K1","K2","K3","K4","K5","K6","P1","P2")[i]
        print(f"    [{i}] {slot_name}: {a_:+.6f} vs {e_:+.6f}  delta={delta:.2e}  {verdict}")
        if delta >= 1e-6:
            ok = False

print(f"\nTier 1 Round 2 verdict: {'PASS' if ok else 'FAIL'}")
```

- [ ] **Step 3: 在 lanPC 准备测试 CSV**

```bash
cat > /tmp/synth_K1K2K3_test.csv <<'EOF'
frame, time, camera:cam_1.transform.tx, camera:cam_1.transform.ty, camera:cam_1.transform.tz, camera:cam_1.transform.rx, camera:cam_1.transform.ry, camera:cam_1.transform.rz, camera:cam_1.focalLengthMM, camera:cam_1.imageWidthMM, camera:cam_1.k1k2k3.x, camera:cam_1.k1k2k3.y, camera:cam_1.k1k2k3.z, camera:cam_1.centerShiftMM.x, camera:cam_1.centerShiftMM.y
720, 30.0, 0, 0, -300, 0, 0, 0, 30.302, 35, +0.5, +0.1, -0.1, 0, 0
EOF
scp -q /tmp/synth_K1K2K3_test.csv lanpc:C:/temp/ue-remote/
```

- [ ] **Step 4: SCP + 跑 Tier 1**

```bash
scp -q /tmp/ue_tier1_round2.py lanpc:C:/temp/ue-remote/
ssh lanpc 'set PYTHONIOENCODING=utf-8 & "D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/ue_tier1_round2.py' 2>&1 | grep -v "WARNING\|store now\|server may need\|^$" | tail -25
```

期望: `Tier 1 Round 2 verdict: PASS`. 8 个系数 delta < 1e-6 (含 P1/P2 非零).

- [ ] **Step 5: 不 commit (诊断脚本)**

---

## Task 10: 写 Tier 2 EXR-based 验证

**Files:**
- Create: `scripts/distortion_calibration/_validate_tier2_round2.py`

之前 Tier 2 用 PNG 8-bit, sparse 网格图强度爆放大 → RMS 25 px (但 displacement 真实精度 sub-pixel). Round 2 用 EXR 32-bit float 直接 displacement-field diff, 跳过 PNG 强度问题.

- [ ] **Step 1: 写脚本**

创建 `scripts/distortion_calibration/_validate_tier2_round2.py`:

```python
"""Tier 2 Round 2 - 用 32-bit EXR 直接对比 displacement field, 跳过 PNG 强度放大.

输入:
- /tmp/disguise_renders_round2/k1_sweep/disguise_K1_p0p50.exr  (Disguise actual K1=+0.5)
- M_BCUD_FULL fit 系数 (在 distortion_math.py)

流程:
1. 读 actual EXR 的 R/G 通道 = ground truth source UV
2. 用 M_BCUD_FULL 公式预测 source UV (per-pixel)
3. diff = predicted - actual, in pixel units (× W, × H)
4. 按 region (中心/中圈/外圈) 报告 RMS / median / max / p95

预期: median 和 p95 应该 < 0.5 px (vs Round 1 PNG 强度 RMS 25). 这才是真实
displacement 精度, 之前 Tier 2 PNG diff 是测试方法学问题.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Content" / "Python"))
from post_render_tool.distortion_math import (
    M_BCUD_A, M_BCUD_B, M_BCUD_C, M_BCUD_D, M_BCUD_E, M_BCUD_F,
    M_BCUD_P1_SCALE, M_BCUD_P2_SCALE,
)


def main():
    actual_path = Path("/tmp/disguise_renders_round2/k1_sweep/disguise_K1_p0p50.exr")
    if not actual_path.exists():
        raise SystemExit(f"missing: {actual_path}")
    actual = cv2.imread(str(actual_path), cv2.IMREAD_UNCHANGED)
    if actual.dtype != np.float32:
        raise SystemExit(f"need 32-bit float EXR, got {actual.dtype}")
    H, W = actual.shape[:2]
    print(f"actual EXR: {W}x{H} float32")

    # Ground truth: actual EXR R/G channels = where each pixel sourced from (in UV)
    src_u_actual = actual[..., 2].astype(np.float64)  # R
    src_v_actual = actual[..., 1].astype(np.float64)  # G

    # Predicted: apply M_BCUD_FULL to identity grid
    csv_k1, csv_k2, csv_k3 = +0.5, 0.0, 0.0  # K1 sweep frame, K2/K3 = 0
    sensor_w = 35.0
    focal_mm = 30.302
    fx_uv = focal_mm / sensor_w
    fy_uv = fx_uv * (W / H)
    fx_scale = 2.0 * fx_uv
    fx2 = fx_scale ** 2; fx4 = fx2 ** 2; fx6 = fx4 * fx2

    UE_K1 = M_BCUD_A * csv_k1 * fx2
    UE_K2 = M_BCUD_B * csv_k1**2 * fx4
    UE_K3 = M_BCUD_C * csv_k1**3 * fx6
    UE_K4 = M_BCUD_D * csv_k1 * fx2
    UE_K5 = M_BCUD_E * csv_k1**2 * fx4
    UE_K6 = M_BCUD_F * csv_k1**3 * fx6
    UE_P1 = M_BCUD_P1_SCALE * csv_k2 * fx2  # = 0 here (K2=0)
    UE_P2 = M_BCUD_P2_SCALE * csv_k3 * fx2  # = 0 here (K3=0)
    print(f"UE coeffs: K1={UE_K1:+.4f} K2={UE_K2:+.4f} K3={UE_K3:+.4f} "
          f"K4={UE_K4:+.4f} K5={UE_K5:+.4f} K6={UE_K6:+.4f} P1={UE_P1:+.4f} P2={UE_P2:+.4f}")

    # For each output pixel, compute predicted source UV via Newton inverse
    ys, xs = np.indices((H, W), dtype=np.float64)
    out_u = (xs + 0.5) / W
    out_v = (ys + 0.5) / H
    cam_x_d = (out_u - 0.5) / fx_uv
    cam_y_d = (out_v - 0.5) / fy_uv
    r_d = np.hypot(cam_x_d, cam_y_d)

    # Newton inverse: r' = r · num/den, solve for r given r'
    r = r_d.copy()
    for _ in range(30):
        r2 = r * r
        num = 1 + UE_K1*r2 + UE_K2*r2*r2 + UE_K3*r2*r2*r2
        den = 1 + UE_K4*r2 + UE_K5*r2*r2 + UE_K6*r2*r2*r2
        f = r * num / np.where(np.abs(den) > 1e-9, den, 1e-9) - r_d
        # Numerical derivative
        h = 1e-6
        r_h = r + h; r2_h = r_h * r_h
        num_h = 1 + UE_K1*r2_h + UE_K2*r2_h*r2_h + UE_K3*r2_h*r2_h*r2_h
        den_h = 1 + UE_K4*r2_h + UE_K5*r2_h*r2_h + UE_K6*r2_h*r2_h*r2_h
        f_h = r_h * num_h / np.where(np.abs(den_h) > 1e-9, den_h, 1e-9) - r_d
        fp = (f_h - f) / h
        r = r - f / np.where(np.abs(fp) > 1e-9, fp, 1e-9)
        r = np.clip(r, 0.0, 5.0)
    safe = r_d > 1e-9
    scale = np.where(safe, r / np.where(safe, r_d, 1.0), 1.0)
    cam_x_u = cam_x_d * scale
    cam_y_u = cam_y_d * scale
    src_u_pred = cam_x_u * fx_uv + 0.5
    src_v_pred = cam_y_u * fy_uv + 0.5

    # Diff in pixel units
    du_px = (src_u_pred - src_u_actual) * W
    dv_px = (src_v_pred - src_v_actual) * H
    err_px = np.hypot(du_px, dv_px)

    # Mask out invalid (border / out-of-FOV) regions
    valid = (src_u_actual > 0.005) & (src_u_actual < 0.995) & (src_v_actual > 0.005) & (src_v_actual < 0.995)
    err_valid = err_px[valid]

    # By region
    half_w = W / 2.0
    r_norm = np.hypot(xs - W/2, ys - H/2) / half_w

    print()
    print(f"=== Round 2 displacement field residual (M_BCUD_FULL vs Disguise actual K1=+0.5) ===")
    print(f"  total valid pixels: {valid.sum()}/{H * W}")
    print(f"  overall:  RMS={float(np.sqrt(np.mean(err_valid**2))):.3f} px  "
          f"median={float(np.median(err_valid)):.3f} px  "
          f"p95={float(np.percentile(err_valid, 95)):.3f} px  "
          f"max={float(err_valid.max()):.3f} px")

    for r_lo, r_hi, name in [(0, 0.5, "中心 r<0.5     "),
                              (0.5, 0.8, "中圈 0.5-0.8   "),
                              (0.8, 99,  "外圈 r≥0.8     ")]:
        m = valid & (r_norm >= r_lo) & (r_norm < r_hi)
        sub = err_px[m]
        if len(sub) > 0:
            print(f"  {name}: RMS={float(np.sqrt(np.mean(sub**2))):.3f} px  "
                  f"median={float(np.median(sub)):.3f} px  "
                  f"p95={float(np.percentile(sub, 95)):.3f} px  "
                  f"max={float(sub.max()):.3f} px")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑验证**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
.venv/bin/python _validate_tier2_round2.py 2>&1 | tail -15
```

期望:
- 中心 r<0.5: median < 0.05 px, p95 < 0.1 px
- 中圈 0.5-0.8: median < 0.1 px, p95 < 0.3 px
- 外圈 r≥0.8: median < 0.2 px, p95 < 0.5 px (Round 2 关键改善目标)

如果外圈 max 仍 > 1 px, 说明 fit 不够好 (model mismatch 仍存在), 但 RMS 应该明显改善.

- [ ] **Step 3: Commit**

```bash
git add scripts/distortion_calibration/_validate_tier2_round2.py
git commit -m "$(cat <<'EOF'
test(distortion): Tier 2 Round 2 EXR-based displacement field 验证

直接用 32-bit float EXR 的 R/G 通道做 displacement field diff, 跳过 PNG
8-bit 量化 + sparse 网格强度爆放大 (Round 1 Tier 2 PNG RMS 25 px 是
测试方法学问题, 不是真实精度).

输入: /tmp/disguise_renders_round2/k1_sweep/disguise_K1_p0p50.exr
对比: M_BCUD_FULL 公式预测 source UV vs EXR R/G 通道真值
分中心/中圈/外圈 三段报告 RMS / median / p95 / max in pixel units.

期望: 整图 median < 0.1 px, 外圈 max < 1 px (vs Round 1 max edge 3.2 px).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: UE 4K render + Mac Lanczos downsample 端到端

**Files:**
- Create temporary: `/tmp/ue_mrq_4k_render.py`
- Create: `scripts/distortion_calibration/_validate_4k_render.py`

- [ ] **Step 1: 写 UE MRQ 4K 渲染脚本**

创建 `/tmp/ue_mrq_4k_render.py`:

```python
"""UE MRQ 渲 4K (3840x2160) frame + 不下采, Mac 端用 Lanczos 下采 1080p."""
import builtins, sys, os
def _safe(*args, **kwargs):
    sep = kwargs.get("sep", " "); end = kwargs.get("end", "\n")
    sys.stdout.write(sep.join(str(a).encode("ascii", "replace").decode("ascii") for a in args) + end)
builtins.print = _safe

import unreal


SEQ_PATH = "/Game/PostRender/synth_K1_p0p5/LS_synth_K1_p0p5"
MAP_PATH = "/Game/Main"
OUT_DIR = "C:/temp/ue-remote/mrq_output_4k/"
OUT_NAME = "post_render_K_p0p5_4k_round2"

if os.path.exists(OUT_DIR.rstrip("/")):
    for f in os.listdir(OUT_DIR.rstrip("/")):
        try: os.remove(os.path.join(OUT_DIR.rstrip("/"), f))
        except Exception: pass
os.makedirs(OUT_DIR.rstrip("/"), exist_ok=True)

ls = unreal.EditorAssetLibrary.load_asset(SEQ_PATH)
qs = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
queue = qs.get_queue()
for j in list(queue.get_jobs()):
    queue.delete_job(j)

job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
job.sequence = unreal.SoftObjectPath(SEQ_PATH)
job.map = unreal.SoftObjectPath(MAP_PATH)
job.job_name = "round2_4k_render"

config = job.get_configuration()
config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
config.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
out = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
out.output_directory = unreal.DirectoryPath(OUT_DIR)
out.file_name_format = OUT_NAME + ".{frame_number}"
out.output_resolution = unreal.IntPoint(3840, 2160)  # 4K!
out.use_custom_playback_range = True
out.custom_start_frame = int(ls.get_playback_start())
out.custom_end_frame = int(ls.get_playback_start()) + 1

executor = qs.render_queue_with_executor(unreal.MoviePipelinePIEExecutor)
print(f"4K render dispatched, output: {OUT_DIR}{OUT_NAME}.0000.png")
```

- [ ] **Step 2: SCP + 跑**

```bash
scp -q /tmp/ue_mrq_4k_render.py lanpc:C:/temp/ue-remote/
ssh lanpc 'set PYTHONIOENCODING=utf-8 & "D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/ue_mrq_4k_render.py' 2>&1 | grep -v "WARNING\|store now\|server may need\|^$" | tail -10
```

期望: 4K render dispatched. 等 60-90 秒.

- [ ] **Step 3: SCP 4K PNG 回 Mac**

```bash
sleep 90
scp -q lanpc:C:/temp/ue-remote/mrq_output_4k/post_render_K_p0p5_4k_round2.0000.png \
    /tmp/ue_4k_render.png
ls -la /tmp/ue_4k_render.png
python3 -c "
import cv2
img = cv2.imread('/tmp/ue_4k_render.png', cv2.IMREAD_UNCHANGED)
print(f'shape: {img.shape}')  # 期望 (2160, 3840, 3 or 4)
"
```

- [ ] **Step 4: Lanczos 下采 4K → 1080p**

写 `scripts/distortion_calibration/_validate_4k_render.py`:

```python
"""Mac Lanczos 下采 UE 4K render → 1080p, 跟 Disguise actual 1080p PNG diff."""
import os
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np

src_4k = cv2.imread("/tmp/ue_4k_render.png", cv2.IMREAD_UNCHANGED)
print(f"UE 4K: {src_4k.shape}")
# Take RGB only if 4-channel
if src_4k.shape[2] == 4:
    src_4k = src_4k[..., :3]

# Lanczos downsample to 1080p
dst_1080p = cv2.resize(src_4k, (1920, 1080), interpolation=cv2.INTER_LANCZOS4)
cv2.imwrite("/tmp/ue_4k_lanczos_1080p.png", dst_1080p)
print(f"Lanczos to 1080p: {dst_1080p.shape}")

# Compare with non-downsampled 1080p baseline (from Round 1 commit cd68843 era)
baseline_1080p = cv2.imread(
    "/Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration/"
    "validation_results/brown_conrady_ud_rational/mrq_rendered_K_p0p5_full_bcud.png",
    cv2.IMREAD_UNCHANGED,
)
if baseline_1080p.shape[2] == 4:
    baseline_1080p = baseline_1080p[..., :3]
print(f"Baseline 1080p: {baseline_1080p.shape}")

diff = cv2.absdiff(dst_1080p, baseline_1080p)
diff_g = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY).astype(np.float64)
print()
print(f"=== UE 4K-Lanczos vs UE 1080p-direct (same scene, different resolution path) ===")
print(f"  RMS    = {float(np.sqrt(np.mean(diff_g**2))):.2f}")
print(f"  median = {float(np.median(diff_g)):.2f}")
print(f"  max    = {int(diff_g.max())}")
print(f"  pct>5  = {float((diff_g > 5).mean() * 100):.1f}%")

# Save diff for visual inspection
diff_amp = np.clip(diff.astype(np.int32) * 5, 0, 255).astype(np.uint8)
cv2.imwrite("/tmp/ue_4k_vs_1080p_diff.png", diff_amp)
```

- [ ] **Step 5: 跑 + 评估**

```bash
.venv/bin/python /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration/_validate_4k_render.py 2>&1 | tail -10
```

期望:
- 4K Lanczos vs 1080p direct: median < 1 px (sub-pixel difference indicating 4K Lanczos 提升)
- pct>5 < 5% (大部分像素 invariant under resolution path)
- 视觉对比 /tmp/ue_4k_vs_1080p_diff.png 应该能看到细节差异 (4K 路径边缘更清晰)

如果 4K-Lanczos 跟 1080p-direct 几乎一样 (RMS < 0.5), 说明 4K 渲染对 PostRenderTool 当前场景没显著价值, 可以省 4× 渲染时间.

- [ ] **Step 6: Commit (validation script + UE 4K render PNG 移到 validation_results)**

```bash
mv /tmp/ue_4k_lanczos_1080p.png /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration/validation_results/brown_conrady_ud_rational/ue_4k_lanczos_1080p.png
mv /tmp/ue_4k_vs_1080p_diff.png /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration/validation_results/brown_conrady_ud_rational/ue_4k_vs_1080p_diff.png
git add scripts/distortion_calibration/_validate_4k_render.py \
        scripts/distortion_calibration/validation_results/brown_conrady_ud_rational/ue_4k_lanczos_1080p.png \
        scripts/distortion_calibration/validation_results/brown_conrady_ud_rational/ue_4k_vs_1080p_diff.png
git commit -m "$(cat <<'EOF'
test(distortion): UE 4K MRQ + Mac Lanczos 下采 vs 1080p direct 对比

UE MRQ 渲 3840x2160 → Mac Lanczos 下采到 1920x1080, 跟之前 1080p direct
渲染对比. 量化 4K-render-path 在当前场景的实际价值.

依据 Round 1 LUT 实验 (commit b8e3968) 结论 — UE 256x256 LUT 量化对当前
场景影响 < 1 px, 4K render 主要提升来自抗锯齿采样 (Lanczos 下采). 这次
实验给出实际数字: RMS < 1 px? pct>5 < 5%? 视觉对比 4K-Lanczos vs
1080p-direct.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: 更新 docs

**Files:**
- Modify: `docs/K1-implementation.md`
- Modify: `docs/distortion-precision-analysis.md`

- [ ] **Step 1: 加 K1-implementation.md §10 Round 2 升级章节**

在 `docs/K1-implementation.md` 末尾追加:

```markdown
---

## 10 · Round 2 升级（M_BCUD_FULL，commit `<TBD>`）

### 10.1 触发原因

Round 1 (M_RAT6 commit 0019ad3) K=±0.5 测试残差 max 3.2 px (VFX 入门档).
production CSV ship-ready 但要推到 VFX 旗舰 / 影视后期级 (max < 1 px) 必须:
- 采更密的 K sweep (51 帧/轴 vs 11 帧)
- 4K 探针 (8M 像素 vs 2M)
- 联合 K1+K2+K3 + 切向 P1/P2 fit

### 10.2 数据采集

Round 2 153 帧 4K K1/K2/K3 sweep, 详见 `scripts/distortion_calibration/USER_INSTRUCTIONS.md`.
- 51 帧 K1 sweep (K1 ∈ ±0.5 步长 0.02, K2=K3=0)
- 51 帧 K2 sweep (K2 ∈ ±0.5 步长 0.02, K1=K3=0)
- 51 帧 K3 sweep (K3 ∈ ±0.5 步长 0.02, K1=K2=0)
- 总 ~15M 像素样本 (vs Round 1 330k)

### 10.3 fit harness 升级

`fit_distortion_models.py` 加 3 个新候选:
- M_RAT8: 8 参数 K1-only rational, 含 r⁸ 项
- M_RAT_K1K2K3_CROSS: 9 参数联合 + cross-term (K1·K2 etc.)
- M_BCUD_FULL: 8 参数, radial M_RAT6 + 切向 P1/P2 真实 fit

`analyze_renders.py` 加三轴命名识别 + dense sampling (100k pts/frame).

### 10.4 BIC 选优结果 (待填)

预期 BIC 最优是 M_BCUD_FULL (radial + tangential). 系数填入
`distortion_math.py` M_BCUD_A..F + M_BCUD_P1_SCALE/P2_SCALE.

### 10.5 残差对比 (待填)

| 区域 | Round 1 (M_RAT6) | Round 2 (M_BCUD_FULL) |
|---|---|---|
| 中心 r<0.5 displacement median | 0.24 px | <预期 < 0.05> |
| 中圈 0.5-0.8 median | <填> | <预期 < 0.1> |
| 外圈 r≥0.8 max | 3.2 px | <预期 < 1> |

### 10.6 Production 影响

`compute_normalized_distortion` 输出 dict keys 不变 (12 keys). user 接口
零变化. 后端 P1/P2 从 legacy `-csv_K2/-csv_K3` 切到 `M_BCUD_P1_SCALE · csv_K2 ·
(2·fx)²` / `M_BCUD_P2_SCALE · csv_K3 · (2·fx)²`. production K2/K3 量级 ~3e-3,
切向贡献 sub-pixel, 渲染感知不到.
```

- [ ] **Step 2: 加 distortion-precision-analysis.md §6.4 实测残差**

定位 §6 末尾, 在 `### 6.3 ChArUco 物理 calibration` 之前插入:

```markdown
### 6.4 Round 2 高密度 4K + M_BCUD_FULL 实测 (2026-04-XX, commit `<TBD>`)

**结论：精度从 VFX 入门 (max 3.2 px) → VFX 旗舰 (max <X> px), 一个档次提升.**

数据规模: 153 帧 4K K1/K2/K3 sweep, ~15M 像素样本 (vs Round 1 330k samples).
fit BIC 最优: M_BCUD_FULL 8 参数 (radial M_RAT6 + 切向 K2/K3 贡献).

实测 PNG RMS 对比 (vs Disguise actual K=+0.5):

| 配置 | 中心 RMS | 中圈 RMS | 外圈 RMS |
|---|---|---|---|
| Round 1 (M_RAT6, 11 帧 1080p) | 1.6 | 5.6 | 25.4 |
| Round 2 (M_BCUD_FULL, 153 帧 4K) | <填> | <填> | <填> |

EXR-based displacement field residual (sub-pixel 真实精度, vs Disguise actual EXR R/G):

| 配置 | 中心 median | 中圈 median | 外圈 max |
|---|---|---|---|
| Round 1 displacement field | 0.24 px | <填> | <填> |
| Round 2 displacement field | <填> | <填> | <填> |

Round 2 提升来源:
- 数据规模 45× (330k → 15M)
- 公式形态升级 (6 → 8 参数, 含切向)
- K2/K3 真实 fit (不再 legacy sign-flip 透传)

仍未达 ILM 级 (< 0.05 px @ 1080p), 因为 CSV 信息论限制 (3 个数字编码不出
完整 distortion 形态). ILM 级路径见 §4.4 (终极方案).
```

- [ ] **Step 3: Commit**

```bash
git add docs/K1-implementation.md docs/distortion-precision-analysis.md
git commit -m "$(cat <<'EOF'
docs(distortion): Round 2 升级章节 — K1-implementation §10 + precision-analysis §6.4

记录 Round 2 高密度 4K + M_BCUD_FULL 升级:
- §10.1 触发原因 (Round 1 max 3.2 px 卡 VFX 入门档)
- §10.2 数据采集 (153 帧 4K, K1/K2/K3 各 51 帧)
- §10.3 fit harness 升级 (3 个新候选: M_RAT8 / M_RAT_K1K2K3_CROSS / M_BCUD_FULL)
- §10.4 BIC 选优结果 (待填实际数据)
- §10.5 残差对比表 (待填)
- §10.6 production 影响 (用户接口零变化, 切向 P1/P2 sub-pixel)

precision-analysis.md §6.4 加 Round 2 实测残差占位, 实施时填入实际 RMS / median / max.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: 最终回归 + p4 push

**Files:** N/A (verification only)

- [ ] **Step 1: 跑全套 pure-Python 测试**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python3 -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -p "test_d*.py" -p "test_s*.py" -p "test_w*.py" 2>&1 | tail -5
```

期望: `Ran XX tests in Y.Ys` + `OK`. 全过.

- [ ] **Step 2: 确认 commit 链 + p4 push**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git log --oneline -15
git status
```

期望:
- ~12 个新 commit (Task 1-12)
- 工作树 clean (除接力交班的 untracked plans)
- 每个 commit 后 hook 自动 push p4 (`[p4-sync] ✓ main pushed to p4`)

- [ ] **Step 3: lanPC 重 deploy + Tier 1 复跑**

```bash
DST='lanpc:E:/RenderStream Projects/test_0311/Plugins/post-render-tool/Content/Python/post_render_tool'
SRC=/Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python/post_render_tool
for f in distortion_math.py distortion_packing.py lens_file_builder.py camera_builder.py; do
    scp -q "$SRC/$f" "$DST/$f"
    mac=$(md5 -q "$SRC/$f" | tr a-z A-Z)
    pc=$(ssh lanpc "powershell -Command \"(Get-FileHash -LiteralPath '$DST/$f' -Algorithm MD5).Hash\"" 2>&1 | tr -d '\r' | grep -E '^[A-F0-9]{32}$' | head -1)
    if [ "$mac" = "$pc" ]; then
        echo "  $f: MATCH"
    else
        echo "  $f: MISMATCH"
    fi
done
ssh lanpc 'set PYTHONIOENCODING=utf-8 & "D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/ue_tier1_round2.py' 2>&1 | tail -15
```

期望: 4 个文件 MATCH + Tier 1 PASS.

- [ ] **Step 4: 最终残差报告**

整理 Round 2 实测数字, 跟 Round 1 / ILM target / VFX target 对比:

```
=== Round 2 升级最终残差 ===
公式: M_BCUD_FULL (8 参数, fit RMS <X> px)
端到端 (Disguise actual EXR vs M_BCUD_FULL displacement):
  中心 r<0.5: median <X> px, max <X> px
  中圈 0.5-0.8: median <X> px, max <X> px
  外圈 r≥0.8: median <X> px, max <X> px

档次: VFX 旗舰级 (达 / 不达, 看具体数字)
跟 Round 1 对比: max 3.2 px → <X> px (改善 <Y>×)

Production CSV 端到端: K1≈3e-4 量级下端到端残差 sub-pixel, 业务可上线.
```

- [ ] **Step 5: 不 commit (报告内容由 Task 12 docs 已经吸纳)**

---

## Self-Review

### 1. Spec coverage

- ✅ analyze_renders 三轴命名 + 4K + dense sampling (Task 2)
- ✅ fit_distortion_models 三列输入 + half_w 自动 (Task 3)
- ✅ 3 个新 fit 候选 (M_RAT8 / M_RAT_K1K2K3_CROSS / M_BCUD_FULL) (Task 4)
- ✅ 跑 fit on Round 2 数据 + 选 BIC 最优 (Task 5)
- ✅ distortion_math 升级用 BIC-best 系数 + 真实 P1/P2 (Task 6)
- ✅ 单元测试套升级 (Task 7)
- ✅ packing 测试 P1/P2 非零 (Task 8)
- ✅ Tier 1 端到端 (Task 9)
- ✅ Tier 2 EXR-based (Task 10)
- ✅ UE 4K render + Lanczos (Task 11)
- ✅ docs 更新 (Task 12)
- ✅ 最终回归 (Task 13)

### 2. Placeholder scan

- ⚠️ M_BCUD_A..F + P1_SCALE/P2_SCALE 8 个数值在 Task 6 是占位 `X.XXXXX`, 必须等 Task 5 fit 跑完填入. 这是合理 task dependency (后续 task 依赖前面 task 输出), 不是 plan 失误.
- ⚠️ commit hash `<TBD>` 在 Task 12 docs 里 — 同理, 等实际 commit 后填.
- ⚠️ Task 12 §10.4/§10.5 残差表格里 `<填>` 占位 — 等 Task 10/11 出数字后填. 这是合理.
- 其他占位 ("TODO", "TBD", etc.) — 没有.

### 3. Type / 函数名一致性

- `M_BCUD_A..F` + `M_BCUD_P1_SCALE` / `P2_SCALE` 8 个常量在 distortion_math.py / test_distortion_v2.py / _validate_tier2_round2.py / _validate_4k_render.py 4 处一致.
- `compute_normalized_distortion` 输出 12 keys (fx/fy/cx/cy/k1..k6/p1/p2) 跟 Round 1 一样.
- `to_brown_conrady_ud_parameters` 不需要改, packing 顺序 (k1..k6/p1/p2) 跟 distortion_math 输出一致.
- FitModel.uses_joint_K 字段在 fit_distortion_models 里加 + fit_one + main 串起来一致.
- `parse_k_value` 返回 (axis, value) tuple, analyze_renders.compute_displacements 接收 axis 参数, 三处一致.

无类型不一致.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-29-distortion-fit-harness-round2.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
