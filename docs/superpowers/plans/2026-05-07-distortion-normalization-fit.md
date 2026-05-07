# d3 Distortion Normalization Fit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 12 帧 EXR 反推 d3 内部 distortion 公式真身 —— focal-length normalization 用什么 r 定义、K2/K3 是不是同 normalization、centerShift 单位/符号约定 —— 一次解决,直接 commit 死。

**Architecture:** 复用 `archive/_exr.py` + `archive/analyze_renders.py` 的 EXR / over-scan helpers。新写一个 fit harness `scripts/distortion_calibration/fit_normalization_candidates.py`,跨 5 个 normalization 候选(full-width, focal-length, diagonal, height, half-width)做 delta-residual 比较:对每个候选 NORM_cand,把 K1=+0.5 帧的 R/G 通道反推 source pixel,跟 forward Brown-Conrady prediction 比 p95(delta);跨 3 个 focal 看哪个候选 fit 出**一致** K1_eff = +0.5。同套 harness 跑 K2/K3/centerShift 单变量 sweep。如果 fit 结论是 "current shader (full-width) 公式正确" → 只 commit fit 报告 + 文档;如果偏离 → 改 HLSL + Python reference + 单元测试 + lanPC 远程 rebuild material asset。最后跑 `compare_production_frame.py` 确保 take_4 baseline (`valid_p95=0.1255`) 没破坏。

**Tech Stack:** Python 3.14 venv (`scripts/distortion_calibration/.venv`,cv2 4.13 + numpy 2.4 + scipy 1.17),Pure-Python(no UE 依赖)。Shader 修改如有则在 lanPC UE 5.7 远程执行(SCP + run_ue.py bridge,见项目 CLAUDE.md "UE Python Remote Execution")。

**Reference docs:**
- `docs/d3-distortion-render-request.md` — 数据规格(12 帧参数表)
- `docs/archive/path_a/distortion-investigation.md` § "2026-05-06 — Normalization Gate" — 半宽 vs 全宽 历史证据
- `docs/custom-postprocess-distortion-final-plan.md` § 2.3 / 2.4 / 2.5 — 当前 shader 公式
- 项目 `CLAUDE.md` — Git/P4 workflow + lanPC 远程执行约定

**Hard constraints (来自任务指令 + memory):**

1. **不建运行时模式开关**:证据指向哪个 normalization 公式,直接换;不引 enum / DISTORTION_NORM 之类 feature flag(memory `feedback_no_temporary_runtime_switches`,commit `1b2b925` 历史)。
2. **数据驱动**:所有结论必须用 12 帧反推,不预设答案。
3. **闭源约束**:d3 是闭源软件(memory `user_role_disguise`),不查 d3 源码、不建议物理 calibration(memory `feedback_no_physical_recalibration`)。
4. **UE 5.7 Python API 写之前先 grep 验证**(memory `feedback_verify_ue_python_api`),每次写 `unreal.X` 都要先在引擎源 / 项目代码确认存在。
5. **完成后不自动 commit**:整体 plan 跑完只汇报状态,等用户明确指令再 commit(memory `feedback_explicit_commit_only`)。

**Key data observation (sanity check 已完成 2026-05-07):** K=0 anchor 帧 over-scan margin 跟 focal 强相关:focal=24 margin≈0.000 / focal=30.302 margin≈0.103 / focal=50 margin≈0.259。说明 d3 的 1.5× over-scan 是 lens-FOV-driven,不是 sensor 固定缩放。这就是反推 normalization 公式的物理信号源。

---

## File Structure

### 新建文件

| Path | 责任 |
|---|---|
| `scripts/distortion_calibration/fit_normalization_candidates.py` | Fit harness 主脚本:载入 12 帧、跨 5 候选 normalization、emit JSON + Markdown report。 |
| `scripts/distortion_calibration/_fit_helpers.py` | 共享工具:`parse_disguise_next_filename` / `over_scan_corrected_source_uv` / `candidate_normalization_factor` / `forward_brown_conrady` / `format_stats`。 |
| `scripts/distortion_calibration/_self_test_fit_normalization.py` | 离线自测:合成 K1=+0.3 distortion via cv2.remap + 已知 normalization,跑 fit 期望选回正确候选(synthetic ground-truth gate)。 |
| `validation_results/normalization_gate/<timestamp>_focal_sweep_report.{json,md}` | 焦距 sweep × K1 fit 报告。 |
| `validation_results/normalization_gate/<timestamp>_k2_k3_report.{json,md}` | K2 / K3 单变量 fit 报告。 |
| `validation_results/normalization_gate/<timestamp>_center_shift_report.{json,md}` | centerShift 单位 / 符号 fit 报告。 |
| `validation_results/normalization_gate/<timestamp>_summary.md` | 跨三组 fit 的总结 + 决策(改不改 shader,改成什么)。 |

### 现有文件 — 视 fit 结论决定改不改

| Path | 改的条件 |
|---|---|
| `Content/Python/post_render_tool/distortion_math.py:212-216` | fit 结论与当前 `r.x = d.x; r.y = d.y / aspect` 不一致时改公式形态。 |
| `Content/Python/post_render_tool/build_distortion_material.py:60-68` | 同上,HLSL 块 `HLSL_CODE` 同步。 |
| `Content/Python/post_render_tool/tests/test_custom_postprocess_distortion_math.py` | Python reference 公式改变后,改/补单元测试。 |
| `<UEProject>/Plugins/post-render-tool/Content/Materials/M_PRT_OfficialSensorInverse.uasset`(lanPC) | shader 改变时通过 lanPC 远程 Python 重 build。 |
| `Content/Python/post_render_tool/tests/test_distortion_rational.py` | 仅在 distortion_math.py 公开签名改变时同步。 |
| `docs/custom-postprocess-distortion-final-plan.md` § 2.3-2.5 | 文档同步定型 normalization。 |
| `docs/archive/path_a/distortion-investigation.md` 末尾追加 § "2026-05-07 — 12-frame normalization fit" | 历史证据归档。 |

---

## Phase 1 — Fit Harness Foundation

### Task 1: `_fit_helpers.py` — 共享工具模块

**Files:**
- Create: `scripts/distortion_calibration/_fit_helpers.py`

- [ ] **Step 1: 写 helper 模块**

