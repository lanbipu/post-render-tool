# K-Sweep Normalization Gate Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified delta-residual evaluator that processes K1/K2/K3 sweep data against a 3-candidate matrix `(normalization × formula)`, outputs a single comparison markdown that lets us **first lock the normalization, then lock the formula**.

**Architecture:** Rename `evaluate_k2_k3_custom_formula.py` → `evaluate_k_sweep_custom_formula.py`. Extend filename parser to recognize `K1`. Add per-sweep-dir anchor lookup (K1 frames pull `k1_sweep/disguise_K1_zero.exr`, K2/K3 frames pull `k2_k3_sweep/disguise_K2_zero.exr`). Refactor `_pixel_grids` and `evaluate_frame` to accept a normalization mode (`full-width` or `half-width`). Add a candidate runner that defaults to running 3 specs in one invocation: `(forward, full-width)` / `(forward, half-width)` / `(division, full-width)`. Emit a single comparison markdown that surfaces verdicts in the spec-required ordering (lock norm first → lock formula second).

**Tech Stack:** Python 3.14, numpy, OpenCV (OPENCV_IO_ENABLE_OPENEXR), argparse, existing project deps. Tests use the existing `_self_test_*.py` plain-function style (no pytest).

---

## Background context

**Where the code lives:**
- Current evaluator: `scripts/distortion_calibration/evaluate_k2_k3_custom_formula.py` — already supports `--formula {forward,division}` and full-width norm (hardcoded after Step 3 fix).
- K2/K3 anchor logic uses `k2_k3_sweep/disguise_K2_zero.exr` (the K=0 frame in the K2/K3 sweep dir).
- K1 sweep data lives separately: `validation_results/k1_sweep/disguise_K1_*.exr` (51 frames, K1 from -0.50 to +0.50 in 0.02 steps), with own zero anchor `k1_sweep/disguise_K1_zero.exr`.
- Self-test: `scripts/distortion_calibration/_self_test_custom_gate_eval.py` — currently broken on the `centerShift` half (Codex P2 finding) but the K2/K3 half still runs.

**Why "normalization first":** Full-width vs half-width differ by a factor of 2 in radius, so the candidate K coefficients differ by `2^n`. If we test formula candidates without first establishing the radius normalization, results are uninterpretable (Cortex + Codex agreed: this was the deepest blind-spot in prior runs).

**What "delta residual" means here:** `(frame_actual − anchor_actual) − (pred_K_frame − pred_K=0_identity)`. This cancels the half-float quantization floor and the over-scan affine residual that anchor and frame share, leaving K-specific modeling residual. Already implemented for K2/K3 in current evaluator; need to extend to K1.

**Test strategy:**
- Light TDD on pure-function helpers (parsers, normalization grid generators, formula functions) using `_self_test_*.py` style.
- Integration verification by running on real EXR data and comparing candidate p95 across the three required combinations. No automated integration test fixture (would require committing or generating synthetic EXR plates, which is overkill for a research script).

**Commit policy:** Per project memory `feedback_explicit_commit_only`, do **not** auto-commit at the end of each task. Stage changes with `git add -p` to allow review. The user will commit at end of the plan.

---

## File Structure

```
scripts/distortion_calibration/
├── evaluate_k_sweep_custom_formula.py   ← NEW (renamed + extended from evaluate_k2_k3_custom_formula.py)
├── evaluate_k2_k3_custom_formula.py     ← DELETED (canonical evaluator becomes the rename target)
├── _self_test_custom_gate_eval.py       ← UPDATED imports + new tests
└── ... (other files unchanged)

docs/superpowers/plans/
└── 2026-05-06-k-sweep-normalization-gate.md  ← this plan
```

The single-file design is intentional: the script is a research tool with one entry point. Splitting helpers across modules would only add import overhead.

---

## Task 1: Rename evaluator file and unbreak self-test imports

**Why:** Current name is K2/K3-specific; the new scope is K1+K2+K3 unified. Also: Codex P2 finding said self-test is broken on `centerShift` half due to filename regex changes — fix while we're touching imports.

