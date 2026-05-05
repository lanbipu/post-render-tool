"""Evaluate K1/K2/K3 Disguise renders against candidate distortion formulas.

This script is the local half of Gate 6. It reads UV-probe EXRs requested in
docs/d3-distortion-render-request.md, compares Disguise's encoded source UV
against candidate distortion models:

    forward:  source_norm = output_norm * (1 + K1*r2 + K2*r4 + K3*r6)
    division: source_norm = output_norm / (1 - K1*r2 - K2*r4 - K3*r6)

and emits JSON + Markdown delta-residual reports for model comparison.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from _exr import load_probe_meta, read_uvprobe_exr
from analyze_renders import (
    VALID_UV_MAX,
    VALID_UV_MIN,
    detect_overscan_from_anchor,
    parse_k_value,
)


DEFAULT_VALIDATION_ROOT = Path("validation_results")
DEFAULT_OUTPUT = Path("/Volumes/Docs/temp/k_sweep/gate6_k2_k3_custom_formula.json")
DEFAULT_MD_OUTPUT = Path("/Volumes/Docs/temp/k_sweep/gate6_k2_k3_custom_formula.md")
DEFAULT_SAMPLES_PER_FRAME = 200_000
DEFAULT_THRESHOLD_P95_PX = 1.5

DEFAULT_CANDIDATES: tuple[tuple[str, str], ...] = (
    # (formula, normalization)
    ("forward",  "full-width"),
    ("forward",  "half-width"),
    ("division", "full-width"),
)

SWEEP_DIR_BY_AXIS: dict[int, tuple[str, str]] = {
    # axis -> (sweep_subdir, anchor_filename)
    1: ("k1_sweep", "disguise_K1_zero.exr"),
    2: ("custom_pp_gate_inputs/k2_k3_sweep", "disguise_K2_zero.exr"),
    3: ("custom_pp_gate_inputs/k2_k3_sweep", "disguise_K2_zero.exr"),
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


def parse_axis_value(stem: str) -> tuple[int, float]:
    """Parse disguise_K{1,2,3}_(p|n)NpNN | disguise_K{1,2,3}_zero filenames."""
    axis, value = parse_k_value(stem)
    if axis not in (1, 2, 3):
        raise ValueError(f"expected K1/K2/K3 filename, got K{axis}: {stem}")
    return axis, value


def source_norm_from_official_formula(
    out_x_norm: np.ndarray,
    out_y_norm: np.ndarray,
    *,
    k1: float,
    k2: float,
    k3: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Forward Brown-Conrady: src = out × (1 + K1·r² + K2·r⁴ + K3·r⁶)."""
    r2 = out_x_norm * out_x_norm + out_y_norm * out_y_norm
    r4 = r2 * r2
    r6 = r4 * r2
    factor = k1 * r2 + k2 * r4 + k3 * r6
    scale = 1.0 + factor
    return out_x_norm * scale, out_y_norm * scale


