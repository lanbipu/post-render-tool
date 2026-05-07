"""Pixel-diff a UE Path C MRQ render against the Disguise transmission frame.

Default inputs target the take_4 production diff:
  UE  : validation_results/path_c_production/path_c_production_test_take_4_dense.0000.png
  ref : validation_results/path_c_production/reference/disguise_take4_seq_frame8.png

The reference PNG was decoded from `.seq frame 8` (motion start, UE LevelSequence
frame 0 in the alignment formula k ↔ .seq (8+k) ↔ d3 (625994+k)).

Output JSON next to the UE render (production_diff.json by default).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def normalize_to_8bit(arr: np.ndarray) -> np.ndarray:
    """Reduce to 3-channel uint8 [0,1] range for cross-format comparison."""
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    if arr.shape[-1] == 4:
        arr = arr[..., :3]
    if arr.dtype == np.uint8:
        return arr.astype(np.float32) / 255.0
    if arr.dtype == np.uint16:
        return arr.astype(np.float32) / 65535.0
    return arr.astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ue",
        default="validation_results/path_c_production/path_c_production_test_take_4_dense.0000.png",
        help="UE MRQ frame 0 render PNG",
    )
    ap.add_argument(
        "--ref",
        default="validation_results/path_c_production/reference/disguise_take4_seq_frame8.png",
        help="Disguise .seq reference PNG",
    )
    ap.add_argument(
        "--out",
        default="validation_results/path_c_production/production_diff.json",
        help="Where to write the diff JSON report",
    )
    args = ap.parse_args()

    ue_arr = normalize_to_8bit(np.asarray(Image.open(args.ue)))
    ref_arr = normalize_to_8bit(np.asarray(Image.open(args.ref)))

    if ue_arr.shape != ref_arr.shape:
        print(f"ERROR: shape mismatch ue={ue_arr.shape} ref={ref_arr.shape}")
        sys.exit(1)

    diff = np.abs(ue_arr - ref_arr)
    valid = (ue_arr.max(axis=-1) > 0) & (ref_arr.max(axis=-1) > 0)
    valid_diff = diff[valid]

    report = {
        "ue":  args.ue,
        "ref": args.ref,
        "shape": list(ue_arr.shape),
        "ue_mean_rgb":  [float(ue_arr[..., c].mean()) for c in range(3)],
        "ref_mean_rgb": [float(ref_arr[..., c].mean()) for c in range(3)],
        "rms":    float(np.sqrt((diff ** 2).mean())),
        "median": float(np.median(diff)),
        "p95":    float(np.percentile(diff, 95)),
        "max":    float(diff.max()),
        "changed_ratio_gt_004": float((diff > 0.004).mean()),
        "valid_pixel_ratio": float(valid.mean()),
        "valid_rms":    float(np.sqrt((valid_diff ** 2).mean())) if valid_diff.size else None,
        "valid_p95":    float(np.percentile(valid_diff, 95)) if valid_diff.size else None,
        "valid_max":    float(valid_diff.max()) if valid_diff.size else None,
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"shape:     {report['shape']}")
    print(f"ue mean:   ({report['ue_mean_rgb'][0]:.4f}, {report['ue_mean_rgb'][1]:.4f}, {report['ue_mean_rgb'][2]:.4f})")
    print(f"ref mean:  ({report['ref_mean_rgb'][0]:.4f}, {report['ref_mean_rgb'][1]:.4f}, {report['ref_mean_rgb'][2]:.4f})")
    print(f"rms:       {report['rms']:.4f}")
    print(f"p95:       {report['p95']:.4f}")
    print(f"valid_p95: {report['valid_p95']:.4f}" if report['valid_p95'] else "valid_p95: n/a")
    print(f"max:       {report['max']:.4f}")
    print(f"diff>0.004 ratio: {report['changed_ratio_gt_004']:.4f}")
    print(f"\nreport: {args.out}")


if __name__ == "__main__":
    main()