**Files:**
- Rename: `scripts/distortion_calibration/evaluate_k2_k3_custom_formula.py` → `scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py`
- Modify: `scripts/distortion_calibration/_self_test_custom_gate_eval.py:13`
- Verify: `scripts/distortion_calibration/_self_test_custom_gate_eval.py`

- [ ] **Step 1: Run current self-test to capture baseline state**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
python3 _self_test_custom_gate_eval.py
```

Expected: tests for `parse_axis_value`, `source_norm_from_official_formula`, `format_stats` should pass. The `parse_center_shift_value` test may fail because `evaluate_center_shift_sweep.py` regex changed to require `K1p3` prefix — note which assertions fail.

- [ ] **Step 2: Rename the evaluator file via git mv**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git mv scripts/distortion_calibration/evaluate_k2_k3_custom_formula.py scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py
```

- [ ] **Step 3: Update self-test imports**

In `scripts/distortion_calibration/_self_test_custom_gate_eval.py`, change:

```python
from evaluate_k2_k3_custom_formula import (
    format_stats,
    parse_axis_value,
    source_norm_from_official_formula,
)
```

to:

```python
from evaluate_k_sweep_custom_formula import (
    format_stats,
    parse_axis_value,
    source_norm_from_official_formula,
)
```

- [ ] **Step 4: Fix center_shift_sweep filename regex tests**

Look at the existing `test_parse_center_shift_value` block (currently uses old `disguise_centerShiftX_n0p10` style). Update each assertion to use the current Set B v2 names that the regex actually accepts:

```python
def test_parse_center_shift_value() -> None:
    assert parse_center_shift_value("disguise_K1p3_centerShiftX_n0p10") == ("x", -0.10)
    assert parse_center_shift_value("disguise_K1p3_centerShiftY_p0p05") == ("y", 0.05)
    assert parse_center_shift_value("disguise_K1p3_centerShift_zero") == ("zero", 0.0)
    assert parse_center_shift_value("disguise_K1p3_centerShiftY_zero") == ("zero", 0.0)
```

(The regex accepts both `_zero` and `Y_zero` / `X_zero` since both are written by Disguise renders; keep both.)

- [ ] **Step 5: Run self-test, expect green**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
python3 _self_test_custom_gate_eval.py
```

Expected: all assertions pass; script exits 0; no Python output other than the standard "all tests passed" if the test file prints one (or silent if it doesn't).

- [ ] **Step 6: Stage changes (do not commit)**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git add scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py scripts/distortion_calibration/_self_test_custom_gate_eval.py
git status
```

Expected: shows `R` (rename) for the evaluator and `M` (modify) for the self-test.

---

## Task 2: Extend parser to recognize K1 frames

**Why:** Current `parse_axis_value` rejects `disguise_K1_*.exr` because it asserts `axis in (2, 3)`. We need K1 frames in the new evaluator.

**Files:**
- Modify: `scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py:36-41`
- Modify: `scripts/distortion_calibration/_self_test_custom_gate_eval.py` (add tests after the existing `test_parse_axis_value`)

- [ ] **Step 1: Write failing tests for K1 parsing**

Add to `_self_test_custom_gate_eval.py` next to the existing `test_parse_axis_value`:

```python
def test_parse_axis_value_includes_k1() -> None:
    assert parse_axis_value("disguise_K1_p0p10") == (1, 0.10)
    assert parse_axis_value("disguise_K1_n0p30") == (1, -0.30)
    assert parse_axis_value("disguise_K1_zero") == (1, 0.0)
```

Then in the test runner block at the bottom of the file, add a call to `test_parse_axis_value_includes_k1()`.

- [ ] **Step 2: Run self-test, expect failure**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
python3 _self_test_custom_gate_eval.py
```

Expected: `ValueError: expected K2/K3 filename, got K1: disguise_K1_p0p10` or similar.

- [ ] **Step 3: Loosen the axis check**

In `evaluate_k_sweep_custom_formula.py`, find the function:

```python
def parse_axis_value(stem: str) -> tuple[int, float]:
    """Parse disguise_K2_p0p3 style filenames."""
    axis, value = parse_k_value(stem)
    if axis not in (2, 3):
        raise ValueError(f"expected K2/K3 filename, got K{axis}: {stem}")
    return axis, value
