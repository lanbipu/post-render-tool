"""Evaluate K2/K3 Disguise renders against the simple custom PP formula.

This script is the local half of Gate 6. It reads UV-probe EXRs requested in
docs/d3-distortion-render-request.md, compares Disguise's encoded source UV
against the current simple shader candidate:

    source_norm = output_norm * (1 + K1*r2 + K2*r4 + K3*r6)

and emits JSON + Markdown readiness reports. It intentionally does not fit a
new model; it answers whether the current simple K2/K3 assumption is viable.
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


DEFAULT_INPUT_DIR = Path("validation_results/custom_pp_gate_inputs/k2_k3_sweep")
DEFAULT_OUTPUT = Path("/Volumes/Docs/temp/k_sweep/gate6_k2_k3_custom_formula.json")
DEFAULT_MD_OUTPUT = Path("/Volumes/Docs/temp/k_sweep/gate6_k2_k3_custom_formula.md")
DEFAULT_SAMPLES_PER_FRAME = 200_000
DEFAULT_THRESHOLD_P95_PX = 1.5


def parse_axis_value(stem: str) -> tuple[int, float]:
    """Parse disguise_K2_p0p3 style filenames."""
    axis, value = parse_k_value(stem)
    if axis not in (2, 3):
        raise ValueError(f"expected K2/K3 filename, got K{axis}: {stem}")
    return axis, value


def source_norm_from_official_formula(
    out_x_norm: np.ndarray,
    out_y_norm: np.ndarray,
    *,
    k1: float,
    k2: float,
    k3: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Predict source coordinates in sensor-width normalized space."""
    r2 = out_x_norm * out_x_norm + out_y_norm * out_y_norm
    r4 = r2 * r2
    r6 = r4 * r2
    factor = k1 * r2 + k2 * r4 + k3 * r6
    scale = 1.0 + factor
    return out_x_norm * scale, out_y_norm * scale


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


