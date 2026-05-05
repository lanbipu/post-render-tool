"""Gate 1.5 offline identity round-trip check.

Runs a cv2.remap identity warp that corresponds to K=0 and DistortionWeight=0.
The expected result is byte-for-byte identical to the input image. Any non-zero
diff means the local remap harness itself is not a valid baseline for later
shader-equivalent tests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


DEFAULT_INPUT = Path("/Volumes/Docs/temp/LS_shot_1_take_15_dense.0000.jpeg")
DEFAULT_OUTPUT = Path("/Volumes/Docs/temp/k_sweep/gate1_5_identity_roundtrip.json")


def build_identity_maps(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Return cv2.remap maps for exact identity sampling."""
    xs = np.arange(width, dtype=np.float32)
    ys = np.arange(height, dtype=np.float32)
    map_x, map_y = np.meshgrid(xs, ys)
    return map_x, map_y


def run_check(input_path: Path) -> dict[str, object]:
    img = cv2.imread(str(input_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"cannot read input image: {input_path}")
    if img.ndim not in (2, 3):
        raise RuntimeError(f"unsupported image shape: {img.shape}")

    height, width = img.shape[:2]
    map_x, map_y = build_identity_maps(width, height)
    warped = cv2.remap(
        img,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    diff = cv2.absdiff(img, warped)
    max_diff = int(diff.max())
    changed_pixels = int(np.count_nonzero(diff))
    total_values = int(diff.size)
    return {
        "gate": "Gate 1.5",
        "input": str(input_path),
        "shape": list(img.shape),
        "dtype": str(img.dtype),
        "interpolation": "cv2.INTER_LINEAR",
        "border_mode": "cv2.BORDER_CONSTANT",
        "distortion": {"K1": 0.0, "K2": 0.0, "K3": 0.0, "DistortionWeight": 0.0},
        "max_abs_diff": max_diff,
        "changed_values": changed_pixels,
        "total_values": total_values,
        "changed_value_ratio": changed_pixels / total_values,
        "verdict": "PASS" if max_diff == 0 and changed_pixels == 0 else "FAIL",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result = run_check(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["verdict"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