```

Change to:

```python
def parse_axis_value(stem: str) -> tuple[int, float]:
    """Parse disguise_K{1,2,3}_(p|n)NpNN | disguise_K{1,2,3}_zero filenames."""
    axis, value = parse_k_value(stem)
    if axis not in (1, 2, 3):
        raise ValueError(f"expected K1/K2/K3 filename, got K{axis}: {stem}")
    return axis, value
```

(`parse_k_value` is imported from `analyze_renders` and already handles K1 — only this evaluator-level wrapper was restricting to K2/K3.)

- [ ] **Step 4: Run self-test, expect green**

```bash
python3 _self_test_custom_gate_eval.py
```

- [ ] **Step 5: Stage**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git add scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py scripts/distortion_calibration/_self_test_custom_gate_eval.py
```

---

## Task 3: Add multi-sweep anchor resolution

**Why:** K1 frames live in `k1_sweep/` and need `k1_sweep/disguise_K1_zero.exr` as anchor. K2/K3 frames live in `k2_k3_sweep/` and use `k2_k3_sweep/disguise_K2_zero.exr`. The current `_find_anchor` only finds anchors in the input directory passed to `evaluate_directory`, which assumes a single sweep dir.

**Files:**
- Modify: `scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py` — add new function and refactor `evaluate_directory`
- Modify: `scripts/distortion_calibration/_self_test_custom_gate_eval.py` — add tests

- [ ] **Step 1: Write failing tests for anchor resolution**

Add to `_self_test_custom_gate_eval.py`:

```python
from pathlib import Path

def test_resolve_anchor_for_axis_picks_correct_zero() -> None:
    from evaluate_k_sweep_custom_formula import resolve_anchor_for_axis
    base = Path("/some/validation_root")
    assert resolve_anchor_for_axis(1, base) == base / "k1_sweep" / "disguise_K1_zero.exr"
    assert resolve_anchor_for_axis(2, base) == base / "k2_k3_sweep" / "disguise_K2_zero.exr"
    assert resolve_anchor_for_axis(3, base) == base / "k2_k3_sweep" / "disguise_K2_zero.exr"
```

Add the call to the test runner block.

- [ ] **Step 2: Run self-test, expect ImportError**

```bash
python3 _self_test_custom_gate_eval.py
```

Expected: `ImportError: cannot import name 'resolve_anchor_for_axis'`.

- [ ] **Step 3: Add the resolver function**

In `evaluate_k_sweep_custom_formula.py`, near the top with other constants, add:

```python
SWEEP_DIR_BY_AXIS: dict[int, tuple[str, str]] = {
    # axis -> (sweep_subdir, anchor_filename)
    1: ("k1_sweep", "disguise_K1_zero.exr"),
    2: ("k2_k3_sweep", "disguise_K2_zero.exr"),
    3: ("k2_k3_sweep", "disguise_K2_zero.exr"),
}


def resolve_anchor_for_axis(axis: int, validation_root: Path) -> Path:
    """Return the canonical zero anchor file path for a given K axis.

    K1 frames anchor against k1_sweep/disguise_K1_zero.exr.
    K2 and K3 frames share k2_k3_sweep/disguise_K2_zero.exr (identical pixel
    content to K3_zero by construction; K2_zero is the canonical pick).
    """
    if axis not in SWEEP_DIR_BY_AXIS:
        raise ValueError(f"unsupported axis K{axis}")
    subdir, name = SWEEP_DIR_BY_AXIS[axis]
    return validation_root / subdir / name
```

- [ ] **Step 4: Run self-test, expect green**

- [ ] **Step 5: Refactor `evaluate_directory` to consume both sweep dirs**

The current signature takes a single `input_dir`. Change it to take a `validation_root` (the parent of `k1_sweep/` and `k2_k3_sweep/`) and discover frames across both subdirs.

