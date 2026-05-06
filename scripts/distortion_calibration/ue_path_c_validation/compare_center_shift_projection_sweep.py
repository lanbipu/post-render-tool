"""Compare Path C centerShift projection sign-sweep renders against D3.

The UE-side sweep dispatches one render per sign/case. This Mac-side script
pulls those renders into a local directory, phase-correlates each case against
its zero anchor, and selects the sign pair with the lowest primary-axis
centerShift residual.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


CENTER_SHIFT_CASES = (
    "path_c_center_k1_p0p5_shiftx_n0p5",
    "path_c_center_k1_p0p5_shiftx_p0p5",
    "path_c_center_k1_p0p5_shifty_n0p5",
    "path_c_center_k1_p0p5_shifty_p0p5",
)
ANCHOR_CASE = "path_c_center_k1_p0p5_shift_zero"
SIGN_SWEEPS = {
    "xp_yp_height": {"x_sign":  1.0, "y_sign":  1.0, "y_normalizer": "sensor_height"},
    "xp_yn_height": {"x_sign":  1.0, "y_sign": -1.0, "y_normalizer": "sensor_height"},
    "xn_yp_height": {"x_sign": -1.0, "y_sign":  1.0, "y_normalizer": "sensor_height"},
    "xn_yn_height": {"x_sign": -1.0, "y_sign": -1.0, "y_normalizer": "sensor_height"},
    "xp_yp_width":  {"x_sign":  1.0, "y_sign":  1.0, "y_normalizer": "sensor_width"},
    "xp_yn_width":  {"x_sign":  1.0, "y_sign": -1.0, "y_normalizer": "sensor_width"},
    "xn_yp_width":  {"x_sign": -1.0, "y_sign":  1.0, "y_normalizer": "sensor_width"},
    "xn_yn_width":  {"x_sign": -1.0, "y_sign": -1.0, "y_normalizer": "sensor_width"},
}


def _load_cv2():
    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise SystemExit(f"OpenCV import failed: {exc}") from exc
    return cv2


def _read_gray(path: Path) -> np.ndarray:
    cv2 = _load_cv2()
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"could not read image: {path}")
    if image.ndim == 3:
        if image.shape[2] == 4:
            image = image[:, :, :3]
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if np.issubdtype(image.dtype, np.integer):
        image = image.astype(np.float32) / float(np.iinfo(image.dtype).max)
    else:
        image = image.astype(np.float32)
        if image.max(initial=0.0) > 2.0:
            image /= 255.0
    return image


def _phase(anchor: np.ndarray, image: np.ndarray) -> dict[str, float]:
    cv2 = _load_cv2()
    if anchor.shape != image.shape:
        raise ValueError(f"shape mismatch: anchor {anchor.shape}, image {image.shape}")
    (shift_x, shift_y), response = cv2.phaseCorrelate(anchor, image)
    return {
        "shift_x_px": float(shift_x),
        "shift_y_px": float(shift_y),
        "response": float(response),
    }


def _primary_axis(case_id: str) -> str:
    if "shiftx_" in case_id:
        return "x"
    if "shifty_" in case_id:
        return "y"
    raise ValueError(f"unknown centerShift case axis: {case_id}")


def _stats(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    return {
        "rms": float(math.sqrt(float(np.mean(arr * arr)))) if arr.size else 0.0,
        "median_abs": float(np.median(np.abs(arr))) if arr.size else 0.0,
        "p95_abs": float(np.percentile(np.abs(arr), 95.0)) if arr.size else 0.0,
        "max_abs": float(np.max(np.abs(arr))) if arr.size else 0.0,
    }


def _image_path(root: Path, case_id: str) -> Path:
    return root / f"{case_id}.png"


def _ue_image_path(root: Path, sign_id: str, case_id: str) -> Path:
    return root / sign_id / case_id / f"{case_id}.0000.png"


def _write_reports(payload: dict[str, object], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Path C centerShift Projection Sign Sweep",
        "",
        f"- Status: `{payload['status']}`",
        f"- D3 centerShift root: `{payload['d3_center_shift_root']}`",
        f"- UE sweep root: `{payload['ue_sweep_root']}`",
        f"- Acceptance threshold: `{payload['acceptance_threshold_px']:.3f}px`",
        "",
    ]
    selected = payload.get("selected_sign")
    if selected:
        lines.extend(
            [
                "## Selected Sign",
                "",
                f"- Sign id: `{selected['sign_id']}`",
                f"- X sign: `{selected['x_sign']}`",
                f"- Y sign: `{selected['y_sign']}`",
                f"- Y normalizer: `{selected['y_normalizer']}`",
                f"- Primary RMS: `{selected['primary_stats']['rms']:.6f}px`",
                f"- Primary P95 abs: `{selected['primary_stats']['p95_abs']:.6f}px`",
                f"- Primary max abs: `{selected['primary_stats']['max_abs']:.6f}px`",
                f"- Direction status: `{selected['direction_status']}`",
                "",
            ]
        )
    if payload.get("reason"):
        lines.extend(["## Reason", "", str(payload["reason"]), ""])
    lines.extend(["## Sign Matrix", ""])
    lines.append(
        "| sign_id | x_sign | y_sign | y_normalizer | rms_px | p95_abs_px | max_abs_px | direction |"
    )
    lines.append("|---|---:|---:|---|---:|---:|---:|---|")
    for item in payload.get("sign_results", []):
        stats = item.get("primary_stats", {})
        lines.append(
            "| `{sign_id}` | x `{x_sign}` | y `{y_sign}` | norm `{y_norm}` | "
            "rms `{rms:.6f}` | p95 `{p95:.6f}` | max `{max_abs:.6f}` | `{direction}` |".format(
                sign_id=item["sign_id"],
                x_sign=item["x_sign"],
                y_sign=item["y_sign"],
                y_norm=item.get("y_normalizer", "n/a"),
                rms=stats.get("rms", 0.0),
                p95=stats.get("p95_abs", 0.0),
                max_abs=stats.get("max_abs", 0.0),
                direction=item.get("direction_status", "n/a"),
            )
        )
    lines.extend(["", "## Case Details", ""])
    for item in payload.get("sign_results", []):
        lines.append(f"### `{item['sign_id']}`")
        for case in item.get("cases", []):
            phase = case["phase"]
            lines.append(
                "- `{case}` axis `{axis}`: D3=({d3x:.3f}, {d3y:.3f}) "
                "UE=({uex:.3f}, {uey:.3f}) delta=({dx:.3f}, {dy:.3f}) "
                "primary_delta=`{primary:.3f}px`".format(
                    case=case["case"],
                    axis=case["primary_axis"],
                    d3x=phase["d3_shift_x_px"],
                    d3y=phase["d3_shift_y_px"],
                    uex=phase["ue_shift_x_px"],
                    uey=phase["ue_shift_y_px"],
                    dx=phase["delta_x_px"],
                    dy=phase["delta_y_px"],
                    primary=case["primary_delta_px"],
                )
            )
        lines.append("")
    output_md.write_text("\n".join(lines), encoding="utf-8")


def compare(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "BLOCKED",
        "d3_center_shift_root": str(args.d3_center_shift_root),
        "ue_sweep_root": str(args.ue_sweep_root),
        "acceptance_threshold_px": args.acceptance_threshold_px,
        "sign_results": [],
    }

    d3_anchor_path = _image_path(args.d3_center_shift_root, ANCHOR_CASE)
    missing: list[str] = []
    if not d3_anchor_path.exists():
        missing.append(str(d3_anchor_path))
    for case_id in CENTER_SHIFT_CASES:
        d3_path = _image_path(args.d3_center_shift_root, case_id)
        if not d3_path.exists():
            missing.append(str(d3_path))
    for sign_id in SIGN_SWEEPS:
        anchor_path = _ue_image_path(args.ue_sweep_root, sign_id, ANCHOR_CASE)
        if not anchor_path.exists():
            missing.append(str(anchor_path))
        for case_id in CENTER_SHIFT_CASES:
            ue_path = _ue_image_path(args.ue_sweep_root, sign_id, case_id)
            if not ue_path.exists():
                missing.append(str(ue_path))
    if missing:
        payload["reason"] = "missing image file(s)"
        payload["missing_files"] = missing
        return payload

    d3_anchor = _read_gray(d3_anchor_path)
    d3_phases = {
        case_id: _phase(d3_anchor, _read_gray(_image_path(args.d3_center_shift_root, case_id)))
        for case_id in CENTER_SHIFT_CASES
    }

    for sign_id, sign_info in SIGN_SWEEPS.items():
        ue_anchor = _read_gray(_ue_image_path(args.ue_sweep_root, sign_id, ANCHOR_CASE))
        case_results = []
        primary_deltas: list[float] = []
        direction_ok = True
        for case_id in CENTER_SHIFT_CASES:
            ue_phase = _phase(
                ue_anchor,
                _read_gray(_ue_image_path(args.ue_sweep_root, sign_id, case_id)),
            )
            d3_phase = d3_phases[case_id]
            delta_x = ue_phase["shift_x_px"] - d3_phase["shift_x_px"]
            delta_y = ue_phase["shift_y_px"] - d3_phase["shift_y_px"]
            axis = _primary_axis(case_id)
            primary_delta = delta_x if axis == "x" else delta_y
            primary_deltas.append(primary_delta)
            d3_primary = d3_phase[f"shift_{axis}_px"]
            ue_primary = ue_phase[f"shift_{axis}_px"]
            if abs(d3_primary) > 1.0 and d3_primary * ue_primary <= 0.0:
                direction_ok = False
            case_results.append(
                {
                    "case": case_id,
                    "primary_axis": axis,
                    "primary_delta_px": float(primary_delta),
                    "phase": {
                        "d3_shift_x_px": d3_phase["shift_x_px"],
                        "d3_shift_y_px": d3_phase["shift_y_px"],
                        "d3_response": d3_phase["response"],
                        "ue_shift_x_px": ue_phase["shift_x_px"],
                        "ue_shift_y_px": ue_phase["shift_y_px"],
                        "ue_response": ue_phase["response"],
                        "delta_x_px": float(delta_x),
                        "delta_y_px": float(delta_y),
                    },
                }
            )

        stats = _stats(primary_deltas)
        payload["sign_results"].append(
            {
                "sign_id": sign_id,
                "x_sign": sign_info["x_sign"],
                "y_sign": sign_info["y_sign"],
                "y_normalizer": sign_info["y_normalizer"],
                "primary_stats": stats,
                "direction_status": "PASS" if direction_ok else "FAIL",
                "cases": case_results,
            }
        )

    sorted_results = sorted(
        payload["sign_results"],
        key=lambda item: (
            item["direction_status"] != "PASS",
            item["primary_stats"]["rms"],
        ),
    )
    selected = sorted_results[0]
    payload["selected_sign"] = selected
    if (
        selected["direction_status"] == "PASS"
        and selected["primary_stats"]["max_abs"] <= args.acceptance_threshold_px
    ):
        payload["status"] = "PASS"
        payload["reason"] = ""
    else:
        payload["status"] = "BLOCKED_FORMULA"
        payload["reason"] = (
            "best sign sweep did not meet direction/max-abs threshold; "
            "request K=0 centerShift-only D3 frames before production rollout"
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--d3-center-shift-root",
        type=Path,
        default=Path("validation_results/path_c_d3_exports/canonical/center_shift"),
    )
    parser.add_argument(
        "--ue-sweep-root",
        type=Path,
        default=Path("validation_results/path_c_d3_exports/center_shift_projection_sweep/ue_renders"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_v2_compare.md"),
    )
    parser.add_argument("--acceptance-threshold-px", type=float, default=3.0)
    args = parser.parse_args()

    payload = compare(args)
    _write_reports(payload, args.output_json, args.output_md)
    # Gate behavior: any non-PASS status must propagate as a non-zero exit code
    # so README / CI invocations cannot silently treat missing renders or
    # blocked-formula outcomes as success. PASS is the only "ok to continue"
    # state.
    if payload["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
