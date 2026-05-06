"""Offline numpy simulation of UE Path C centerShift behavior.

DEPRECATED 2026-05-07. The simulation here was built on the assumption that
`map_center_shift_projection` divided centerShiftMM by focalLengthMM
(RenderStream NDC mapping) — which K=0 control frames disproved. The current
production formula has no `focal_length_mm`/`x_sign`/`y_sign`/`y_normalizer`
parameters, so the call below would TypeError. Kept in tree as historical
artefact; running it raises.

To validate the current formula offline against the K=0 D3 frames, write a new
small script — phase-correlate each shift case against the K=0 anchor at
`validation_results/path_c_d3_exports/canonical/center_shift_k_zero/`.

Warps the existing D3 zero-anchor frame with the predicted UE displacement
field for 8 cases (K1=0 vs K1=0.5) × (centerShiftMM ∈ ±0.5 X/Y), then
phase-correlates each warped image against the zero-anchor to predict the
global pixel shift UE will produce.

Decision rule: if predicted Y phase shift at K1=0.5 ≈ 21 px (matches D3
measurement), the residual is K1 distortion coupling and Stage 3 UE sweep
is the next step. Otherwise Stage 4 fresh D3 K=0 frames are required.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# Allow running from repo root: scripts/distortion_calibration/ue_path_c_validation/...
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Content" / "Python"))

from post_render_tool.distortion_math import (  # noqa: E402
    map_center_shift_projection,
)


SENSOR_WIDTH_MM = 35.0
ASPECT = 1.77779
FOCAL_LENGTH_MM = 30.302
IMAGE_W = 1920
IMAGE_H = 1080

ANCHOR_PATH = Path(
    "validation_results/path_c_d3_exports/canonical/center_shift/"
    "path_c_center_k1_p0p5_shift_zero.png"
)

CASES = (
    ("k_zero_shiftx_n0p5",  0.0, -0.5,  0.0),
    ("k_zero_shiftx_p0p5",  0.0,  0.5,  0.0),
    ("k_zero_shifty_n0p5",  0.0,  0.0, -0.5),
    ("k_zero_shifty_p0p5",  0.0,  0.0,  0.5),
    ("k1_p0p5_shiftx_n0p5", 0.5, -0.5,  0.0),
    ("k1_p0p5_shiftx_p0p5", 0.5,  0.5,  0.0),
    ("k1_p0p5_shifty_n0p5", 0.5,  0.0, -0.5),
    ("k1_p0p5_shifty_p0p5", 0.5,  0.0,  0.5),
)


def _load_anchor(anchor_path: Path) -> np.ndarray:
    import cv2
    image = cv2.imread(str(anchor_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FileNotFoundError(f"missing anchor: {anchor_path}")
    if image.ndim == 3:
        if image.shape[2] == 4:
            image = image[:, :, :3]
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if np.issubdtype(image.dtype, np.integer):
        image = image.astype(np.float32) / float(np.iinfo(image.dtype).max)
    else:
        image = image.astype(np.float32)
    return image


def _warp_anchor(
    anchor: np.ndarray,
    *,
    k1: float,
    shift_x_mm: float,
    shift_y_mm: float,
    y_normalizer: str,
) -> np.ndarray:
    """Warp the anchor frame with the predicted UE Path C displacement field.

    UE pipeline being simulated:
      1. CineCamera projects with shifted principal point (NDC translation
         post-projection). For an output pixel (u, v), the corresponding
         input world point lands at (u - cx_ndc * image_w/2, v - cy_ndc * image_h/2 * y_sign)
         in the unshifted projection's pixel space.
      2. Post-process material radial distortion re-samples around
         CenterUV = (0.5 + shift_x/sensor_w, 0.5 + shift_y/sensor_h).

    The combined displacement is the sample-source UV. This function builds
    a (h, w) source-pixel map per axis and uses cv2.remap to produce the warp.

    Note: K2 and K3 are hardcoded to 0 in this simulation. The CASES tuple
    only varies K1, so the radial factor is ``k1 * r²`` only.
    """
    import cv2

    mapping = map_center_shift_projection(
        center_shift_x_mm=shift_x_mm,
        center_shift_y_mm=shift_y_mm,
        sensor_width_mm=SENSOR_WIDTH_MM,
        aspect=ASPECT,
        focal_length_mm=FOCAL_LENGTH_MM,
        x_sign=1.0,
        y_sign=-1.0,
        y_normalizer=y_normalizer,
    )

    h, w = anchor.shape
    out_u = (np.arange(w, dtype=np.float64) + 0.5) / w
    out_v = (np.arange(h, dtype=np.float64) + 0.5) / h
    grid_u, grid_v = np.meshgrid(out_u, out_v)

    sensor_h_mm = SENSOR_WIDTH_MM / ASPECT
    pixel_dx = mapping.sensor_horizontal_offset_mm * (w / SENSOR_WIDTH_MM)
    pixel_dy = mapping.sensor_vertical_offset_mm * (h / sensor_h_mm)
    uv_dx = pixel_dx / w
    uv_dy = pixel_dy / h

    pre_shift_u = grid_u - uv_dx
    pre_shift_v = grid_v - uv_dy

    cu = mapping.center_u
    cv_ = mapping.center_v
    dx = pre_shift_u - cu
    dy = pre_shift_v - cv_
    rx = dx
    ry = dy / ASPECT
    r2 = rx * rx + ry * ry
    factor = k1 * r2
    src_u = pre_shift_u + factor * dx
    src_v = pre_shift_v + factor * dy

    src_x = (src_u * w - 0.5).astype(np.float32)
    src_y = (src_v * h - 0.5).astype(np.float32)
    warped = cv2.remap(
        anchor,
        src_x,
        src_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return warped


def _phase_correlate(anchor: np.ndarray, warped: np.ndarray) -> tuple[float, float, float]:
    import cv2
    (shift_x, shift_y), response = cv2.phaseCorrelate(anchor, warped)
    return float(shift_x), float(shift_y), float(response)


def _write_reports(
    results: list[dict],
    output_md: Path,
    output_json: Path,
    y_normalizer: str,
) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(
            {"y_normalizer": y_normalizer, "cases": results},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    lines = [
        "# Path C centerShift Offline Numpy Simulation",
        "",
        f"- y_normalizer: `{y_normalizer}`",
        f"- anchor: `{ANCHOR_PATH}`",
        f"- focal_length_mm: `{FOCAL_LENGTH_MM}`",
        f"- sensor_width_mm: `{SENSOR_WIDTH_MM}`",
        f"- image: `{IMAGE_W} x {IMAGE_H}`",
        "",
        "## Predicted UE Phase Shift vs D3 Measurement",
        "",
        "| case | K1 | shift_mm | predicted_x_px | predicted_y_px | response |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for r in results:
        shift = f"({r['shift_x_mm']:+.1f}, {r['shift_y_mm']:+.1f})"
        lines.append(
            "| `{cid}` | {k1:.1f} | {shift} | {x:+.3f} | {y:+.3f} | {resp:.3f} |".format(
                cid=r["case_id"],
                k1=r["k1"],
                shift=shift,
                x=r["predicted_shift_x_px"],
                y=r["predicted_shift_y_px"],
                resp=r["phase_response"],
            )
        )
    lines.extend([
        "",
        "## Decision Rule",
        "",
        "- If `k1_p0p5_shifty_n0p5` predicted_y_px ≈ +21 px (and `..._shifty_p0p5` ≈ -21 px):",
        "  21 px residual is K1 distortion coupling. Proceed to Stage 3 UE sweep.",
        "- If `k1_p0p5_shifty_*` predicted_y_px stays near ±9 px (sensor_height)",
        "  or ±16 px (sensor_width): formula has an unmodeled gap.",
        "  Skip Stage 3, proceed directly to Stage 4 D3 K=0 control frames.",
    ])
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    raise SystemExit(
        "center_shift_offline_simulation is deprecated 2026-05-07; "
        "centerShift formula is hardcoded in distortion_math.map_center_shift_projection. "
        "See docs/distortion-investigation.md '2026-05-07 — K=0 直接测量'."
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", type=Path, default=ANCHOR_PATH)
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path(
            "validation_results/path_c_d3_exports/canonical/"
            "center_shift_offline_simulation.md"
        ),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(
            "validation_results/path_c_d3_exports/canonical/"
            "center_shift_offline_simulation.json"
        ),
    )
    parser.add_argument(
        "--y-normalizer",
        choices=("sensor_height", "sensor_width"),
        default="sensor_height",
    )
    args = parser.parse_args()

    anchor = _load_anchor(args.anchor)
    if anchor.shape != (IMAGE_H, IMAGE_W):
        raise SystemExit(
            f"anchor shape {anchor.shape} != expected ({IMAGE_H}, {IMAGE_W})"
        )

    results = []
    for case_id, k1, shift_x_mm, shift_y_mm in CASES:
        warped = _warp_anchor(
            anchor,
            k1=k1,
            shift_x_mm=shift_x_mm,
            shift_y_mm=shift_y_mm,
            y_normalizer=args.y_normalizer,
        )
        px_x, px_y, response = _phase_correlate(anchor, warped)
        results.append({
            "case_id": case_id,
            "k1": k1,
            "shift_x_mm": shift_x_mm,
            "shift_y_mm": shift_y_mm,
            "predicted_shift_x_px": px_x,
            "predicted_shift_y_px": px_y,
            "phase_response": response,
        })

    _write_reports(results, args.output_md, args.output_json, args.y_normalizer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