```python
# scripts/distortion_calibration/_fit_helpers.py
"""Shared helpers for normalization-candidate fit harness.

12-frame EXR (validation_results/disguise_next_data/) → reverse-engineered
d3 distortion formula. Each frame's filename encodes (focal_mm, K1/K2/K3,
centerShift_x_mm); we parse it once here.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np

# Reuse archived helpers (cwd-independent). The archive scripts already use
# the same OPENCV_IO_ENABLE_OPENEXR convention.
HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "archive"
sys.path.insert(0, str(ARCHIVE))
from _exr import read_uvprobe_exr, load_probe_meta  # noqa: E402
from analyze_renders import (  # noqa: E402
    VALID_UV_MAX,
    VALID_UV_MIN,
    detect_overscan_from_anchor,
)

# ── Filename parsing ──────────────────────────────────────────────────

# Set A: disguise_focal{24,30p302,50}_K1_{zero,p0p5}.exr
# Set B: disguise_focal30p302_{K2,K3}_p0p5.exr
# Set C: disguise_focal30p302_csx_{p,n}{0p05,0p10}.exr
_FOCAL_RE = re.compile(
    r"^disguise_focal(?P<focal>\d+(?:p\d+)?)"
    r"_(?P<axis>K1|K2|K3|csx)"
    r"(?:_(?P<sign>p|n)(?P<val>\d+(?:p\d+)?)|_zero)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FrameSpec:
    path: Path
    focal_mm: float
    axis: str          # "K1", "K2", "K3", "csx"
    value: float       # 0 for zero anchor; signed for non-zero
    is_anchor: bool


def _decode_p(s: str) -> float:
    return float(s.lower().replace("p", "."))


def parse_disguise_next_filename(path: Path) -> FrameSpec:
    m = _FOCAL_RE.match(path.stem)
    if not m:
        raise ValueError(f"cannot parse disguise_next filename: {path.name}")
    focal_mm = _decode_p(m.group("focal"))
    axis = m.group("axis").upper() if m.group("axis").lower() != "csx" else "csx"
    if m.group("val") is None:
        return FrameSpec(path, focal_mm, axis, 0.0, True)
    sign = +1.0 if m.group("sign").lower() == "p" else -1.0
    value = sign * _decode_p(m.group("val"))
    return FrameSpec(path, focal_mm, axis, value, False)


# ── EXR → corrected source pixel ──────────────────────────────────────

@dataclass(frozen=True)
class FrameSamples:
    """Per-frame valid-pixel sample set, all in pixel units (not normalized)."""
    output_x_px: np.ndarray
    output_y_px: np.ndarray
    source_x_px: np.ndarray
    source_y_px: np.ndarray
    overscan_factor: float
    overscan_margin: float


def load_frame_samples(
    spec: FrameSpec,
    *,
    width: int,
    height: int,
    rng: np.random.Generator,
    samples: int,
    anchor_overscan: tuple[float, float] | None = None,
) -> FrameSamples:
    """Read EXR, undo over-scan affine, sample N valid pixels.

    If `anchor_overscan` is provided, use it (frames in a focal group share
    one anchor's affine — guarantees delta-residual cancels common floor).
    Otherwise, detect from this frame.
    """
    R, G = read_uvprobe_exr(spec.path)
    if R.shape != (height, width):
        raise ValueError(f"{spec.path.name}: shape {R.shape} != {(height, width)}")
    if anchor_overscan is None:
        of, om = detect_overscan_from_anchor(R, G)
    else:
        of, om = anchor_overscan
    span = 1.0 - 2.0 * om
    R_corr = (R - om) / span
    G_corr = (G - om) / span

    valid = (
        (R > VALID_UV_MIN) & (R < VALID_UV_MAX) &
        (G > VALID_UV_MIN) & (G < VALID_UV_MAX)
    )
    valid_idx = np.flatnonzero(valid.ravel())
    if valid_idx.size == 0:
        raise RuntimeError(f"{spec.path.name}: no valid pixels")
    n = min(samples, int(valid_idx.size))
    sample = rng.choice(valid_idx, size=n, replace=False)
    ys, xs = np.unravel_index(sample, (height, width))
    out_x = xs.astype(np.float64) + 0.5
    out_y = ys.astype(np.float64) + 0.5
    src_x = R_corr[ys, xs] * width
    src_y = G_corr[ys, xs] * height
    return FrameSamples(out_x, out_y, src_x, src_y, of, om)


# ── Candidate normalization factors ───────────────────────────────────

def candidate_norm_factor(
    candidate: str,
    *,
    width_px: int,
    height_px: int,
    focal_mm: float,
    sensor_width_mm: float,
) -> float:
    """Return per-pixel normalization denominator (in pixels).

    Forward Brown-Conrady is `(src - c)/N = (out - c)/N · (1 + K · ((out-c)/N)²)`.
    The N cancels in `src - c = (out - c) · (1 + K · ((out-c)/N)²)`, so
    different candidates only differ in the K_eff value they imply.
    """
    if candidate == "full-width":
        return float(width_px)
    if candidate == "half-width":
        return float(width_px) / 2.0
    if candidate == "height":
        return float(height_px)
    if candidate == "diagonal":
        return float(np.hypot(width_px, height_px))
    if candidate == "focal-length":
        # Pinhole: fx_pixels = (focal_mm / sensor_width_mm) · width_px.
        return (focal_mm / sensor_width_mm) * float(width_px)
    raise ValueError(f"unknown candidate: {candidate!r}")


CANDIDATES: tuple[str, ...] = (
    "full-width",
    "focal-length",
    "diagonal",
    "height",
    "half-width",
)


# ── Forward Brown-Conrady predictor (pixel-space) ─────────────────────

def forward_brown_conrady_pixel(
    out_x_px: np.ndarray,
    out_y_px: np.ndarray,
    *,
    cx_px: float,
    cy_px: float,
    norm_px: float,
    k1: float,
    k2: float,
    k3: float,
) -> tuple[np.ndarray, np.ndarray]:
    dx = out_x_px - cx_px
    dy = out_y_px - cy_px
    rx = dx / norm_px
    ry = dy / norm_px
    r2 = rx * rx + ry * ry
    factor = k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
    src_x = out_x_px + factor * dx
    src_y = out_y_px + factor * dy
    return src_x, src_y


# ── Stats ─────────────────────────────────────────────────────────────

def format_stats(values_px: np.ndarray) -> dict:
    if values_px.size == 0:
        return {"n": 0, "median_px": float("nan"), "p95_px": float("nan"),
                "rms_px": float("nan"), "max_px": float("nan")}
    return {
        "n": int(values_px.size),
        "median_px": float(np.percentile(values_px, 50)),
        "p95_px": float(np.percentile(values_px, 95)),
        "rms_px": float(np.sqrt(np.mean(values_px * values_px))),
        "max_px": float(np.max(values_px)),
    }


# Module re-exports for unittest discovery
__all__ = [
    "CANDIDATES",
    "FrameSamples",
    "FrameSpec",
    "VALID_UV_MAX",
    "VALID_UV_MIN",
    "candidate_norm_factor",
    "format_stats",
    "forward_brown_conrady_pixel",
    "load_frame_samples",
    "parse_disguise_next_filename",
    "load_probe_meta",
]
```

- [ ] **Step 2: 跑 import smoke test**

Run:
```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration && \
.venv/bin/python -c "from _fit_helpers import CANDIDATES, parse_disguise_next_filename; \
from pathlib import Path; \
print(CANDIDATES); \
print(parse_disguise_next_filename(Path('disguise_focal30p302_K1_p0p5.exr'))); \
print(parse_disguise_next_filename(Path('disguise_focal24_K1_zero.exr'))); \
print(parse_disguise_next_filename(Path('disguise_focal30p302_csx_n0p10.exr')))"
```

Expected:
```
('full-width', 'focal-length', 'diagonal', 'height', 'half-width')
FrameSpec(path=PosixPath('disguise_focal30p302_K1_p0p5.exr'), focal_mm=30.302, axis='K1', value=0.5, is_anchor=False)
FrameSpec(path=PosixPath('disguise_focal24_K1_zero.exr'), focal_mm=24.0, axis='K1', value=0.0, is_anchor=True)
FrameSpec(path=PosixPath('disguise_focal30p302_csx_n0p10.exr'), focal_mm=30.302, axis='csx', value=-0.1, is_anchor=False)
```

---

### Task 2: `_self_test_fit_normalization.py` — synthetic ground-truth gate

**Files:**
- Create: `scripts/distortion_calibration/_self_test_fit_normalization.py`

- [ ] **Step 1: 写自测**

