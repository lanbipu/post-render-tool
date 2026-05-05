"""Evaluate Disguise centerShift-only UV-probe renders.

This is Gate 3.5's local analyzer. It compares each centerShift frame to a
zero-shift anchor, measures the actual source-UV displacement, and reports
which sign convention best matches:

    CenterU = 0.5 + centerShiftMM.x / sensorWidthMM
    CenterV = 0.5 + centerShiftMM.y / sensorHeightMM

The script is intentionally descriptive. It does not mutate project code or
choose a production default by itself.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from _exr import load_probe_meta, read_uvprobe_exr
from analyze_renders import VALID_UV_MAX, VALID_UV_MIN, detect_overscan_from_anchor


DEFAULT_INPUT_DIR = Path("validation_results/custom_pp_gate_inputs/center_shift_sweep")
DEFAULT_OUTPUT = Path("/Volumes/Docs/temp/k_sweep/gate3_5_center_shift_sweep.json")
DEFAULT_MD_OUTPUT = Path("/Volumes/Docs/temp/k_sweep/gate3_5_center_shift_sweep.md")
DEFAULT_SENSOR_WIDTH_MM = 35.0
DEFAULT_ASPECT_RATIO = 16.0 / 9.0
DEFAULT_SAMPLES_PER_FRAME = 200_000

_CENTER_PATTERN = re.compile(
    r"^disguise_centerShift(?:(?P<axis>[XY])_(?P<sign>[pn])(?P<value>\d+(?:p\d+)?)|_(?P<zero>zero))$",
    re.IGNORECASE,
)


def parse_center_shift_value(stem: str) -> tuple[str, float]:
    """Parse disguise_centerShiftX_n0p10 style filenames."""
    match = _CENTER_PATTERN.match(stem)
    if not match:
        raise ValueError(f"cannot parse centerShift filename: {stem}")
    if match.group("zero"):
        return "zero", 0.0
    axis = match.group("axis").lower()
    sign = 1.0 if match.group("sign").lower() == "p" else -1.0
    value = float(match.group("value").lower().replace("p", "."))
    return axis, sign * value


def center_uv_from_shift(
    *,
    shift_x_mm: float,
    shift_y_mm: float,
    sensor_width_mm: float,
    aspect_ratio: float,
) -> tuple[float, float]:
    sensor_height_mm = sensor_width_mm / aspect_ratio
    center_u = 0.5 + shift_x_mm / sensor_width_mm
    center_v = 0.5 + shift_y_mm / sensor_height_mm
    return center_u, center_v


def expected_shift_pixels(
    *,
    axis: str,
    shift_mm: float,
    sensor_width_mm: float,
    aspect_ratio: float,
    width_px: int,
    height_px: int,
) -> tuple[float, float]:
    sensor_height_mm = sensor_width_mm / aspect_ratio
    if axis == "x":
        return shift_mm / sensor_width_mm * width_px, 0.0
    if axis == "y":
        return 0.0, shift_mm / sensor_height_mm * height_px
    raise ValueError(f"unsupported axis: {axis}")


def format_stats(values_px: np.ndarray) -> dict[str, float | int]:
    if values_px.size == 0:
        return {
            "n": 0,
            "median_px": float("nan"),
            "p95_px": float("nan"),
            "rms_px": float("nan"),
            "max_px": float("nan"),
        }
    return {
        "n": int(values_px.size),
        "median_px": float(np.percentile(values_px, 50)),
        "p95_px": float(np.percentile(values_px, 95)),
        "rms_px": float(np.sqrt(np.mean(values_px * values_px))),
        "max_px": float(np.max(values_px)),
    }


def _find_zero(exr_files: list[Path]) -> Path:
    for path in sorted(exr_files):
        try:
            axis, value = parse_center_shift_value(path.stem)
        except ValueError:
            continue
        if axis == "zero" and abs(value) < 1e-9:
            return path
    raise RuntimeError("missing disguise_centerShift_zero.exr anchor")


def _source_pixels(
    R: np.ndarray,
    G: np.ndarray,
    *,
    overscan_margin: float,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    usable_span = 1.0 - 2.0 * overscan_margin
    R_corr = (R - overscan_margin) / usable_span
    G_corr = (G - overscan_margin) / usable_span
    return R_corr * width, G_corr * height


def evaluate_frame(
    path: Path,
    axis: str,
    value: float,
    *,
    zero_src_x: np.ndarray,
    zero_src_y: np.ndarray,
    zero_valid: np.ndarray,
    overscan_margin: float,
    width: int,
    height: int,
    sensor_width_mm: float,
    aspect_ratio: float,
    rng: np.random.Generator,
    samples_per_frame: int,
) -> dict[str, object]:
    R, G = read_uvprobe_exr(path)
    if R.shape != (height, width):
        raise ValueError(f"{path.name}: shape {R.shape} != {(height, width)}")
    src_x, src_y = _source_pixels(
        R,
        G,
        overscan_margin=overscan_margin,
        width=width,
        height=height,
    )
    valid = (
        zero_valid &
        (R > VALID_UV_MIN) & (R < VALID_UV_MAX) &
        (G > VALID_UV_MIN) & (G < VALID_UV_MAX)
    )
    valid_idx = np.flatnonzero(valid.ravel())
    if valid_idx.size == 0:
        raise RuntimeError(f"{path.name}: no joint-valid pixels")

    sample_count = min(samples_per_frame, int(valid_idx.size))
    sample = rng.choice(valid_idx, size=sample_count, replace=False)
    ys, xs = np.unravel_index(sample, (height, width))

    delta_x = src_x[ys, xs] - zero_src_x[ys, xs]
    delta_y = src_y[ys, xs] - zero_src_y[ys, xs]
    median_dx = float(np.median(delta_x))
    median_dy = float(np.median(delta_y))
    residual = np.hypot(delta_x - median_dx, delta_y - median_dy)

    expected_dx, expected_dy = expected_shift_pixels(
        axis=axis,
        shift_mm=value,
        sensor_width_mm=sensor_width_mm,
        aspect_ratio=aspect_ratio,
        width_px=width,
        height_px=height,
    )
    plus_error = float(np.hypot(median_dx - expected_dx, median_dy - expected_dy))
    minus_error = float(np.hypot(median_dx + expected_dx, median_dy + expected_dy))
    best_sign = "+formula" if plus_error <= minus_error else "-formula"
    center_u, center_v = center_uv_from_shift(
        shift_x_mm=value if axis == "x" else 0.0,
        shift_y_mm=value if axis == "y" else 0.0,
        sensor_width_mm=sensor_width_mm,
        aspect_ratio=aspect_ratio,
    )
    return {
        "file": path.name,
        "axis": axis,
        "shift_mm": value,
        "center_u_formula": center_u,
        "center_v_formula": center_v,
        "sampled": sample_count,
        "median_dx_px": median_dx,
        "median_dy_px": median_dy,
        "expected_plus_dx_px": expected_dx,
        "expected_plus_dy_px": expected_dy,
        "plus_formula_error_px": plus_error,
        "minus_formula_error_px": minus_error,
        "best_sign": best_sign,
        "field_residual_about_median": format_stats(residual),
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Gate 3.5 CenterShift Sweep Evaluation",
        "",
        f"- Input: `{report['input_dir']}`",
        f"- Anchor: `{report['anchor']}`",
        f"- Sensor width: {report['sensor_width_mm']} mm",
        f"- Aspect ratio: {report['aspect_ratio']}",
        "",
        "| frame | axis | shift mm | median dx px | median dy px | +formula err px | -formula err px | best sign | field p95 px |",
        "|---|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for frame in report["frames"]:
        stats = frame["field_residual_about_median"]
        lines.append(
            f"| `{frame['file']}` | {frame['axis']} | {frame['shift_mm']:+.3f} | "
            f"{frame['median_dx_px']:.3f} | {frame['median_dy_px']:.3f} | "
            f"{frame['plus_formula_error_px']:.3f} | {frame['minus_formula_error_px']:.3f} | "
            f"{frame['best_sign']} | {stats['p95_px']:.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def evaluate_directory(
    input_dir: Path,
    *,
    output_json: Path,
    output_md: Path,
    probe_truth: Path | None,
    sensor_width_mm: float,
    aspect_ratio: float,
    samples_per_frame: int,
    seed: int,
) -> dict[str, object]:
    if not input_dir.is_dir():
        raise RuntimeError(f"input dir not found: {input_dir}")
    exr_files = sorted(input_dir.rglob("disguise_centerShift*.exr"))
    if not exr_files:
        raise RuntimeError(f"no disguise_centerShift*.exr files under {input_dir}")

    width_probe, height_probe, width_camera, height_camera = load_probe_meta(probe_truth)
    if width_probe != width_camera or height_probe != height_camera:
        raise RuntimeError("Gate 3.5 expects nominal camera-size EXRs")

    zero_path = _find_zero(exr_files)
    R0, G0 = read_uvprobe_exr(zero_path)
    overscan_factor, overscan_margin = detect_overscan_from_anchor(R0, G0)
    zero_src_x, zero_src_y = _source_pixels(
        R0,
        G0,
        overscan_margin=overscan_margin,
        width=width_camera,
        height=height_camera,
    )
    zero_valid = (
        (R0 > VALID_UV_MIN) & (R0 < VALID_UV_MAX) &
        (G0 > VALID_UV_MIN) & (G0 < VALID_UV_MAX)
    )

    rng = np.random.default_rng(seed)
    frames = []
    for path in exr_files:
        axis, value = parse_center_shift_value(path.stem)
        if axis == "zero":
            continue
        frames.append(
            evaluate_frame(
                path,
                axis,
                value,
                zero_src_x=zero_src_x,
                zero_src_y=zero_src_y,
                zero_valid=zero_valid,
                overscan_margin=overscan_margin,
                width=width_camera,
                height=height_camera,
                sensor_width_mm=sensor_width_mm,
                aspect_ratio=aspect_ratio,
                rng=rng,
                samples_per_frame=samples_per_frame,
            )
        )
    if not frames:
        raise RuntimeError("no non-zero centerShift frames found")

    signs = [frame["best_sign"] for frame in frames]
    sign_summary = {
        "+formula": signs.count("+formula"),
        "-formula": signs.count("-formula"),
    }
    report = {
        "gate": "Gate 3.5",
        "input_dir": str(input_dir),
        "anchor": zero_path.name,
        "probe": {"width": width_probe, "height": height_probe},
        "camera": {"width": width_camera, "height": height_camera},
        "overscan_factor": float(overscan_factor),
        "overscan_margin": float(overscan_margin),
        "sensor_width_mm": sensor_width_mm,
        "aspect_ratio": aspect_ratio,
        "samples_per_frame": samples_per_frame,
        "sign_summary": sign_summary,
        "frames": frames,
        "verdict": "GO" if sign_summary["+formula"] == len(frames) else "CHECK_SIGN",
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
    parser.add_argument("--sensor-width-mm", type=float, default=DEFAULT_SENSOR_WIDTH_MM)
    parser.add_argument("--aspect-ratio", type=float, default=DEFAULT_ASPECT_RATIO)
    parser.add_argument("--samples-per-frame", type=int, default=DEFAULT_SAMPLES_PER_FRAME)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    report = evaluate_directory(
        args.input_dir,
        output_json=args.output,
        output_md=args.md_output,
        probe_truth=args.probe_truth,
        sensor_width_mm=args.sensor_width_mm,
        aspect_ratio=args.aspect_ratio,
        samples_per_frame=args.samples_per_frame,
        seed=args.seed,
    )
    print(f"wrote {args.output}")
    print(f"wrote {args.md_output}")
    print(f"verdict={report['verdict']}")
    if report["verdict"] != "GO":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