Find this block in `evaluate_directory`:

```python
if not input_dir.is_dir():
    raise RuntimeError(f"input dir not found: {input_dir}")
exr_files = sorted(input_dir.rglob("disguise_*.exr"))
if not exr_files:
    raise RuntimeError(f"no disguise_*.exr files under {input_dir}")
```

Replace with:

```python
if not validation_root.is_dir():
    raise RuntimeError(f"validation root not found: {validation_root}")
sweep_dirs = [validation_root / "k1_sweep", validation_root / "k2_k3_sweep"]
exr_files: list[Path] = []
for d in sweep_dirs:
    if d.is_dir():
        exr_files.extend(sorted(d.glob("disguise_K*.exr")))
if not exr_files:
    raise RuntimeError(
        f"no disguise_K*.exr files under {sweep_dirs}; expected k1_sweep/ and k2_k3_sweep/"
    )
```

Rename the `input_dir` parameter to `validation_root` everywhere in that function signature and body. Update the report dict's `"input_dir"` key to `"validation_root"`.

- [ ] **Step 6: Refactor anchor read logic to be per-frame**

The existing code does this once before the frame loop:

```python
anchor = _find_anchor(exr_files)
R0, G0 = read_uvprobe_exr(anchor)
overscan_factor, overscan_margin = detect_overscan_from_anchor(R0, G0)
```

This must move inside the frame loop and become per-axis. Replace with a small cache:

```python
anchor_cache: dict[int, tuple[np.ndarray, np.ndarray, float, float]] = {}

def get_anchor(axis: int) -> tuple[np.ndarray, np.ndarray, float, float]:
    if axis not in anchor_cache:
        path = resolve_anchor_for_axis(axis, validation_root)
        if not path.exists():
            raise RuntimeError(f"missing anchor for K{axis}: {path}")
        R0, G0 = read_uvprobe_exr(path)
        of, om = detect_overscan_from_anchor(R0, G0)
        anchor_cache[axis] = (R0, G0, of, om)
    return anchor_cache[axis]
```

Then inside the frame loop, fetch the per-axis anchor:

```python
for path in exr_files:
    try:
        axis, value = parse_axis_value(path.stem)
    except ValueError:
        continue
    if abs(value) < 1e-9:
        continue
    R0, G0, overscan_factor, overscan_margin = get_anchor(axis)
    frame = evaluate_frame(
        path,
        axis,
        value,
        R0=R0,
        G0=G0,
        overscan_margin=overscan_margin,
        width=width_camera,
        height=height_camera,
        half_width=half_width,
        rng=rng,
        samples_per_frame=samples_per_frame,
        formula=formula,
    )
    ...
```

Delete the old `_find_anchor` function — no longer needed.

The existing report dict's `"anchor": anchor.name` becomes `"anchors": {axis: path.name for axis, ... in anchor_cache.items()}` (use a dict comprehension to map axis -> filename).

- [ ] **Step 7: Update CLI default and arg name**

In `main()`:

```python
DEFAULT_INPUT_DIR = Path("validation_results/custom_pp_gate_inputs/k2_k3_sweep")
```

Change to:

```python
DEFAULT_VALIDATION_ROOT = Path("validation_results")
```

And update the argparse line:

```python
parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
```

to:

```python
parser.add_argument("--validation-root", type=Path, default=DEFAULT_VALIDATION_ROOT)
```

Update the call in `main()` to pass `validation_root=args.validation_root`.

- [ ] **Step 8: Run self-test, expect green; smoke test the script**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
python3 _self_test_custom_gate_eval.py
python3 evaluate_k_sweep_custom_formula.py --validation-root validation_results --formula forward 2>&1 | tail -3
```

Expected: self-test passes; the script runs without crashing and writes a markdown report. Verdict will likely still be NO-GO — that's fine, this task only re-plumbs anchor lookup. Verify the report now contains rows for `disguise_K1_*.exr` frames in addition to K2/K3. Report should have ~12 frames (4 K2 ± + 4 K3 ± + at least 4 K1 ± from K1 sweep, depending on which K1 values you choose to include; see Task 4 for filtering).

- [ ] **Step 9: Stage**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git add scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py scripts/distortion_calibration/_self_test_custom_gate_eval.py
```

