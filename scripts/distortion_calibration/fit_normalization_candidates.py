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
  - WINNER = candidate satisfying ALL three: k1_eff_spread < K1_TOL,
    |k1_eff_mean − target_k1| < K1_TOL, p95_max_across_focals < SUB_PIXEL_FLOOR_PX × 5.
    If no candidate qualifies, the lowest-p95 candidate is reported with verdict=REVIEW.

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
    joint_sample,
    load_corrected_arrays,
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


def _passes_winner_criteria(report: dict, target_k1: float) -> bool:
    """All three conditions: cross-focal consistency, K matches d3 value, p95 in floor."""
    return (
        report["k1_eff_spread"] < K1_TOL
        and abs(report["k1_eff_mean"] - target_k1) < K1_TOL
        and report["p95_max_across_focals"] < SUB_PIXEL_FLOOR_PX * 5
    )


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
        anchor_arr = load_corrected_arrays(anchor, width=width, height=height)
        frame_arr = load_corrected_arrays(
            non_zero, width=width, height=height,
            anchor_overscan=(anchor_arr.overscan_factor, anchor_arr.overscan_margin),
        )
        js = joint_sample(anchor_arr, frame_arr, rng=rng, samples=samples_per_frame)
        per_focal_data[f] = {
            "anchor_spec": anchor, "frame_spec": non_zero,
            "joint_samples": js,
        }

    candidate_results: dict[str, dict] = {}
    for cand in CANDIDATES:
        per_focal = []
        k1_eff_list = []
        residual_p95_list = []
        for f in focals:
            d = per_focal_data[f]
            js = d["joint_samples"]
            norm = candidate_norm_factor(
                cand, width_px=width, height_px=height,
                focal_mm=f, sensor_width_mm=sensor_width_mm,
            )
            # Predicted dr at K1=+0.5
            pred_x, pred_y = forward_brown_conrady_pixel(
                js.output_x_px, js.output_y_px,
                cx_px=cx, cy_px=cy, norm_px=norm,
                k1=d["frame_spec"].value, k2=0, k3=0,
            )
            # Actual dr (delta-residual cancels common floor with anchor pair)
            actual_dr_x = js.frame_source_x_px - js.anchor_source_x_px
            actual_dr_y = js.frame_source_y_px - js.anchor_source_y_px
            pred_dr_x = pred_x - js.output_x_px
            pred_dr_y = pred_y - js.output_y_px
            err = np.hypot(actual_dr_x - pred_dr_x, actual_dr_y - pred_dr_y)
            stats = format_stats(err)
            # Inferred K1_eff at this candidate's r definition.
            # Fit against the delta-residual (frame_src − anchor_src) which
            # cancels the common-mode over-scan recovery floor; passing
            # `output + dr` makes `_fit_k_eff` see `b = dr` cleanly.
            k_eff = _fit_k_eff(
                js.output_x_px, js.output_y_px,
                js.output_x_px + actual_dr_x,
                js.output_y_px + actual_dr_y,
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
    qualifying = [name for name, r in ranked if _passes_winner_criteria(r, target_k1)]
    winner = qualifying[0] if qualifying else None
    verdict = "GO" if qualifying else "REVIEW"
    ranked_top = [
        {
            "candidate": name,
            "p95_max_across_focals": r["p95_max_across_focals"],
            "k1_eff_mean": r["k1_eff_mean"],
            "k1_eff_spread": r["k1_eff_spread"],
        }
        for name, r in ranked[:3]
    ]

    return {
        "gate": "focal_sweep",
        "data_root": str(data_root / "focal_length_sweep"),
        "width": width, "height": height, "sensor_width_mm": sensor_width_mm,
        "candidates": candidate_results,
        "winner": winner,
        "verdict": verdict,
        "ranked_top": ranked_top,
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
    anchor_arr = load_corrected_arrays(anchor_spec, width=width, height=height)
    norm = candidate_norm_factor(
        winner_norm, width_px=width, height_px=height,
        focal_mm=anchor_spec.focal_mm, sensor_width_mm=sensor_width_mm,
    )
    cx, cy = width / 2.0, height / 2.0
    rows = []
    for s in specs:
        if s.is_anchor:
            continue
        frame_arr = load_corrected_arrays(
            s, width=width, height=height,
            anchor_overscan=(anchor_arr.overscan_factor, anchor_arr.overscan_margin),
        )
        js = joint_sample(anchor_arr, frame_arr, rng=rng, samples=samples_per_frame)
        k1, k2, k3 = 0.0, 0.0, 0.0
        if s.axis == "K2":
            k2 = s.value
        elif s.axis == "K3":
            k3 = s.value
        pred_x, pred_y = forward_brown_conrady_pixel(
            js.output_x_px, js.output_y_px,
            cx_px=cx, cy_px=cy, norm_px=norm,
            k1=k1, k2=k2, k3=k3,
        )
        # Same delta-residual scheme as Set A
        actual_dr_x = js.frame_source_x_px - js.anchor_source_x_px
        actual_dr_y = js.frame_source_y_px - js.anchor_source_y_px
        pred_dr_x = pred_x - js.output_x_px
        pred_dr_y = pred_y - js.output_y_px
        err = np.hypot(actual_dr_x - pred_dr_x, actual_dr_y - pred_dr_y)
        # Per-axis inferred coefficient: src - out ≈ k_eff · r^(2n) · (out - c)
        # n = 2 for K2 (r⁴), n = 3 for K3 (r⁶)
        order = {"K2": 2, "K3": 3}[s.axis]
        dx = js.output_x_px - cx
        dy = js.output_y_px - cy
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
    anchor_arr = load_corrected_arrays(anchor_spec, width=width, height=height)
    rows = []
    for s in specs:
        if s.is_anchor:
            continue
        frame_arr = load_corrected_arrays(
            s, width=width, height=height,
            anchor_overscan=(anchor_arr.overscan_factor, anchor_arr.overscan_margin),
        )
        js = joint_sample(anchor_arr, frame_arr, rng=rng, samples=samples_per_frame)
        median_dx_px = float(np.median(js.frame_source_x_px - js.anchor_source_x_px))
        median_dy_px = float(np.median(js.frame_source_y_px - js.anchor_source_y_px))
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
    winner_str = (
        f"`{report['winner']}`"
        if report["winner"]
        else "`NONE` — no qualifying candidate"
    )
    lines = [
        "# Focal Sweep × K1 Normalization Fit",
        "",
        f"- Data: `{report['data_root']}`",
        f"- Verdict: **{report['verdict']}** — winner = {winner_str}",
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
    ]
    if report.get("winner_assumed"):
        lines.append(
            f"> ⚠️ **ASSUMED winner = `{report['winner_normalization']}`** "
            f"via `--assume-winner` operator override. Not fit-validated. "
            f"K_eff numbers below should be re-cross-checked manually."
        )
        lines.append("")
    lines.extend([
        f"- Verdict: **{report['verdict']}** (using `{report['winner_normalization']}` from focal sweep)",
        "",
        "| frame | axis | d3 value | inferred k_eff | p95 px | rms px |",
        "|---|---|---:|---:|---:|---:|",
    ])
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


def render_summary_md(
    focal: dict,
    k2k3: dict | None,
    csx: dict | None,
    *,
    winner_assumed: bool,
    assumed_winner: str | None = None,
) -> str:
    focal_winner = focal["winner"]
    lines = [
        "# Distortion Normalization Fit — Summary",
        "",
        f"- Focal sweep verdict: **{focal['verdict']}**, winner = "
        f"`{focal_winner if focal_winner else 'NONE — no qualifying candidate'}`",
    ]
    if k2k3 is not None:
        assumed_marker = " (ASSUMED winner via --assume-winner)" if winner_assumed else ""
        lines.append(f"- K2/K3 sweep verdict: **{k2k3['verdict']}**{assumed_marker}")
    else:
        lines.append("- K2/K3 sweep: SKIPPED (no winner)")
    if csx is not None:
        lines.append(f"- CenterShift sweep verdict: **{csx['verdict']}**")
    else:
        lines.append("- CenterShift sweep: SKIPPED (no winner)")
    lines.extend(["", "## Decision", ""])
    if focal["verdict"] == "GO" and focal_winner:
        lines.append(
            f"d3 internal normalization is `{focal_winner}`. "
            "Compare against current shader formula in "
            "`Content/Python/post_render_tool/distortion_math.py:208-227` and "
            "`Content/Python/post_render_tool/build_distortion_material.py:60-72`. "
            "If they match, commit only the report; otherwise update the HLSL + "
            "Python reference + remote material asset."
        )
    elif winner_assumed:
        lines.append(
            f"d3 internal normalization ASSUMED to be `{assumed_winner}` via "
            "`--assume-winner` override. Focal-sweep gate did NOT confirm this; "
            "manual verification required before any shader change is shipped."
        )
    else:
        lines.append(
            "**No qualifying normalization candidate found.** Focal-sweep verdict is "
            "REVIEW. Inspect per-focal breakdown in `..._focal_sweep_report.md` to "
            "decide whether a focal is data-corrupted (e.g., over-scan margin too "
            "small to recover) or whether the candidate list needs extending. Do "
            "NOT ship shader changes based on this run alone."
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", type=Path, default=DATA_ROOT_DEFAULT)
    p.add_argument("--out-root", type=Path, default=OUT_ROOT_DEFAULT)
    p.add_argument("--probe-truth", type=Path, default=None,
                   help="Path to uv_probe_truth_3840x2160.npz (defaults via load_probe_meta)")
    p.add_argument("--sensor-width-mm", type=float, default=SENSOR_WIDTH_MM_DEFAULT)
    p.add_argument("--samples-per-frame", type=int, default=SAMPLES_PER_FRAME)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--assume-winner",
        choices=CANDIDATES,
        default=None,
        help=(
            "Override focal-sweep winner selection. Use ONLY when focal-sweep "
            "verdict=REVIEW for known data-quality reasons (e.g., a focal whose "
            "over-scan margin is too small to recover) and you've manually "
            "confirmed the per-focal breakdown. Reports will mark the winner "
            "as ASSUMED, not gate-validated."
        ),
    )
    args = p.parse_args()

    try:
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

        effective_winner = focal["winner"] or args.assume_winner
        winner_assumed = focal["winner"] is None and args.assume_winner is not None

        if effective_winner is None:
            # No GO and no override → can't run downstream. Write summary with
            # explicit "no qualifying candidate" statement, exit non-zero.
            summary = render_summary_md(
                focal, None, None,
                winner_assumed=False, assumed_winner=None,
            )
            (args.out_root / f"{timestamp}_summary.md").write_text(
                summary, encoding="utf-8")
            print(f"focal sweep: verdict={focal['verdict']} winner=NONE (no candidate qualifies)")
            print(f"summary: {args.out_root}/{timestamp}_summary.md")
            raise SystemExit(
                "focal sweep REVIEW with no qualifying candidate. K2/K3 + centerShift "
                "evaluation skipped. Pass --assume-winner <NAME> to force, after "
                "investigating per-focal breakdown."
            )

        k2k3 = evaluate_k2_k3(
            data_root=args.data_root, width=width, height=height,
            sensor_width_mm=args.sensor_width_mm,
            winner_norm=effective_winner,
            samples_per_frame=args.samples_per_frame, seed=args.seed + 1,
        )
        k2k3["winner_assumed"] = winner_assumed
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

        summary = render_summary_md(
            focal, k2k3, csx,
            winner_assumed=winner_assumed,
            assumed_winner=args.assume_winner if winner_assumed else None,
        )
        (args.out_root / f"{timestamp}_summary.md").write_text(summary, encoding="utf-8")

        winner_label = effective_winner + (" (ASSUMED)" if winner_assumed else "")
        print(f"focal sweep: verdict={focal['verdict']} winner={winner_label}")
        print(f"k2/k3:       verdict={k2k3['verdict']}")
        print(f"centerShift: verdict={csx['verdict']}")
        print(f"reports under {args.out_root}, timestamp={timestamp}")
    except FileNotFoundError as e:
        raise SystemExit(f"missing input: {e}")


if __name__ == "__main__":
    main()