```python
"""Synthetic ground-truth gate for fit_normalization_candidates.

Generates a fake K1=+0.3 distortion via known full-width Brown-Conrady, runs
the fit harness, and asserts:
1. full-width candidate has lowest delta-residual.
2. fitted K1_eff matches +0.3 to within 1e-3.
3. focal-length candidate's K1_eff diverges (since it would require
   different K1_eff at different focals).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _fit_helpers import (  # noqa: E402
    CANDIDATES,
    candidate_norm_factor,
    forward_brown_conrady_pixel,
)


def _synth_disguise_frame(
    *,
    width: int,
    height: int,
    focal_mm: float,
    sensor_width_mm: float,
    k1: float,
    overscan_margin: float,
    truth_norm: str,
) -> np.ndarray:
    """Build a synthetic Disguise output: R = corrected source U, G = source V.

    The input plate is identity; truth distortion uses `truth_norm` so we
    know which candidate the fit harness should pick.
    """
    cx = width / 2.0
    cy = height / 2.0
    norm = candidate_norm_factor(
        truth_norm,
        width_px=width,
        height_px=height,
        focal_mm=focal_mm,
        sensor_width_mm=sensor_width_mm,
    )
    xs = np.arange(width, dtype=np.float64) + 0.5
    ys = np.arange(height, dtype=np.float64) + 0.5
    out_x, out_y = np.meshgrid(xs, ys)
    src_x, src_y = forward_brown_conrady_pixel(
        out_x, out_y, cx_px=cx, cy_px=cy, norm_px=norm, k1=k1, k2=0, k3=0,
    )
    span = 1.0 - 2.0 * overscan_margin
    R = (src_x / width) * span + overscan_margin
    G = (src_y / height) * span + overscan_margin
    img = np.zeros((height, width, 3), dtype=np.float32)
    img[..., 2] = R.astype(np.float32)
    img[..., 1] = G.astype(np.float32)
    return img


class FitGroundTruthTest(unittest.TestCase):
    def test_truth_normalization_recovered(self):
        # Synthesize 3 focal × K1 sweep using truth = full-width.
        width, height = 3840, 2160
        sensor_w = 35.0
        truth_k1 = 0.3
        truth_norm = "full-width"
        focals = [24.0, 30.302, 50.0]
        # Each focal gets a different over-scan margin (matches d3 behavior)
        margins = {24.0: 0.001, 30.302: 0.103, 50.0: 0.259}

        # Run harness on a tempdir of synthetic EXRs; assert verdict matches truth.
        # Implementation: import fit_normalization_candidates after task 3 lands,
        # invoke its `evaluate_focal_sweep(...)`, and verify:
        #   - report["winner"] == "full-width"
        #   - abs(report["candidates"]["full-width"]["k1_eff_consistency"]) < 1e-3
        #   - report["candidates"]["focal-length"]["k1_eff_spread"] > 1e-2
        # (The exact attribute names match the report schema in Task 3.)
        self.skipTest("enable after Task 3 lands fit_normalization_candidates harness")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑(预期 skip)**

Run: `cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration && .venv/bin/python -m unittest _self_test_fit_normalization.py -v`
Expected: `OK (skipped=1)` — synth gate 标记为 skip,等 Task 3 后回填激活。这个 step 只验证 import 链没断、helper 模块能 load。

---

## Phase 2 — Focal Sweep Fit (Set A)

### Task 3: `fit_normalization_candidates.py` — fit harness 主体

**Files:**
- Create: `scripts/distortion_calibration/fit_normalization_candidates.py`
- Modify: `scripts/distortion_calibration/_self_test_fit_normalization.py:75-83` (取消 skipTest,激活断言)

- [ ] **Step 1: 写 fit harness**

```python
"""Fit harness — reverse-engineer d3 distortion normalization.

Inputs:
  validation_results/disguise_next_data/{focal_length_sweep,k2_k3_sweep,
  center_shift_sweep}/*.exr

Output:
  validation_results/normalization_gate/<timestamp>_focal_sweep_report.{json,md}
  validation_results/normalization_gate/<timestamp>_k2_k3_report.{json,md}
  validation_results/normalization_gate/<timestamp>_center_shift_report.{json,md}
  validation_results/normalization_gate/<timestamp>_summary.md

Fit logic (focal sweep, 6 frames):

For each candidate normalization NORM_cand ∈ {full-width, focal-length,
diagonal, height, half-width}:

  1. Per-focal pair (K=0, K=+0.5): compute over-scan affine from K=0 anchor;
     apply to both. Take 200k random valid pixels.
  2. Compute predicted source pixel using forward Brown-Conrady with
     K1 = d3-reported value (+0.5) and r = (out - c) / NORM_cand.
  3. delta_residual = |actual_dr − predicted_dr| where dr = source_pixel − output_pixel.
     This cancels the over-scan affine common to anchor and frame.
  4. Aggregate: per-focal p95(delta_residual), and `k1_eff_inferred`
     (least-squares fit `dr_actual / dx ≈ K1_eff · r²`).
  5. Cross-focal consistency: `k1_eff_spread` = stddev over 3 focals.

Verdict ranking:
  - Lower per-focal p95 = better fit at THAT focal.
  - Lower cross-focal `k1_eff_spread` = candidate's r definition matches d3's.
  - WINNER = candidate with lowest p95 AND k1_eff matches d3 K1 = +0.5
    within tolerance (default 5e-3).

K2/K3 sweep uses the WINNER from focal sweep; verifies same-normalization
hypothesis (K2/K3 should give k_eff close to d3-reported value at focal=30.302).

centerShift sweep verifies the existing CenterUV formula:
    CenterU = 0.5 + centerShiftMM.x / sensor_width_mm
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _fit_helpers import (  # noqa: E402
    CANDIDATES,
    FrameSpec,
    candidate_norm_factor,
    format_stats,
    forward_brown_conrady_pixel,
    load_frame_samples,
    load_probe_meta,
    parse_disguise_next_filename,
)

DATA_ROOT_DEFAULT = Path("validation_results/disguise_next_data")
OUT_ROOT_DEFAULT = Path("validation_results/normalization_gate")
SAMPLES_PER_FRAME = 200_000
SENSOR_WIDTH_MM_DEFAULT = 35.0  # d3 cinema sensor convention; verified below
ASPECT_DEFAULT = 16.0 / 9.0
K1_TOL = 5e-3                   # k1_eff agreement tolerance
SUB_PIXEL_FLOOR_PX = 0.20       # EXR float quantization floor we expect


def _scan_dir(directory: Path) -> list[FrameSpec]:
    if not directory.is_dir():
        raise FileNotFoundError(f"missing dir: {directory}")
    out: list[FrameSpec] = []
    for path in sorted(directory.glob("*.exr")):
        out.append(parse_disguise_next_filename(path))
    return out


def _fit_k_eff(
    out_x: np.ndarray, out_y: np.ndarray,
    src_x: np.ndarray, src_y: np.ndarray,
    *,
    cx: float, cy: float, norm: float,
) -> float:
    """LSQ fit: src - out = k1_eff · ((out - c)/norm)² · (out - c)."""
    dx = out_x - cx
    dy = out_y - cy
    r2 = (dx / norm) ** 2 + (dy / norm) ** 2
    # stack 2D: (src - out) ≈ k1_eff · r² · (out - c)
    a = np.concatenate([r2 * dx, r2 * dy])
    b = np.concatenate([src_x - out_x, src_y - out_y])
    return float(np.dot(a, b) / np.dot(a, a))


def evaluate_focal_sweep(
    *,
    data_root: Path,
    width: int, height: int,
    sensor_width_mm: float,
    samples_per_frame: int = SAMPLES_PER_FRAME,
    seed: int = 42,
) -> dict:
    """Evaluate Set A — 6 frames, 3 focals × {K1=0, K1=+0.5}."""
    specs = _scan_dir(data_root / "focal_length_sweep")
    rng = np.random.default_rng(seed)
    cx, cy = width / 2.0, height / 2.0

    # Group by focal; each focal has one anchor + one K1=+0.5 frame
    focals = sorted({s.focal_mm for s in specs})
    per_focal_data: dict[float, dict] = {}
    for f in focals:
        anchor = next(s for s in specs if s.focal_mm == f and s.is_anchor and s.axis == "K1")
        non_zero = next(s for s in specs if s.focal_mm == f and not s.is_anchor and s.axis == "K1")
        a = load_frame_samples(anchor, width=width, height=height,
                               rng=rng, samples=samples_per_frame)
        nz = load_frame_samples(non_zero, width=width, height=height,
                                rng=rng, samples=samples_per_frame,
                                anchor_overscan=(a.overscan_factor, a.overscan_margin))
        per_focal_data[f] = {
            "anchor_spec": anchor, "frame_spec": non_zero,
            "anchor_samples": a, "frame_samples": nz,
        }

    candidate_results: dict[str, dict] = {}
    for cand in CANDIDATES:
        per_focal = []
        k1_eff_list = []
        residual_p95_list = []
        for f in focals:
            d = per_focal_data[f]
            a = d["anchor_samples"]
            nz = d["frame_samples"]
            norm = candidate_norm_factor(
                cand, width_px=width, height_px=height,
                focal_mm=f, sensor_width_mm=sensor_width_mm,
            )
            # Predicted dr at K1=+0.5
            pred_x, pred_y = forward_brown_conrady_pixel(
                nz.output_x_px, nz.output_y_px,
                cx_px=cx, cy_px=cy, norm_px=norm,
                k1=d["frame_spec"].value, k2=0, k3=0,
            )
            # Actual dr (delta-residual cancels common floor with anchor pair)
            actual_dr_x = nz.source_x_px - a.source_x_px
            actual_dr_y = nz.source_y_px - a.source_y_px
            pred_dr_x = pred_x - nz.output_x_px
            pred_dr_y = pred_y - nz.output_y_px
            err = np.hypot(actual_dr_x - pred_dr_x, actual_dr_y - pred_dr_y)
            stats = format_stats(err)
            # Inferred K1_eff at this candidate's r definition
            k_eff = _fit_k_eff(
                nz.output_x_px, nz.output_y_px,
                a.source_x_px + actual_dr_x, a.source_y_px + actual_dr_y,
                cx=cx, cy=cy, norm=norm,
            )
            per_focal.append({
                "focal_mm": f,
                "norm_px": norm,
                "k1_eff_inferred": k_eff,
                "delta_residual": stats,
            })
            k1_eff_list.append(k_eff)
            residual_p95_list.append(stats["p95_px"])
        candidate_results[cand] = {
            "per_focal": per_focal,
            "k1_eff_mean": float(np.mean(k1_eff_list)),
            "k1_eff_spread": float(np.std(k1_eff_list, ddof=0)),
            "p95_max_across_focals": float(np.max(residual_p95_list)),
        }

    # Pick winner: smallest p95_max, AND k1_eff_spread < tol, AND k1_eff_mean ≈ +0.5
    target_k1 = 0.5
    ranked = sorted(
        candidate_results.items(),
        key=lambda kv: (kv[1]["p95_max_across_focals"], kv[1]["k1_eff_spread"]),
    )
    winner = None
    for name, r in ranked:
        if (r["k1_eff_spread"] < K1_TOL
                and abs(r["k1_eff_mean"] - target_k1) < K1_TOL
                and r["p95_max_across_focals"] < SUB_PIXEL_FLOOR_PX * 5):
            winner = name
            break
    if winner is None:
        winner = ranked[0][0]  # best-effort, but fail criteria
    verdict = "GO" if winner == ranked[0][0] and ranked[0][1]["k1_eff_spread"] < K1_TOL else "REVIEW"

    return {
        "gate": "focal_sweep",
        "data_root": str(data_root / "focal_length_sweep"),
        "width": width, "height": height, "sensor_width_mm": sensor_width_mm,
        "candidates": candidate_results,
        "winner": winner,
        "verdict": verdict,
        "k1_target": target_k1,
        "k1_tolerance": K1_TOL,
    }


def evaluate_k2_k3(
    *,
    data_root: Path,
    width: int, height: int,
    sensor_width_mm: float,
    winner_norm: str,
    samples_per_frame: int = SAMPLES_PER_FRAME,
    seed: int = 43,
) -> dict:
    """Set B — verify K2/K3 use the same normalization picked by Set A.

    Anchor: re-use focal_length_sweep/disguise_focal30p302_K1_zero.exr (same focal).
    Each non-zero frame: only one of K2/K3 is set to +0.5, others zero.
    Predict dr using winner_norm and d3-reported K2/K3; report delta-residual
    + inferred k_eff for that axis.
    """
    rng = np.random.default_rng(seed)
    specs = _scan_dir(data_root / "k2_k3_sweep")
    anchor_spec = parse_disguise_next_filename(
        data_root / "focal_length_sweep" / "disguise_focal30p302_K1_zero.exr"
    )
    a = load_frame_samples(anchor_spec, width=width, height=height,
                           rng=rng, samples=samples_per_frame)
    norm = candidate_norm_factor(
        winner_norm, width_px=width, height_px=height,
        focal_mm=anchor_spec.focal_mm, sensor_width_mm=sensor_width_mm,
    )
    cx, cy = width / 2.0, height / 2.0
    rows = []
    for s in specs:
        if s.is_anchor:
            continue
        nz = load_frame_samples(s, width=width, height=height,
                                rng=rng, samples=samples_per_frame,
                                anchor_overscan=(a.overscan_factor, a.overscan_margin))
        k1, k2, k3 = 0.0, 0.0, 0.0
        if s.axis == "K2":
            k2 = s.value
        elif s.axis == "K3":
            k3 = s.value
        pred_x, pred_y = forward_brown_conrady_pixel(
            nz.output_x_px, nz.output_y_px,
            cx_px=cx, cy_px=cy, norm_px=norm,
            k1=k1, k2=k2, k3=k3,
        )
        # Same delta-residual scheme as Set A
        actual_dr_x = nz.source_x_px - a.source_x_px
        actual_dr_y = nz.source_y_px - a.source_y_px
        pred_dr_x = pred_x - nz.output_x_px
        pred_dr_y = pred_y - nz.output_y_px
        err = np.hypot(actual_dr_x - pred_dr_x, actual_dr_y - pred_dr_y)
        # Per-axis inferred coefficient: src - out ≈ k_eff · r^(2n) · (out - c)
        # n = 2 for K2 (r⁴), n = 3 for K3 (r⁶)
        order = {"K2": 2, "K3": 3}[s.axis]
        dx = nz.output_x_px - cx
        dy = nz.output_y_px - cy
        r2 = (dx / norm) ** 2 + (dy / norm) ** 2
        weight = r2 ** order
        a_vec = np.concatenate([weight * dx, weight * dy])
        b_vec = np.concatenate([actual_dr_x, actual_dr_y])
        k_eff = float(np.dot(a_vec, b_vec) / np.dot(a_vec, a_vec))
        rows.append({
            "file": s.path.name,
            "axis": s.axis,
            "value_d3": s.value,
            "k_eff_inferred": k_eff,
            "delta_residual": format_stats(err),
        })
    spread_ok = all(abs(r["k_eff_inferred"] - r["value_d3"]) < K1_TOL for r in rows)
    p95_ok = all(r["delta_residual"]["p95_px"] < SUB_PIXEL_FLOOR_PX * 5 for r in rows)
    verdict = "GO" if spread_ok and p95_ok else "REVIEW"
    return {
        "gate": "k2_k3",
        "winner_normalization": winner_norm,
        "frames": rows,
        "verdict": verdict,
    }


def evaluate_center_shift(
    *,
    data_root: Path,
    width: int, height: int,
    sensor_width_mm: float,
    samples_per_frame: int = SAMPLES_PER_FRAME,
    seed: int = 44,
) -> dict:
    """Set C — verify CenterU = 0.5 + csx_mm / sensor_width_mm.

    K1=K2=K3=0 in this set; the only effect is principal-point translation.
    Per-frame: median(src_x − anchor_src_x) should equal expected_dx_px =
    csx_mm / sensor_width_mm · width_px (with sign convention).
    """
    rng = np.random.default_rng(seed)
    specs = _scan_dir(data_root / "center_shift_sweep")
    anchor_spec = parse_disguise_next_filename(
        data_root / "focal_length_sweep" / "disguise_focal30p302_K1_zero.exr"
    )
    a = load_frame_samples(anchor_spec, width=width, height=height,
                           rng=rng, samples=samples_per_frame)
    rows = []
    for s in specs:
        if s.is_anchor:
            continue
        nz = load_frame_samples(s, width=width, height=height,
                                rng=rng, samples=samples_per_frame,
                                anchor_overscan=(a.overscan_factor, a.overscan_margin))
        median_dx_px = float(np.median(nz.source_x_px - a.source_x_px))
        median_dy_px = float(np.median(nz.source_y_px - a.source_y_px))
        expected_dx_px = s.value / sensor_width_mm * width
        plus_err = abs(median_dx_px - expected_dx_px)
        minus_err = abs(median_dx_px + expected_dx_px)
        rows.append({
            "file": s.path.name,
            "csx_mm": s.value,
            "median_dx_px": median_dx_px,
            "median_dy_px": median_dy_px,
            "expected_plus_dx_px": expected_dx_px,
            "plus_formula_err_px": plus_err,
            "minus_formula_err_px": minus_err,
            "best_sign": "+formula" if plus_err <= minus_err else "-formula",
        })
    sign_ok = all(r["best_sign"] == "+formula" for r in rows)
    err_ok = all(r["plus_formula_err_px"] < 1.0 for r in rows)
    verdict = "GO" if sign_ok and err_ok else "REVIEW"
    return {"gate": "center_shift", "frames": rows, "verdict": verdict}


# ── Markdown rendering ────────────────────────────────────────────────

def render_focal_md(report: dict) -> str:
    lines = [
        "# Focal Sweep × K1 Normalization Fit",
        "",
        f"- Data: `{report['data_root']}`",
        f"- Verdict: **{report['verdict']}** — winner = `{report['winner']}`",
        f"- K1 target: {report['k1_target']:+.3f}, tol = {report['k1_tolerance']}",
        "",
        "| candidate | k1_eff_mean | k1_eff_spread | p95_max_px |",
        "|---|---:|---:|---:|",
    ]
    ranked = sorted(report["candidates"].items(),
                    key=lambda kv: kv[1]["p95_max_across_focals"])
    for name, r in ranked:
        lines.append(
            f"| `{name}` | {r['k1_eff_mean']:+.4f} | {r['k1_eff_spread']:.4f} | "
            f"{r['p95_max_across_focals']:.3f} |"
        )
    lines.extend(["", "## Per-focal breakdown", "",
                  "| candidate | focal mm | k1_eff | p95 px | rms px | max px |",
                  "|---|---:|---:|---:|---:|---:|"])
    for name, r in report["candidates"].items():
        for pf in r["per_focal"]:
            d = pf["delta_residual"]
            lines.append(
                f"| `{name}` | {pf['focal_mm']} | {pf['k1_eff_inferred']:+.4f} | "
                f"{d['p95_px']:.3f} | {d['rms_px']:.3f} | {d['max_px']:.3f} |"
            )
    return "\n".join(lines) + "\n"


def render_k2_k3_md(report: dict) -> str:
    lines = [
        "# K2 / K3 Single-Variable Sweep",
        "",
        f"- Verdict: **{report['verdict']}** (using `{report['winner_normalization']}` from focal sweep)",
        "",
        "| frame | axis | d3 value | inferred k_eff | p95 px | rms px |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for r in report["frames"]:
        d = r["delta_residual"]
        lines.append(
            f"| `{r['file']}` | {r['axis']} | {r['value_d3']:+.3f} | "
            f"{r['k_eff_inferred']:+.4f} | {d['p95_px']:.3f} | {d['rms_px']:.3f} |"
        )
    return "\n".join(lines) + "\n"


def render_center_shift_md(report: dict) -> str:
    lines = [
        "# CenterShift Sweep",
        "",
        f"- Verdict: **{report['verdict']}**",
        "- Formula tested: `CenterU = 0.5 + csx_mm / sensor_width_mm`",
        "",
        "| frame | csx mm | median dx px | expected dx px | +err px | -err px | best sign |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in report["frames"]:
        lines.append(
            f"| `{r['file']}` | {r['csx_mm']:+.3f} | {r['median_dx_px']:+.3f} | "
            f"{r['expected_plus_dx_px']:+.3f} | {r['plus_formula_err_px']:.3f} | "
            f"{r['minus_formula_err_px']:.3f} | {r['best_sign']} |"
        )
    return "\n".join(lines) + "\n"


def render_summary_md(focal: dict, k2k3: dict, csx: dict) -> str:
    return "\n".join([
        "# Distortion Normalization Fit — Summary",
        "",
        f"- Focal sweep verdict: **{focal['verdict']}**, winner = `{focal['winner']}`",
        f"- K2/K3 sweep verdict: **{k2k3['verdict']}** (using winner normalization)",
        f"- CenterShift sweep verdict: **{csx['verdict']}**",
        "",
        "## Decision",
        "",
        f"d3 internal normalization is `{focal['winner']}`. ",
        "Compare against current shader formula in "
        "`Content/Python/post_render_tool/distortion_math.py:212-216` and "
        "`Content/Python/post_render_tool/build_distortion_material.py:60-68`. "
        "If they match (current shader is `full-width` UV-space), commit only the "
        "report; otherwise update the HLSL + Python reference + remote material asset.",
        "",
    ]) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", type=Path, default=DATA_ROOT_DEFAULT)
    p.add_argument("--out-root", type=Path, default=OUT_ROOT_DEFAULT)
    p.add_argument("--probe-truth", type=Path, default=None,
                   help="Path to uv_probe_truth_3840x2160.npz (defaults via load_probe_meta)")
    p.add_argument("--sensor-width-mm", type=float, default=SENSOR_WIDTH_MM_DEFAULT)
    p.add_argument("--samples-per-frame", type=int, default=SAMPLES_PER_FRAME)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    pw, ph, cw, ch = load_probe_meta(args.probe_truth)
    if (pw, ph) != (cw, ch):
        raise SystemExit(f"probe / camera size mismatch: probe={pw}x{ph}, camera={cw}x{ch}")
    width, height = cw, ch
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    args.out_root.mkdir(parents=True, exist_ok=True)

    focal = evaluate_focal_sweep(
        data_root=args.data_root, width=width, height=height,
        sensor_width_mm=args.sensor_width_mm,
        samples_per_frame=args.samples_per_frame, seed=args.seed,
    )
    (args.out_root / f"{timestamp}_focal_sweep_report.json").write_text(
        json.dumps(focal, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out_root / f"{timestamp}_focal_sweep_report.md").write_text(
        render_focal_md(focal), encoding="utf-8")

    k2k3 = evaluate_k2_k3(
        data_root=args.data_root, width=width, height=height,
        sensor_width_mm=args.sensor_width_mm,
        winner_norm=focal["winner"],
        samples_per_frame=args.samples_per_frame, seed=args.seed + 1,
    )
    (args.out_root / f"{timestamp}_k2_k3_report.json").write_text(
        json.dumps(k2k3, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out_root / f"{timestamp}_k2_k3_report.md").write_text(
        render_k2_k3_md(k2k3), encoding="utf-8")

    csx = evaluate_center_shift(
        data_root=args.data_root, width=width, height=height,
        sensor_width_mm=args.sensor_width_mm,
        samples_per_frame=args.samples_per_frame, seed=args.seed + 2,
    )
    (args.out_root / f"{timestamp}_center_shift_report.json").write_text(
        json.dumps(csx, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out_root / f"{timestamp}_center_shift_report.md").write_text(
        render_center_shift_md(csx), encoding="utf-8")

    summary = render_summary_md(focal, k2k3, csx)
    (args.out_root / f"{timestamp}_summary.md").write_text(summary, encoding="utf-8")

    print(f"focal sweep: verdict={focal['verdict']} winner={focal['winner']}")
    print(f"k2/k3:       verdict={k2k3['verdict']}")
    print(f"centerShift: verdict={csx['verdict']}")
    print(f"reports under {args.out_root}, timestamp={timestamp}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 激活 Task 2 自测的真实断言**

Edit `_self_test_fit_normalization.py` 末尾的 `FitGroundTruthTest.test_truth_normalization_recovered`,把 `self.skipTest(...)` 整段替换成:

```python
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            (data_root / "focal_length_sweep").mkdir()
            (data_root / "k2_k3_sweep").mkdir()
            (data_root / "center_shift_sweep").mkdir()
            for f in focals:
                anchor = _synth_disguise_frame(
                    width=width, height=height,
                    focal_mm=f, sensor_width_mm=sensor_w,
                    k1=0.0, overscan_margin=margins[f],
                    truth_norm=truth_norm,
                )
                nonzero = _synth_disguise_frame(
                    width=width, height=height,
                    focal_mm=f, sensor_width_mm=sensor_w,
                    k1=truth_k1, overscan_margin=margins[f],
                    truth_norm=truth_norm,
                )
                fcal_str = str(f).replace(".", "p")
                cv2.imwrite(
                    str(data_root / "focal_length_sweep" / f"disguise_focal{fcal_str}_K1_zero.exr"),
                    anchor,
                )
                cv2.imwrite(
                    str(data_root / "focal_length_sweep" / f"disguise_focal{fcal_str}_K1_p0p3.exr"),
                    nonzero,
                )
            # Re-import (after Task 3 lands) and run focal-only path
            from fit_normalization_candidates import evaluate_focal_sweep
            report = evaluate_focal_sweep(
                data_root=data_root, width=width, height=height,
                sensor_width_mm=sensor_w, samples_per_frame=50_000, seed=0,
            )
            self.assertEqual(report["winner"], truth_norm)
            self.assertLess(
                abs(report["candidates"][truth_norm]["k1_eff_mean"] - truth_k1),
                1e-3,
            )
            self.assertLess(report["candidates"][truth_norm]["k1_eff_spread"], 1e-3)
            self.assertGreater(
                report["candidates"]["focal-length"]["k1_eff_spread"], 1e-2,
            )
```

Note: `_FOCAL_RE` already accepts `K1_p0p3` (regex matches arbitrary `\d+(?:p\d+)?`).

- [ ] **Step 3: 跑自测验证 fit harness 在 synthetic ground-truth 上正确**

Run: `cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration && .venv/bin/python -m unittest _self_test_fit_normalization.py -v`
Expected: `OK` — synth-truth 用 full-width,fit harness 应选回 full-width,inferred K1=+0.3 ± 1e-3,focal-length 候选的 spread > 1e-2(因为它跟 focal 走但合成数据没 focal 依赖)。

---

### Task 4: 跑真实 12 帧 fit + 看 focal sweep 结果

**Files:**
- Run only.

- [ ] **Step 1: 跑 fit harness**

Run:
```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool && \
scripts/distortion_calibration/.venv/bin/python \
  scripts/distortion_calibration/fit_normalization_candidates.py
```

Expected output 形状(实际数值由数据决定):
```
focal sweep: verdict=GO winner=full-width      # 或 focal-length / 其他
k2/k3:       verdict=GO
centerShift: verdict=GO
reports under validation_results/normalization_gate, timestamp=YYYYMMDD_HHMMSS
```

- [ ] **Step 2: 读 `<ts>_focal_sweep_report.md`**

Open `validation_results/normalization_gate/<timestamp>_focal_sweep_report.md`。看:

- 哪个候选 `k1_eff_spread` < 5e-3 且 `k1_eff_mean` ≈ +0.5(target)
- 哪个候选 `p95_max_across_focals` 最低(应当跟 spread 最低的同一个)
- 当前 shader 用 `full-width` —— **如果它是赢家**,跳到 Task 7;**如果是别人**,继续 Task 5/6 验证再改。

记录关键数字:每个候选的 `k1_eff_mean` / `k1_eff_spread` / `p95_max`,winner 名字。这些是 Task 7 决策的基础。

---

## Phase 3 — K2/K3 + centerShift Verification

### Task 5: 看 K2/K3 报告

**Files:**
- Run only.

- [ ] **Step 1: 读 `<ts>_k2_k3_report.md`**

Open `validation_results/normalization_gate/<timestamp>_k2_k3_report.md`。看:

- `K2_p0p5` 推出来的 `k_eff_inferred` 是不是 ≈ +0.5(同 normalization 假说)
- `K3_p0p5` 同上
- `delta_residual.p95` 是不是 < 1.0 px(亚像素)

如果两个都 GO:K2/K3 跟 K1 用同 normalization,这是同一个公式形态。
如果其中一个 k_eff 跟 d3 报告值差很大 / p95 异常高:K2 或 K3 用了不同 normalization,需要在 summary 里明确标注、追加 fit 候选。

- [ ] **Step 2: 决策记录**

把"K2/K3 是否同 normalization"写入 `<ts>_summary.md`(已由 harness 自动生成,可手动追加备注)。

### Task 6: 看 centerShift 报告

**Files:**
- Run only.

- [ ] **Step 1: 读 `<ts>_center_shift_report.md`**

Open `validation_results/normalization_gate/<timestamp>_center_shift_report.md`。看:

- 4 帧的 `best_sign` 是不是都是 `+formula`(确认当前 `CenterU = 0.5 + csx/sensor_w` 符号正确)
- `plus_formula_err_px` < 1.0 px(单位正确)

如果 4 帧都 `+formula` 且 err < 1.0 px:当前 shader CenterUV 公式正确,不改。
如果 4 帧都 `-formula`:符号反了,需要在 shader 把 CenterU 公式改成 `0.5 - csx/sensor_w`。
如果数值差较大:单位约定不对(可能 csx 是 sensor_height 而非 sensor_width),需要在 fit harness 里换分母重跑。

---

## Phase 4 — Decision + Shader Update (条件性)

### Task 7: 比对 fit 结论 vs 当前 shader,决定改不改

**Files:**
- Read: `Content/Python/post_render_tool/distortion_math.py:212-216`(当前 K-formula)
- Read: `Content/Python/post_render_tool/build_distortion_material.py:60-68`(HLSL)

- [ ] **Step 1: 列出当前 shader 公式**

```python
# distortion_math.py:212-216  (Path C UV-space reference)
rx = dx              # = d.x
ry = dy / aspect     # = d.y / aspect  ← UV 已自带 1/W normalization
r2 = rx * rx + ry * ry
factor = k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
```

UV-space 等价 pixel-space `r_x = (px - cx) / W, r_y = (py - cy) / W`,即 `full-width` 候选。

- [ ] **Step 2: 对照 fit 结论决策**

| Focal sweep winner | K2/K3 verdict | csx verdict | 决策 |
|---|---|---|---|
| `full-width` | GO | GO | ✅ 当前 shader 正确,跳到 Task 10(只 commit 报告 + 文档)。 |
| `full-width` | REVIEW | * | K2/K3 normalization 跟 K1 不同 → Task 8a 单独处理 K2/K3 公式。 |
| `full-width` | * | REVIEW | csx 单位/符号错 → Task 8a 改 CenterUV 公式。 |
| `focal-length` / 其他 | * | * | Task 8a + Task 8b + Task 9 全套 shader 改。 |

把决策写入 `validation_results/normalization_gate/<timestamp>_summary.md`。

---

### Task 8a (条件): 改 Python reference 公式 + 单元测试

> **触发条件**:Task 7 决策需要改 shader 公式。

**Files:**
- Modify: `Content/Python/post_render_tool/distortion_math.py:212-216`(`official_sensor_inverse_uv` 主体)
- Modify: `Content/Python/post_render_tool/build_distortion_material.py:60-68`(`HLSL_CODE` 字符串)
- Modify: `Content/Python/post_render_tool/tests/test_custom_postprocess_distortion_math.py`(补回归测试)

- [ ] **Step 1: 改 Python reference**(示例:winner = `focal-length`)

把 `distortion_math.py:212-213` 改成:

```python
    # Normalization 来自 2026-05-07 12-frame fit (validation_results/normalization_gate/<ts>_summary.md)
    # winner = focal-length: r = (px - cx) / fx_pixels;
    # UV-space 等价: r = d × (W / fx_pixels) = d × sensor_width_mm / focal_mm
    # 通过 caller 传 norm_scale = sensor_width_mm / focal_mm 进来,函数签名加 keyword arg。
    norm_scale = focal_mm / sensor_width_mm  # caller 算好,这里只用
    rx = dx * norm_scale
    ry = (dy / aspect) * norm_scale
```

并把 `def official_sensor_inverse_uv(...)` 函数签名加上 `norm_scale: float`(如有需要)。**具体改法由 fit winner 决定**——上面是示例。如果 winner 仍是 full-width,跳过本 task。

- [ ] **Step 2: 改 HLSL 块**(同步 Python reference)

把 `build_distortion_material.py:60-68` 的 `HLSL_CODE` 改到跟 Python reference 一字一致。如果新公式需要新 Material parameter(比如 `NormScale`),还要:
- 加进 `CUSTOM_INPUT_NAMES`(line 83)
- 加进 `LAYOUT`(line 87)
- 在 `_make_scalar` 调用处新建参数节点
- 在 `mel.connect_material_expressions` 处接线

- [ ] **Step 3: 改单元测试**

把 `test_custom_postprocess_distortion_math.py` 里所有 `official_sensor_inverse_uv(...)` 调用补上新参数,然后加一个回归 case:用 12 帧 fit 出来的 `k1_eff` + 对应 normalization 跑一帧 prediction,断言跟存档的 expected source UV 一致(亚像素)。

- [ ] **Step 4: 跑单元测试**

Run:
```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python && \
python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -v
```
Expected: 所有 test PASS。

---

### Task 8b (条件): lanPC 远程 rebuild Material asset

> **触发条件**:Task 8a 改了 HLSL_CODE 或 material parameter 列表。

**Files:**
- Read remote: `E:\RenderStream Projects\test_0311\Plugins\post-render-tool\Content\Materials\M_PRT_OfficialSensorInverse.uasset`

- [ ] **Step 1: SCP 改后的 build_distortion_material.py 到 lanPC**

Run:
```bash
scp /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python/post_render_tool/build_distortion_material.py \
  lanpc:'E:/RenderStream\ Projects/test_0311/Plugins/post-render-tool/Content/Python/post_render_tool/build_distortion_material.py'
```

> 项目实际 plugin 部署路径在 lanPC 的 UE Project 下(`E:\RenderStream Projects\test_0311\Plugins\post-render-tool\`)。先 verify 路径再 scp:`echo 'Test-Path "E:\RenderStream Projects\test_0311\Plugins\post-render-tool\Content\Python\post_render_tool\build_distortion_material.py"' | ssh lanpc powershell -Command -`。

- [ ] **Step 2: 写 UE remote bridge driver,远程 rebuild material**

Create `/tmp/rebuild_material.py` 本地:

```python
import unreal
from post_render_tool import build_distortion_material as bdm

asset_path = bdm.FULL_ASSET_PATH
existing = unreal.EditorAssetLibrary.does_asset_exist(asset_path)
print(f"asset_exists_before={existing}")

if existing:
    ok = unreal.EditorAssetLibrary.delete_asset(asset_path)
    print(f"deleted={ok}")

bdm.run_build()
print(f"rebuilt={unreal.EditorAssetLibrary.does_asset_exist(asset_path)}")
```

> **API check before running**:`grep -rn "delete_asset\|does_asset_exist" /Users/bip.lan/AIWorkspace/vp/UnrealEngine/Engine/Plugins/Experimental/PythonScriptPlugin/` to confirm signatures (memory `feedback_verify_ue_python_api`).

- [ ] **Step 3: SCP + 远程跑**

Run:
```bash
scp /tmp/rebuild_material.py lanpc:C:/temp/ue-remote/rebuild_material.py
ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/rebuild_material.py'
```

Expected:
```
asset_exists_before=True
deleted=True
rebuilt=True
```

如果 rebuild 失败,**不要**继续 Task 9。回到 Task 8a 检查 HLSL / parameter 名字是不是有 typo。

---

### Task 9 (条件): take_4 production diff regression

> **触发条件**:Task 8b 改了远程 material asset。

**Files:**
- Run only.

- [ ] **Step 1: 远程 MRQ 重渲 take_4 frame**

记下当前 baseline `valid_p95 = 0.1255`(`production_diff_frame2_vs_seq0.json`)。

写 `/tmp/render_take4_frame.py`(MRQ remote 触发,**先 verify** `unreal.MoviePipelineQueue` 在项目代码里怎么用 —— grep 现有 `path_c_production_render.json` 旁边的 production trigger 脚本看怎么写的,不要凭印象写)。

```bash
grep -rn "MoviePipelineQueue\|MoviePipelineLibrary\|MoviePipelineEditorLibrary" /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts 2>&1 | head -20
```

如果项目内已有 production trigger 脚本(commit `097d428`、`5f2fa2b` 用过),复用。

- [ ] **Step 2: 远程跑 + 拉回输出 PNG**

```bash
scp /tmp/render_take4_frame.py lanpc:C:/temp/ue-remote/render_take4_frame.py
ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/render_take4_frame.py'

# 把渲染产出 PNG 拉回(实际 lanPC 输出目录由 MRQ 配置决定)
scp 'lanpc:E:/RenderStream\ Projects/test_0311/Saved/MovieRenders/path_c_production_test_take_4_dense.0002.png' \
  /Users/bip.lan/AIWorkspace/vp/post_render_tool/validation_results/path_c_production/path_c_production_test_take_4_dense.0002.png
```

- [ ] **Step 3: 跑 production diff**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool && \
scripts/distortion_calibration/.venv/bin/python \
  scripts/distortion_calibration/compare_production_frame.py \
  --ue validation_results/path_c_production/path_c_production_test_take_4_dense.0002.png \
  --ref validation_results/path_c_production/reference/disguise_take4_seq_frame0.png \
  --out validation_results/path_c_production/production_diff_frame2_vs_seq0_post_normalization_gate.json
```

Expected: `valid_p95 ≤ 0.1255 + 0.005`(允许 5e-3 量化抖动)。`max ≤ 0.55`(baseline 0.549)。

如果 `valid_p95` 显著超过 baseline:**rollback** Task 8a/8b 的改动,把 fit summary 标 `REVIEW`,不动 production shader,等下一轮 d3 数据。**严禁**为了 fit 数字漂亮而牺牲已通过的 production diff。

---

## Phase 5 — Documentation Sync

### Task 10: 写历史归档 + plan summary

**Files:**
- Modify: `docs/archive/path_a/distortion-investigation.md` 末尾
- Modify: `docs/custom-postprocess-distortion-final-plan.md` § 2.3-2.5

- [ ] **Step 1: 在 `docs/archive/path_a/distortion-investigation.md` 末尾追加**

```markdown
## 2026-05-07 — 12-frame Normalization Fit (focal sweep + K2/K3 + centerShift)

12 帧 EXR(`validation_results/disguise_next_data/`)反推 d3 内部 distortion
公式真身。Set A: 6 帧 focal × K1 sweep。Set B: 2 帧 K2/K3 单变量。Set C: 4 帧
centerShift sweep。

**Fit harness**: `scripts/distortion_calibration/fit_normalization_candidates.py`。
跨 5 候选(full-width / focal-length / diagonal / height / half-width)做
delta-residual + cross-focal k1_eff consistency 比较。

**Verdict**: <fill in: winner candidate from focal sweep + GO/REVIEW for k2k3 / csx>。
**Reports**: `validation_results/normalization_gate/<ts>_*.{json,md}`。
**Shader change**: <fill in: 改了/没改;改了改了什么>。
**Production regression**: take_4 valid_p95 = <fill in> vs baseline 0.1255。
```

- [ ] **Step 2: 改 `docs/custom-postprocess-distortion-final-plan.md` § 2.3 / 2.4 / 2.5**

如果 fit winner 仍是 `full-width`:在 § 2.3 上方追加一段:

```markdown
> **2026-05-07 12-frame normalization gate 复核**:跨 3 焦距 (24 / 30.302 / 50 mm)
> + K2/K3 + centerShift 12 帧 EXR fit 重新确认 `full-width` (除以 W) 公式正确。
> 焦距归一化 / 对角线归一化 / 半高归一化候选 cross-focal k1_eff_spread > <fill in>,
> 全部排除。证据见 `validation_results/normalization_gate/<ts>_summary.md`。
```

如果 fit winner 是别的:整段 § 2.3-2.4 改写成新公式形态,留下 git diff 痕迹。

- [ ] **Step 3: 跨文档名字一致性 check**

```bash
grep -rn "fit_normalization_candidates\|normalization_gate" /Users/bip.lan/AIWorkspace/vp/post_render_tool/docs/ /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration/README.md 2>&1 | head -20
```

确认 README + 文档都引用了新脚本路径。如果 README 漏了,补一行简介。

---

## Phase 6 — Final State Check (no commit)

### Task 11: 全量 sanity check + 汇报状态

**Files:**
- Run only.

- [ ] **Step 1: 跑全量 unit tests**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python && \
python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -v
```

Expected: 全 PASS。

- [ ] **Step 2: 跑 fit harness 自测**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration && \
.venv/bin/python -m unittest _self_test_fit_normalization.py -v
```

Expected: PASS(synthetic ground-truth 验证 fit logic 正确)。

- [ ] **Step 3: `git status` 确认改动范围**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool && git status
```

预期改动:
- 新增:`scripts/distortion_calibration/fit_normalization_candidates.py`
- 新增:`scripts/distortion_calibration/_fit_helpers.py`
- 新增:`scripts/distortion_calibration/_self_test_fit_normalization.py`
- 新增:`validation_results/normalization_gate/<ts>_*.{json,md}`(7 个文件)
- 修改:`docs/archive/path_a/distortion-investigation.md`(追加 § 2026-05-07)
- 修改:`docs/custom-postprocess-distortion-final-plan.md`(§ 2.3 复核备注)
- (条件)修改:`Content/Python/post_render_tool/distortion_math.py`
- (条件)修改:`Content/Python/post_render_tool/build_distortion_material.py`
- (条件)修改:`Content/Python/post_render_tool/tests/test_custom_postprocess_distortion_math.py`
- (条件)修改:`validation_results/path_c_production/production_diff_frame2_vs_seq0_post_normalization_gate.json`

- [ ] **Step 4: 汇报给用户(不 commit)**

按下面格式汇报:

```
12 帧 fit 结论:
- focal sweep winner: <full-width | focal-length | ...>
- K2/K3: <GO | REVIEW>
- centerShift: <GO | REVIEW>

Shader 决策:
- 改 / 没改 — 理由 1 句

production diff regression(如改了 shader):
- valid_p95 新 = X vs baseline 0.1255

接下来等指令 commit。
```

**不要主动 commit**(memory `feedback_explicit_commit_only`)。

---

## Self-Review Notes

- **Spec coverage**:
  - "focal-length normalization 用什么 r 定义" → Task 3 evaluate_focal_sweep 跑 5 候选。
  - "K2/K3 是不是同 normalization" → Task 3 evaluate_k2_k3 + Task 5 验收。
  - "centerShift 单位 / 符号" → Task 3 evaluate_center_shift + Task 6 验收。
  - "fit 报告落 `validation_results/normalization_gate/`" → Task 3 main() 写 7 个文件。
  - "必要时改 shader" → Task 8a/8b 条件分支。
  - "不破坏 take_4 production diff baseline (valid_p95=0.13)" → Task 9 regression(实际 baseline 是 0.1255,plan 用 0.1255 + 5e-3 容差)。
  - "不建运行时模式开关" → Task 7 决策只换 normalization 实现,不引 enum。
  - "不要每步 commit" → Task 11 末尾汇报,不 commit。

- **Type consistency**:`_FOCAL_RE` 在 `_fit_helpers.py` 定义、`fit_normalization_candidates.py` 通过 `parse_disguise_next_filename` 复用;`FrameSpec` / `FrameSamples` 跨两文件统一;`CANDIDATES` 单点定义;`SUB_PIXEL_FLOOR_PX` / `K1_TOL` 顶层常量,全文件引用。

- **No-placeholder scan**:Task 8a 的 Python reference 改法是"示例"——这是因为公式形态由 Task 4 fit 结果决定,没法预先写死。Task 8a/8b/9 整体是条件性 task,触发条件已明确。Task 10 留了 `<fill in>` 占位,它们是结果性数据,fit 跑完才能填。这两类不算 placeholder 失败。

- **Open items 用户需要前提确认 / 可能影响 fit**:
  - **sensor_width_mm 默认 35.0**:plan 假设 d3 cinema sensor 标准。如果 take_4 production CSV 有别的 sensor 宽度,Task 4 跑前需要传 `--sensor-width-mm <X>`。focal-length 候选 fit 强依赖这个值;full-width / diagonal / height / half-width 不依赖,所以即使 sensor_w 用错也不影响"d3 是不是用 sensor full-width"的结论。
  - **`load_probe_meta` 解析 npz** 在 `_fit_helpers.py` 里通过 archive sys.path 复用,前提是 `archive/uv_probe_truth_3840x2160.npz` 在(已确认存在)。

End of plan.