---

## Task 4: Add normalization mode parameter

**Why:** Spec needs `(forward, full-width)` and `(forward, half-width)` and `(division, full-width)` candidates. Currently the evaluator hardcodes full-width via `half_width = float(width_camera)`. Need to make this a runtime choice.

**Files:**
- Modify: `scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py`
- Modify: `scripts/distortion_calibration/_self_test_custom_gate_eval.py`

- [ ] **Step 1: Write failing test for normalization helper**

Add to `_self_test_custom_gate_eval.py`:

```python
def test_normalization_factor_full_width_vs_half_width() -> None:
    from evaluate_k_sweep_custom_formula import normalization_factor
    width = 3840
    assert normalization_factor("full-width", width) == 3840.0
    assert normalization_factor("half-width", width) == 1920.0
```

- [ ] **Step 2: Run self-test, expect ImportError**

- [ ] **Step 3: Add normalization helper**

In `evaluate_k_sweep_custom_formula.py`, near `_pixel_grids`:

```python
NORMALIZATION_MODES: tuple[str, ...] = ("full-width", "half-width")


def normalization_factor(mode: str, width: int) -> float:
    """Return the per-axis normalization denominator in pixel units.

    full-width: r_norm = (px - cx) / W      → corner r ≈ 0.574 in 16:9
    half-width: r_norm = (px - cx) / (W/2)  → corner r ≈ 1.147 in 16:9 (legacy
                  OpenCV-ish convention, pre-Step-3 fix)
    """
    if mode == "full-width":
        return float(width)
    if mode == "half-width":
        return float(width) / 2.0
    raise ValueError(f"unknown normalization mode: {mode!r}")
```

- [ ] **Step 4: Run self-test, expect green**

- [ ] **Step 5: Thread `normalization` through the evaluator chain**

Update `evaluate_frame` signature to accept `normalization: str = "full-width"`. Inside, replace the existing `half_width` references with computing the factor from the parameter:

Currently inside `evaluate_frame` (at the start of computation):

```python
out_x_norm, out_y_norm = _pixel_grids(width, height, half_width)
```

`half_width` here is misnamed — it's whatever normalizer the caller chose. Don't rename for now (rename in Task 5 if it survives review); just keep passing it.

In `evaluate_directory`, change:

```python
half_width = float(width_camera)
```

to:

```python
half_width = normalization_factor(normalization, width_camera)
```

Add `normalization: str = "full-width"` to the `evaluate_directory` signature and pass `normalization=normalization` into the `evaluate_frame` call.

- [ ] **Step 6: Add `--normalization` CLI flag**

In `main()`:

```python
parser.add_argument(
    "--normalization",
    choices=NORMALIZATION_MODES,
    default="full-width",
    help="Radius normalization: full-width (sensor full width) or half-width (legacy)",
)
```

Pass `normalization=args.normalization` in the `evaluate_directory(...)` call.

Add `"normalization": normalization,` to the report dict alongside the existing `"formula": formula,`.

Update `render_markdown` to surface the normalization in the header:

```python
f"- Normalization: **{report.get('normalization', 'full-width')}**",
```

(Place this line right after the `Formula:` line.)

- [ ] **Step 7: Smoke test both normalizations**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
python3 evaluate_k_sweep_custom_formula.py --validation-root validation_results --formula forward --normalization full-width --md-output /tmp/gate6_full.md 2>&1 | tail -2
python3 evaluate_k_sweep_custom_formula.py --validation-root validation_results --formula forward --normalization half-width --md-output /tmp/gate6_half.md 2>&1 | tail -2
head -8 /tmp/gate6_full.md
echo "---"
head -8 /tmp/gate6_half.md
```

Expected: both runs complete; first output shows `Normalization: **full-width**`, second shows `Normalization: **half-width**`. Verdict on half-width should be much worse (large p95) — that's the data confirming our prior reverse-engineering that full-width is right.

- [ ] **Step 8: Stage**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git add scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py scripts/distortion_calibration/_self_test_custom_gate_eval.py
```