def source_norm_from_division_formula(
    out_x_norm: np.ndarray,
    out_y_norm: np.ndarray,
    *,
    k1: float,
    k2: float,
    k3: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Division (Fitzgibbon-style) model: src = out / (1 − K1·r² − K2·r⁴ − K3·r⁶).

    Sign convention matches forward at small K: K>0 yields src/out > 1
    (outward warp), aligning with observed obs_at_r=1 sign for K=+0.30 sweep.
    Differs from forward in second order — visible at high r, large |K|.
    """
    r2 = out_x_norm * out_x_norm + out_y_norm * out_y_norm
    r4 = r2 * r2
    r6 = r4 * r2
    factor = k1 * r2 + k2 * r4 + k3 * r6
    scale = 1.0 / (1.0 - factor)
    return out_x_norm * scale, out_y_norm * scale


_FORMULA_DISPATCH = {
    "forward": source_norm_from_official_formula,
    "division": source_norm_from_division_formula,
}


def format_stats(values_px: np.ndarray) -> dict[str, float | int]:
    if values_px.size == 0:
        return {
            "n": 0,
            "median_px": float("nan"),
            "p95_px": float("nan"),
            "p99_px": float("nan"),
            "rms_px": float("nan"),
            "max_px": float("nan"),
        }
    return {
        "n": int(values_px.size),
        "median_px": float(np.percentile(values_px, 50)),
        "p95_px": float(np.percentile(values_px, 95)),
        "p99_px": float(np.percentile(values_px, 99)),
        "rms_px": float(np.sqrt(np.mean(values_px * values_px))),
        "max_px": float(np.max(values_px)),
    }



NORMALIZATION_MODES: tuple[str, ...] = ("full-width", "half-width")


def normalization_factor(mode: str, width: int) -> float:
    """Return the per-axis normalization denominator in pixel units.

    full-width: r_norm = (px - cx) / W      → corner r ≈ 0.574 in 16:9
    half-width: r_norm = (px - cx) / (W/2)  → corner r ≈ 1.147 in 16:9
                  (legacy OpenCV-ish convention, pre-Step-3 fix)
    """
    if mode == "full-width":
        return float(width)
    if mode == "half-width":
        return float(width) / 2.0
    raise ValueError(f"unknown normalization mode: {mode!r}")


def _pixel_grids(width: int, height: int, half_width: float) -> tuple[np.ndarray, np.ndarray]:
    xs = (np.arange(width, dtype=np.float64) + 0.5 - width / 2.0) / half_width
    ys = (np.arange(height, dtype=np.float64) + 0.5 - height / 2.0) / half_width
    return xs[None, :], ys[:, None]


def _raw_uv_from_norm(
    x_norm: np.ndarray,
    y_norm: np.ndarray,
    width: int,
    height: int,
    half_width: float,
) -> tuple[np.ndarray, np.ndarray]:
    u = 0.5 + x_norm * half_width / width
    v = 0.5 + y_norm * half_width / height
    return u, v


def evaluate_frame(
    path: Path,
    axis: int,
    value: float,
    *,
    R0: np.ndarray,
    G0: np.ndarray,
    overscan_margin: float,
    width: int,
    height: int,
    half_width: float,
    rng: np.random.Generator,
    samples_per_frame: int,
    formula: str = "forward",
) -> dict[str, object]:
    """Compute K2/K3 frame residual against the candidate Brown-Conrady formula.

    Two residuals are reported:
      - `delta_residual`:    (frame - anchor) actual  vs  (frame_pred - identity)
                             cancels common quantization floor / over-scan affine
                             residual, so this is the model-discriminating metric.
      - `absolute_residual`: legacy `actual vs pred` for sanity comparison only.
    """
    R, G = read_uvprobe_exr(path)
    if R.shape != (height, width):
        raise ValueError(f"{path.name}: shape {R.shape} != {(height, width)}")

    usable_span = 1.0 - 2.0 * overscan_margin
    R_corr = (R - overscan_margin) / usable_span
    G_corr = (G - overscan_margin) / usable_span
    R0_corr = (R0 - overscan_margin) / usable_span
    G0_corr = (G0 - overscan_margin) / usable_span

    out_x_norm, out_y_norm = _pixel_grids(width, height, half_width)
    out_x_norm = np.broadcast_to(out_x_norm, (height, width))
    out_y_norm = np.broadcast_to(out_y_norm, (height, width))
    k1 = value if axis == 1 else 0.0
    k2 = value if axis == 2 else 0.0
    k3 = value if axis == 3 else 0.0
    formula_fn = _FORMULA_DISPATCH[formula]
    pred_x_norm, pred_y_norm = formula_fn(
        out_x_norm,
        out_y_norm,
        k1=k1,
        k2=k2,
        k3=k3,
    )
    pred_u, pred_v = _raw_uv_from_norm(pred_x_norm, pred_y_norm, width, height, half_width)

    actual_valid = (
        (R > VALID_UV_MIN) & (R < VALID_UV_MAX)
        & (G > VALID_UV_MIN) & (G < VALID_UV_MAX)
        & (R0 > VALID_UV_MIN) & (R0 < VALID_UV_MAX)
        & (G0 > VALID_UV_MIN) & (G0 < VALID_UV_MAX)
    )
    pred_valid = (
        (pred_u > VALID_UV_MIN) & (pred_u < VALID_UV_MAX) &
        (pred_v > VALID_UV_MIN) & (pred_v < VALID_UV_MAX)
    )
    joint_valid = actual_valid & pred_valid
    valid_idx = np.flatnonzero(joint_valid.ravel())
    if valid_idx.size == 0:
        raise RuntimeError(f"{path.name}: no joint-valid pixels")

    sample_count = min(samples_per_frame, int(valid_idx.size))
    sample = rng.choice(valid_idx, size=sample_count, replace=False)
    ys, xs = np.unravel_index(sample, (height, width))

    actual_x_norm = (R_corr[ys, xs] * width - width / 2.0) / half_width
    actual_y_norm = (G_corr[ys, xs] * height - height / 2.0) / half_width
    anchor_x_norm = (R0_corr[ys, xs] * width - width / 2.0) / half_width
    anchor_y_norm = (G0_corr[ys, xs] * height - height / 2.0) / half_width
    pred_x = pred_x_norm[ys, xs]
    pred_y = pred_y_norm[ys, xs]
    out_x_sample = out_x_norm[ys, xs]
    out_y_sample = out_y_norm[ys, xs]

    # Delta-residual: (frame - anchor) vs (pred - identity). Cancels the
    # quantization/affine floor that anchor and frame share, leaving K-specific
    # modeling error.
    delta_actual_x = actual_x_norm - anchor_x_norm
    delta_actual_y = actual_y_norm - anchor_y_norm
    delta_pred_x = pred_x - out_x_sample
    delta_pred_y = pred_y - out_y_sample
    delta_err_px = np.hypot(
        delta_actual_x - delta_pred_x,
        delta_actual_y - delta_pred_y,
    ) * half_width

    # Absolute residual (legacy): actual src vs pred src. Sensitive to
    # quantization floor common to anchor + frame, so dominated by ~3 px floor
    # at half-float precision. Kept for sanity comparison.
    abs_err_px = np.hypot(actual_x_norm - pred_x, actual_y_norm - pred_y) * half_width

    # Full-width norm: in 16:9 4K, corner radius ≈ 0.574, so the populated
    # range is [0, ~0.6]. Buckets are sized accordingly so the edge bucket
    # actually receives pixels.
    r_out = np.hypot(out_x_sample, out_y_sample)
    radius_buckets = []
    for lo, hi, label in (
        (0.00, 0.15, "center"),
        (0.15, 0.30, "inner_mid"),
        (0.30, 0.45, "outer_mid"),
        (0.45, 0.65, "edge"),
    ):
        mask = (r_out >= lo) & (r_out < hi)
        if np.any(mask):
            row = {"bucket": label, "r_lo": lo, "r_hi": hi}
            row.update(format_stats(delta_err_px[mask]))
            radius_buckets.append(row)

    total_px = width * height
    actual_only = int(np.count_nonzero(actual_valid & ~pred_valid))
    pred_only = int(np.count_nonzero(pred_valid & ~actual_valid))
    both_valid = int(np.count_nonzero(joint_valid))
    both_invalid = total_px - both_valid - actual_only - pred_only
    return {
        "file": path.name,
        "axis": f"K{axis}",
        "value": value,
        "sampled": sample_count,
        "delta_residual": format_stats(delta_err_px),
        "absolute_residual": format_stats(abs_err_px),
        "radius_buckets": radius_buckets,
        "valid_mask": {
            "pixels": total_px,
            "both_valid": both_valid,
            "actual_valid_pred_invalid": actual_only,
            "pred_valid_actual_invalid": pred_only,
            "both_invalid": both_invalid,
            "mask_mismatch_pct": 100.0 * (actual_only + pred_only) / total_px,
        },
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Gate 6 K2/K3 Custom Formula Evaluation",
        "",
        f"- Verdict: **{report['verdict']}**",
        f"- Formula: **{report.get('formula', 'forward')}**",
        f"- Normalization: **{report.get('normalization', 'full-width')}**",
        f"- Threshold: per-frame and per-radius `p95(delta_residual) < {report['threshold_p95_px']} px`",
        f"- Validation root: `{report['validation_root']}`",
        "- `delta` = `(frame_actual − anchor_actual) − (frame_pred − identity)` — model-discriminating, cancels common quantization/affine floor.",
        "- `abs` = `actual − pred` (legacy absolute residual) — sensitive to half-float floor (~3 px), kept for sanity comparison.",
        "",
        "| frame | axis | value | delta med | delta p95 | delta p99 | delta RMS | abs med | abs p95 | mask % |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for frame in report["frames"]:
        d = frame["delta_residual"]
        a = frame["absolute_residual"]
        vm = frame["valid_mask"]
        lines.append(
            f"| `{frame['file']}` | {frame['axis']} | {frame['value']:+.3f} | "
            f"{d['median_px']:.3f} | {d['p95_px']:.3f} | {d['p99_px']:.3f} | {d['rms_px']:.3f} | "
            f"{a['median_px']:.3f} | {a['p95_px']:.3f} | "
            f"{vm['mask_mismatch_pct']:.3f} |"
        )
    lines.extend(["", "## Failed Buckets (delta-residual)", ""])
    if report["failed_buckets"]:
        lines.append("| frame | bucket | p95 px | max px |")
        lines.append("|---|---|---:|---:|")
        for row in report["failed_buckets"]:
            lines.append(
                f"| `{row['file']}` | `{row['bucket']}` | "
                f"{row['p95_px']:.3f} | {row['max_px']:.3f} |"
            )
    else:
        lines.append("No failed buckets.")
    lines.append("")
    return "\n".join(lines)


def evaluate_directory(
    validation_root: Path,
    *,
    output_json: Path,
    output_md: Path,
    probe_truth: Path | None,
    samples_per_frame: int,
    seed: int,
    threshold_p95_px: float,
    formula: str = "forward",
    normalization: str = "full-width",
) -> dict[str, object]:
    if not validation_root.is_dir():
        raise RuntimeError(f"validation root not found: {validation_root}")
    sweep_dirs = [
        validation_root / "k1_sweep",
        validation_root / "custom_pp_gate_inputs" / "k2_k3_sweep",
    ]
    exr_files: list[Path] = []
    for d in sweep_dirs:
        if d.is_dir():
            exr_files.extend(sorted(d.glob("disguise_K*.exr")))
    if not exr_files:
        raise RuntimeError(
            f"no disguise_K*.exr files under {sweep_dirs}; expected k1_sweep/ and k2_k3_sweep/"
        )

    width_probe, height_probe, width_camera, height_camera = load_probe_meta(probe_truth)
    if width_probe != width_camera or height_probe != height_camera:
        raise RuntimeError("Gate 6 expects nominal 4K EXR dimensions; over-scan is lens-side affine")
    half_width = normalization_factor(normalization, width_camera)

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

    rng = np.random.default_rng(seed)
    frames = []
    failed = []
    for path in exr_files:
        try:
            axis, value = parse_axis_value(path.stem)
        except ValueError:
            continue
        if abs(value) < 1e-9:
            continue
        R0, G0, _, overscan_margin = get_anchor(axis)
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
        frames.append(frame)
        # Use delta-residual (model-discriminating) for verdict, not absolute_residual.
        if frame["delta_residual"]["p95_px"] >= threshold_p95_px:
            failed.append({
                "file": frame["file"],
                "bucket": "overall",
                **frame["delta_residual"],
            })
        for bucket in frame["radius_buckets"]:
            if bucket["p95_px"] >= threshold_p95_px:
                failed.append({
                    "file": frame["file"],
                    **bucket,
                })

    if not frames:
        raise RuntimeError("no non-zero K frames found")

    report = {
        "gate": "Gate 6",
        "validation_root": str(validation_root),
        "formula": formula,
        "normalization": normalization,
        "probe": {"width": width_probe, "height": height_probe},
        "camera": {"width": width_camera, "height": height_camera},
        "anchors": {axis: SWEEP_DIR_BY_AXIS[axis][1] for axis in anchor_cache},
        "overscan_per_axis": {
            axis: {"factor": float(of), "margin": float(om)}
            for axis, (_, _, of, om) in anchor_cache.items()
        },
        "samples_per_frame": samples_per_frame,
        "threshold_p95_px": threshold_p95_px,
        "frames": frames,
        "failed_buckets": failed,
        "verdict": "GO" if not failed else "NO-GO",
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_comparison_markdown(
    reports: list[dict[str, object]],
    threshold_p95_px: float,
) -> str:
    """Render a single comparison table where each row is one frame and
    columns are per-candidate p95(delta_residual). Surfaces the spec ordering
    'lock norm first → lock formula second' via the per-axis aggregate table.
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

    # Lookup: report_idx -> {file -> delta_p95}
    by_file_per_report: list[dict[str, float]] = []
    for r in reports:
        file_p95: dict[str, float] = {}
        for frame in r["frames"]:
            file_p95[frame["file"]] = frame["delta_residual"]["p95_px"]
        by_file_per_report.append(file_p95)

    # Use the first report's frame ordering as canonical row order
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

    # Aggregate per-axis max p95 across all frames
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
        # Per-candidate output paths get a suffix so the directory shows all of them.
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
        json.dumps(
            {"candidates": candidate_reports, "threshold_p95_px": threshold_p95_px},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"candidates": candidate_reports, "threshold_p95_px": threshold_p95_px}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-root", type=Path, default=DEFAULT_VALIDATION_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--md-output", type=Path, default=DEFAULT_MD_OUTPUT)
    parser.add_argument("--probe-truth", type=Path, default=None)
    parser.add_argument("--samples-per-frame", type=int, default=DEFAULT_SAMPLES_PER_FRAME)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threshold-p95-px", type=float, default=DEFAULT_THRESHOLD_P95_PX)
    parser.add_argument(
        "--formula",
        choices=tuple(_FORMULA_DISPATCH.keys()),
        default="forward",
        help="Distortion model to test (forward Brown-Conrady or division/Fitzgibbon)",
    )
    parser.add_argument(
        "--normalization",
        choices=NORMALIZATION_MODES,
        default="full-width",
        help="Radius normalization: full-width (sensor full width) or half-width (legacy)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run the default candidate matrix (3 specs) and emit a comparison markdown",
    )
    args = parser.parse_args()

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

    report = evaluate_directory(
        args.validation_root,
        output_json=args.output,
        output_md=args.md_output,
        probe_truth=args.probe_truth,
        samples_per_frame=args.samples_per_frame,
        seed=args.seed,
        threshold_p95_px=args.threshold_p95_px,
        formula=args.formula,
        normalization=args.normalization,
    )
    print(f"wrote {args.output}")
    print(f"wrote {args.md_output}")
    print(f"verdict={report['verdict']}")
    if report["verdict"] != "GO":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
