"""Compare UE Path C render output against Python reference.

The comparison script is intentionally usable before UE render output exists:
missing inputs emit a BLOCKED JSON/Markdown report instead of raising a code
failure. That keeps environment/RHI blockers separate from shader correctness.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np


os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")


def _load_cv2():
    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise SystemExit(f"OpenCV import failed: {exc}") from exc
    return cv2


def _read_image(path: Path) -> np.ndarray:
    cv2 = _load_cv2()
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"could not read image: {path}")
    if image.ndim == 2:
        image = image[..., None]
    if np.issubdtype(image.dtype, np.integer):
        image = image.astype(np.float32) / float(np.iinfo(image.dtype).max)
        return image
    image = image.astype(np.float32)
    if image.max(initial=0.0) > 2.0:
        image /= 255.0
    return image


def _path_status(path: Path) -> dict[str, object]:
    return {"path": str(path), "exists": path.exists()}


def _write_reports(payload: dict[str, object], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        f"# Path C Render Compare - {payload.get('case', 'unknown')}",
        "",
        f"- Status: `{payload['status']}`",
        f"- Input probe: `{payload['input_probe']['path']}`",
        f"- Reference base: `{payload['reference_base']['path']}`",
        f"- UE render: `{payload['ue_render']['path']}`",
        f"- Reference mode: `{payload.get('reference_mode', 'n/a')}`",
        f"- Metric unit: `{payload.get('metric_unit', 'n/a')}`",
        "",
    ]
    if payload["status"] == "PASS":
        metrics = payload["metrics"]
        lines.extend([
            "## Metrics",
            "",
            f"- RMS: `{metrics['rms']:.8f}`",
            f"- Median: `{metrics['median']:.8f}`",
            f"- P95: `{metrics['p95']:.8f}`",
            f"- Max: `{metrics['max']:.8f}`",
            f"- Changed values: `{metrics['changed_values']}`",
            f"- Changed value ratio: `{metrics['changed_value_ratio']:.8f}`",
            f"- Valid-mask mismatch ratio: `{metrics['valid_mask_mismatch_ratio']:.8f}`",
            f"- Valid RMS: `{metrics['valid_rms']:.8f}`",
            f"- Valid median: `{metrics['valid_median']:.8f}`",
            f"- Valid P95: `{metrics['valid_p95']:.8f}`",
            f"- Valid max: `{metrics['valid_max']:.8f}`",
            f"- Valid changed values: `{metrics['valid_changed_values']}`",
            f"- Valid changed value ratio: `{metrics['valid_changed_value_ratio']:.8f}`",
            "",
        ])
    else:
        lines.extend([
            "## Blocker",
            "",
            str(payload.get("reason", "unknown")),
            "",
        ])
    output_md.write_text("\n".join(lines), encoding="utf-8")


def _case_coefficients(case: str) -> tuple[float, float, float, float]:
    if case == "identity":
        return 0.5, 0.0, 0.0, 0.0
    if case == "k1":
        return 0.5, 0.0, 0.0, 1.0
    if case == "k2":
        return 0.0, 0.5, 0.0, 1.0
    if case == "k3":
        return 0.0, 0.0, 0.5, 1.0
    raise ValueError(f"unsupported case: {case}")


def _build_reference(
    reference_base: np.ndarray,
    *,
    case: str,
    center_u: float,
    center_v: float,
    aspect: float,
) -> tuple[np.ndarray, np.ndarray]:
    cv2 = _load_cv2()
    h, w = reference_base.shape[:2]
    k1, k2, k3, weight = _case_coefficients(case)

    xs = np.arange(w, dtype=np.float32)
    ys = np.arange(h, dtype=np.float32)
    u = (xs[None, :] + 0.5) / float(w)
    v = (ys[:, None] + 0.5) / float(h)
    dx = u - center_u
    dy = v - center_v
    rx = dx
    ry = dy / aspect
    r2 = rx * rx + ry * ry
    factor = k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
    source_u = u + factor * dx * weight
    source_v = v + factor * dy * weight

    map_x = (source_u * float(w) - 0.5).astype(np.float32)
    map_y = (source_v * float(h) - 0.5).astype(np.float32)
    reference = cv2.remap(
        reference_base,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    valid = (
        (source_u >= 0.0)
        & (source_u <= 1.0)
        & (source_v >= 0.0)
        & (source_v <= 1.0)
    )
    return reference, valid


def _metrics(ue_render: np.ndarray, reference: np.ndarray, valid: np.ndarray) -> dict[str, object]:
    if ue_render.ndim == 3 and reference.ndim == 3 and ue_render.shape[:2] == reference.shape[:2]:
        if ue_render.shape[2] == 4:
            ue_render = ue_render[:, :, :3]
        if reference.shape[2] == 4:
            reference = reference[:, :, :3]

    if ue_render.shape != reference.shape:
        raise ValueError(f"shape mismatch: UE {ue_render.shape} vs reference {reference.shape}")

    diff = np.abs(ue_render.astype(np.float32) - reference.astype(np.float32))
    flat = diff.reshape(-1)
    changed = flat > (1.0 / 255.0)
    valid_diff = diff[valid]
    valid_flat = valid_diff.reshape(-1) if valid_diff.size else flat[:0]
    valid_changed = valid_flat > (1.0 / 255.0)

    ue_nonzero = np.any(np.abs(ue_render) > (1.0 / 255.0), axis=2)
    ref_nonzero = np.any(np.abs(reference) > (1.0 / 255.0), axis=2)
    valid_mismatch = np.logical_xor(ue_nonzero, ref_nonzero)

    return {
        "rms": float(np.sqrt(np.mean(flat * flat))),
        "median": float(np.median(flat)),
        "p95": float(np.percentile(flat, 95.0)),
        "max": float(np.max(flat)),
        "changed_values": int(np.count_nonzero(changed)),
        "changed_value_ratio": float(np.mean(changed)),
        "valid_mask_mismatch_ratio": float(np.mean(valid_mismatch)),
        "reference_valid_ratio": float(np.mean(valid)),
        "valid_rms": float(np.sqrt(np.mean(valid_flat * valid_flat))) if valid_flat.size else 0.0,
        "valid_median": float(np.median(valid_flat)) if valid_flat.size else 0.0,
        "valid_p95": float(np.percentile(valid_flat, 95.0)) if valid_flat.size else 0.0,
        "valid_max": float(np.max(valid_flat)) if valid_flat.size else 0.0,
        "valid_changed_values": int(np.count_nonzero(valid_changed)),
        "valid_changed_value_ratio": float(np.mean(valid_changed)) if valid_flat.size else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("identity", "k1", "k2", "k3"), required=True)
    parser.add_argument("--input-probe", type=Path, required=True)
    parser.add_argument("--ue-render", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--reference-base", type=Path)
    parser.add_argument("--center-u", type=float, default=0.5)
    parser.add_argument("--center-v", type=float, default=0.5)
    parser.add_argument("--aspect", type=float, default=16.0 / 9.0)
    args = parser.parse_args()

    reference_base_path = args.reference_base or args.input_probe

    payload: dict[str, object] = {
        "status": "BLOCKED",
        "case": args.case,
        "input_probe": _path_status(args.input_probe),
        "reference_base": _path_status(reference_base_path),
        "ue_render": _path_status(args.ue_render),
        "reference_mode": "official_sensor_inverse_uv vectorized formula"
        + (" from UE identity render" if args.reference_base else " from input probe"),
        "metric_unit": "normalized channel absolute difference [0,1]",
    }

    missing = [
        label
        for label, path in (
            ("input probe", args.input_probe),
            ("reference base", reference_base_path),
            ("UE render", args.ue_render),
        )
        if not path.exists()
    ]
    if missing:
        payload["reason"] = "missing file(s): " + ", ".join(missing)
        _write_reports(payload, args.output_json, args.output_md)
        return

    try:
        reference_base = _read_image(reference_base_path)
        ue_render = _read_image(args.ue_render)
        reference, valid = _build_reference(
            reference_base,
            case=args.case,
            center_u=args.center_u,
            center_v=args.center_v,
            aspect=args.aspect,
        )
        payload["metrics"] = _metrics(ue_render, reference, valid)
        payload["status"] = "PASS"
        payload["reason"] = ""
    except Exception as exc:
        payload["status"] = "FAIL"
        payload["reason"] = str(exc)

    _write_reports(payload, args.output_json, args.output_md)
    if payload["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