---

## Task 5: Add candidate matrix runner with comparison markdown

**Why:** Spec requires running 3 candidates and comparing in a single artifact. CLI should support both single-candidate (existing flags) and matrix mode (new).

**Files:**
- Modify: `scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py`

- [ ] **Step 1: Define the candidate matrix as a constant**

Near the other constants at the top:

```python
DEFAULT_CANDIDATES: tuple[tuple[str, str], ...] = (
    # (formula, normalization)
    ("forward",  "full-width"),
    ("forward",  "half-width"),
    ("division", "full-width"),
)
```

- [ ] **Step 2: Add a runner function**

Below `evaluate_directory`, add:

```python
def evaluate_candidates(
    validation_root: Path,
    *,
    candidates: tuple[tuple[str, str], ...],
    output_md: Path,
    output_json: Path,
    probe_truth: Path | None,
    samples_per_frame: int,
    seed: int,
    threshold_p95_px: float,
) -> dict[str, object]:
    """Run multiple (formula, normalization) candidates against the same data
    and emit a single comparison markdown.
    """
    candidate_reports: list[dict[str, object]] = []
    for formula, normalization in candidates:
        # Per-candidate JSON gets a suffix so the directory shows all of them.
        suffix = f"{formula}_{normalization.replace('-', '')}"
        cand_json = output_json.with_name(f"{output_json.stem}_{suffix}.json")
        cand_md = output_md.with_name(f"{output_md.stem}_{suffix}.md")
        report = evaluate_directory(
            validation_root,
            output_json=cand_json,
            output_md=cand_md,
            probe_truth=probe_truth,
            samples_per_frame=samples_per_frame,
            seed=seed,
            threshold_p95_px=threshold_p95_px,
            formula=formula,
            normalization=normalization,
        )
        candidate_reports.append(report)

    comparison_md = render_comparison_markdown(candidate_reports, threshold_p95_px)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(comparison_md, encoding="utf-8")
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps({"candidates": candidate_reports, "threshold_p95_px": threshold_p95_px}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"candidates": candidate_reports, "threshold_p95_px": threshold_p95_px}
```

- [ ] **Step 3: Add the comparison renderer**

Below `render_markdown`, add:

```python
def render_comparison_markdown(
    reports: list[dict[str, object]],
    threshold_p95_px: float,
) -> str:
    """Render a single comparison table where each row is one frame and
    columns are per-candidate p95(delta_residual). Surfaces normalization
    first (group by normalization), then formula within each group, so the
    spec ordering 'lock norm first → lock formula second' is visually direct.
    """
    lines = [
        "# Gate 6 K-Sweep Candidate Comparison",
        "",
        f"- Threshold: per-frame `p95(delta_residual) < {threshold_p95_px} px`",
        "- Reading order: pick the **normalization** with the lowest p95 across all axes first, then within that normalization pick the **formula** with the lowest p95.",
        "- `delta_residual` = `(frame_actual − anchor_actual) − (pred_K − pred_identity)`. Cancels common quantization/affine floor.",
        "",
    ]
    # Header row: candidate columns
    headers = ["frame", "axis", "value"]
    candidate_labels = []
    for r in reports:
        norm = r.get("normalization", "?")
        formula = r.get("formula", "?")
        candidate_labels.append(f"{norm}/{formula}")
    headers.extend([f"{c} p95" for c in candidate_labels])
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")

    # Build a lookup: report_idx -> {file -> delta_p95}
    by_file_per_report: list[dict[str, float]] = []
    for r in reports:
        file_p95 = {}
        for frame in r["frames"]:
            file_p95[frame["file"]] = frame["delta_residual"]["p95_px"]
        by_file_per_report.append(file_p95)

    # Use the first report's frame ordering as the canonical row order
    canonical_frames = reports[0]["frames"] if reports else []
    for frame in canonical_frames:
        row = [
            f"`{frame['file']}`",
            frame["axis"],
            f"{frame['value']:+.3f}",
        ]
        for fp95 in by_file_per_report:
            v = fp95.get(frame["file"])
            row.append(f"{v:.3f}" if v is not None else "—")
        lines.append("| " + " | ".join(row) + " |")

    # Aggregate per-axis p95
    lines.extend(["", "## Per-axis aggregate p95 across all frames", ""])
    lines.append("| axis | " + " | ".join(candidate_labels) + " |")
    lines.append("|" + "|".join(["---"] * (len(candidate_labels) + 1)) + "|")
    axes = ["K1", "K2", "K3"]
    for axis_label in axes:
        row = [axis_label]
        for r in reports:
            axis_p95s = [
                f["delta_residual"]["p95_px"]
                for f in r["frames"]
                if f["axis"] == axis_label
            ]
            if axis_p95s:
                row.append(f"{max(axis_p95s):.3f}")
            else:
                row.append("—")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Wire `--compare` flag in main()**

Add a `--compare` flag to `main()`:

```python
parser.add_argument(
    "--compare",
    action="store_true",
    help="Run the default candidate matrix (3 specs) and emit a comparison markdown",
)
```

In the body of `main()`, branch:

```python
if args.compare:
    evaluate_candidates(
        args.validation_root,
        candidates=DEFAULT_CANDIDATES,
        output_json=args.output,
        output_md=args.md_output,
        probe_truth=args.probe_truth,
        samples_per_frame=args.samples_per_frame,
        seed=args.seed,
        threshold_p95_px=args.threshold_p95_px,
    )
    print(f"wrote comparison {args.md_output}")
    return