def _find_anchor(exr_files: list[Path]) -> Path:
    for path in sorted(exr_files):
        try:
            axis, value = parse_axis_value(path.stem)
        except ValueError:
            continue
        if axis in (2, 3) and abs(value) < 1e-9:
            return path
    raise RuntimeError("missing K2/K3 zero anchor EXR")


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
    overscan_margin: float,
    width: int,
    height: int,
    half_width: float,
    rng: np.random.Generator,
    samples_per_frame: int,
) -> dict[str, object]:
    R, G = read_uvprobe_exr(path)
    if R.shape != (height, width):
        raise ValueError(f"{path.name}: shape {R.shape} != {(height, width)}")

    usable_span = 1.0 - 2.0 * overscan_margin
    R_corr = (R - overscan_margin) / usable_span
    G_corr = (G - overscan_margin) / usable_span

    out_x_norm, out_y_norm = _pixel_grids(width, height, half_width)
    k1 = value if axis == 1 else 0.0
    k2 = value if axis == 2 else 0.0
    k3 = value if axis == 3 else 0.0
    pred_x_norm, pred_y_norm = source_norm_from_official_formula(
        out_x_norm,
        out_y_norm,
        k1=k1,
        k2=k2,
        k3=k3,
    )
    pred_u, pred_v = _raw_uv_from_norm(pred_x_norm, pred_y_norm, width, height, half_width)

    actual_valid = (
        (R > VALID_UV_MIN) & (R < VALID_UV_MAX) &
        (G > VALID_UV_MIN) & (G < VALID_UV_MAX)
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
    pred_x = pred_x_norm[ys, xs]
    pred_y = pred_y_norm[ys, xs]
    err_px = np.hypot(actual_x_norm - pred_x, actual_y_norm - pred_y) * half_width

    r_out = np.hypot(out_x_norm[ys, xs], out_y_norm[ys, xs])
    radius_buckets = []
    for lo, hi, label in (
        (0.0, 0.3, "center"),
        (0.3, 0.6, "inner_mid"),
        (0.6, 0.9, "outer_mid"),
        (0.9, 1.3, "edge"),
    ):
        mask = (r_out >= lo) & (r_out < hi)
        if np.any(mask):
            row = {"bucket": label, "r_lo": lo, "r_hi": hi}
            row.update(format_stats(err_px[mask]))
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
        "overall": format_stats(err_px),
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
        f"- Threshold: per-frame and per-radius `p95 < {report['threshold_p95_px']} px`",
        f"- Input: `{report['input_dir']}`",
        "",
        "| frame | axis | value | median px | p95 px | p99 px | RMS px | max px | mask mismatch % |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for frame in report["frames"]:
        s = frame["overall"]
        vm = frame["valid_mask"]
        lines.append(
            f"| `{frame['file']}` | {frame['axis']} | {frame['value']:+.3f} | "
            f"{s['median_px']:.3f} | {s['p95_px']:.3f} | {s['p99_px']:.3f} | "
            f"{s['rms_px']:.3f} | {s['max_px']:.3f} | {vm['mask_mismatch_pct']:.3f} |"
        )
    lines.extend(["", "## Failed Buckets", ""])
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
    input_dir: Path,
    *,
    output_json: Path,
    output_md: Path,
    probe_truth: Path | None,
    samples_per_frame: int,
    seed: int,
    threshold_p95_px: float,
) -> dict[str, object]:
    if not input_dir.is_dir():
        raise RuntimeError(f"input dir not found: {input_dir}")
    exr_files = sorted(input_dir.rglob("disguise_*.exr"))
    if not exr_files:
        raise RuntimeError(f"no disguise_*.exr files under {input_dir}")

    width_probe, height_probe, width_camera, height_camera = load_probe_meta(probe_truth)
    if width_probe != width_camera or height_probe != height_camera:
        raise RuntimeError("Gate 6 expects nominal 4K EXR dimensions; over-scan is lens-side affine")
    half_width = width_camera / 2.0

    anchor = _find_anchor(exr_files)
    R0, G0 = read_uvprobe_exr(anchor)
    overscan_factor, overscan_margin = detect_overscan_from_anchor(R0, G0)

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
        frame = evaluate_frame(
            path,
            axis,
            value,
            overscan_margin=overscan_margin,
            width=width_camera,
            height=height_camera,
            half_width=half_width,
            rng=rng,
            samples_per_frame=samples_per_frame,
        )
        frames.append(frame)
        if frame["overall"]["p95_px"] >= threshold_p95_px:
            failed.append({
                "file": frame["file"],
                "bucket": "overall",
                **frame["overall"],
            })
        for bucket in frame["radius_buckets"]:
            if bucket["p95_px"] >= threshold_p95_px:
                failed.append({
                    "file": frame["file"],
                    **bucket,
                })

    if not frames:
        raise RuntimeError("no non-zero K2/K3 frames found")

    report = {
        "gate": "Gate 6",
        "input_dir": str(input_dir),
        "probe": {"width": width_probe, "height": height_probe},
        "camera": {"width": width_camera, "height": height_camera},
        "anchor": anchor.name,
        "overscan_factor": float(overscan_factor),
        "overscan_margin": float(overscan_margin),
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--md-output", type=Path, default=DEFAULT_MD_OUTPUT)
    parser.add_argument("--probe-truth", type=Path, default=None)
    parser.add_argument("--samples-per-frame", type=int, default=DEFAULT_SAMPLES_PER_FRAME)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threshold-p95-px", type=float, default=DEFAULT_THRESHOLD_P95_PX)
    args = parser.parse_args()

    report = evaluate_directory(
        args.input_dir,
        output_json=args.output,
        output_md=args.md_output,
        probe_truth=args.probe_truth,
        samples_per_frame=args.samples_per_frame,
        seed=args.seed,
        threshold_p95_px=args.threshold_p95_px,
    )
    print(f"wrote {args.output}")
    print(f"wrote {args.md_output}")
    print(f"verdict={report['verdict']}")
    if report["verdict"] != "GO":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