```

Place this branch *before* the existing single-run `evaluate_directory(...)` call so `--compare` short-circuits.

- [ ] **Step 5: Smoke test the matrix runner**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
python3 evaluate_k_sweep_custom_formula.py --validation-root validation_results --compare \
    --output /Volumes/Docs/temp/k_sweep/gate6_compare.json \
    --md-output /Volumes/Docs/temp/k_sweep/gate6_compare.md 2>&1 | tail -5
ls -la /Volumes/Docs/temp/k_sweep/gate6_compare*
```

Expected: 3 per-candidate `.json` and `.md` files plus the master `gate6_compare.{json,md}`. The master `gate6_compare.md` shows a per-frame comparison table with three p95 columns.

- [ ] **Step 6: Stage**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git add scripts/distortion_calibration/evaluate_k_sweep_custom_formula.py
```

---

## Task 6: Run on real data and document the verdict

**Why:** End-of-plan: produce the actual normalization+formula decision document the user can act on.

**Files:**
- Run script (no source edits)
- Create: `docs/distortion-investigation.md` — append a new section (do not overwrite the existing file)

- [ ] **Step 1: Run the matrix on real data**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/scripts/distortion_calibration
python3 evaluate_k_sweep_custom_formula.py --validation-root validation_results --compare \
    --output /Volumes/Docs/temp/k_sweep/gate6_compare.json \
    --md-output /Volumes/Docs/temp/k_sweep/gate6_compare.md
```

Expected: completes in 1–3 minutes (each candidate samples 200k pixels per frame across ~50 K1 frames + 8 K2/K3 frames). `gate6_compare.md` written.

- [ ] **Step 2: Read the comparison report**

```bash
cat /Volumes/Docs/temp/k_sweep/gate6_compare.md
```

- [ ] **Step 3: Identify the winner via the per-axis aggregate table**

The "Per-axis aggregate p95" table at the bottom of the comparison report should show:
- One column per candidate
- One row per axis (K1, K2, K3)
- Cell value = max p95 across all frames for that axis under that candidate

The winning **normalization** is the one whose K1 column is dramatically lower than the alternative (half-width should give 16x larger residuals on K1 sweep if our prior reverse-engineering is right). Once normalization is locked, compare the two formula candidates *within* that normalization (forward+full vs division+full); the lower-p95 one wins.

If the K1 column is comparable across normalizations (within 10–20%), that means the data cannot distinguish — write that finding instead of forcing a verdict.

- [ ] **Step 4: Append findings to the investigation doc**

In `docs/distortion-investigation.md`, append a new section at the end:

```markdown
## 2026-05-06 — Normalization Gate

Ran K1+K2+K3 sweep against `(forward, full-width) / (forward, half-width) / (division, full-width)` candidates with delta-residual scoring. Report: `/Volumes/Docs/temp/k_sweep/gate6_compare.md`.

**Per-axis p95 (delta_residual) across all sweep frames:**

| axis | full-width / forward | half-width / forward | full-width / division |
|---|---:|---:|---:|
| K1 | <fill> | <fill> | <fill> |
| K2 | <fill> | <fill> | <fill> |
| K3 | <fill> | <fill> | <fill> |

**Verdict:**
1. Normalization: <winner / unable-to-distinguish + reasoning>
2. Formula (within winning normalization): <winner / unable-to-distinguish + reasoning>

**Implications for shader landing (`Content/Python/post_render_tool/distortion_math.py`):**
- <whether to keep current half-width or switch to full-width>
- <whether forward dispatch is justified or division should be tested in shader too>

**Caveats still in play:**
- focal-length normalization confound (Codex P2 #6) — not addressed by this gate; would require new d3 renders at different focal lengths.
- 32-bit float floor (~3 px residual) — limits absolute accuracy; this gate compares candidates relative to that floor, not as absolute measurements.
```

Replace each `<fill>` and `<...>` with values from the comparison report. The verdict text should follow this template:

> Winner: **<normalization>** (K1 p95 = X.XX vs Y.YY) — confident / borderline / inconclusive based on margin.

- [ ] **Step 5: Stage everything**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
git add docs/distortion-investigation.md
git status
```

Expected: shows the renamed evaluator, modified self-test, modified `distortion-investigation.md`. **Do not commit** — wait for user authorization (per project memory `feedback_explicit_commit_only`).

- [ ] **Step 6: Surface the verdict to the user**

Output a short summary in the conversation (not in any file) with:
- Which candidate won
- Margin of victory (in p95 px)
- Whether the verdict is confident or borderline
- Recommendation for the next step (touch shader, ask for new d3 renders, etc.)

Wait for user direction before any further changes (in particular: no edits to `distortion_math.py` or `custom-postprocess-distortion-final-plan.md` until the user has reviewed the verdict).

---

## Self-review checklist

**Spec coverage:**
- ✅ Extend evaluator to K1+K2+K3 — Tasks 2, 3
- ✅ Rename to `evaluate_k_sweep_custom_formula.py` — Task 1
- ✅ Inputs from both `k1_sweep/` and `k2_k3_sweep/` — Task 3
- ✅ Three required candidates — Task 5 (`DEFAULT_CANDIDATES`)
- ✅ Per axis / K / radius bucket delta_residual — already in current evaluator (per-frame `delta_residual` + `radius_buckets`); aggregated per-axis added in Task 5 comparison renderer
- ✅ "First normalization, then formula" ordering — Task 5 renderer surfaces per-axis p95 grouped to make this comparison direct, Task 6 verdict template enforces the ordering
- ✅ Codex P2 self-test broken — fixed in Task 1

**Placeholder scan:** No "TBD", "TODO", "implement later", "add validation", "similar to Task N" in the plan body. The `<fill>` markers in Task 6 are explicit placeholders the executor must fill from real data — that is the point of that task.

**Type consistency:**
- `parse_axis_value` returns `tuple[int, float]` everywhere
- `resolve_anchor_for_axis(axis, root)` signature consistent across Task 3 step 3 and step 6
- `normalization_factor(mode, width)` signature consistent across Task 4 step 3 and step 5
- `evaluate_directory` parameter rename `input_dir` → `validation_root` propagates through Task 3 step 5, Task 5 step 2 caller, and Task 4/5 main() wiring

**Commit policy:** No task auto-commits. All tasks end with `git add` + `git status` (or just `git add`). Final commit decision is the user's at the end of the plan.

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-06-k-sweep-normalization-gate.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
