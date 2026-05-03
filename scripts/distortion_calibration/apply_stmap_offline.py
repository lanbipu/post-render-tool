"""Offline STMap application: warp an undistorted source image with a Disguise
UV-probe truth displacement field. Simulates what PostRenderTool would render
if it used the STMap dictionary strategy at the K value baked into the truth EXR.

Use case: A/B compare against UE Round 2.1's polynomial-fit output. Take an
undistorted grid image, run it through:
    (1) Disguise direct render at K=+0.5  → ground truth
    (2) UE Round 2.1 render at K=+0.5     → existing comparison
    (3) this script with K=+0.5 truth EXR → STMap simulation

Then visually diff (1)↔(2) vs (1)↔(3) to judge whether STMap's residual is
smaller than Round 2.1's. If yes, STMap is worth integrating into PostRenderTool.

Caveat: the output skips UE's 256×256 displacement LUT quantization (which
adds 0.5-1 px error in the actual UE shader). This output is the *upper
bound* of what STMap can deliver; real UE rendering will be slightly worse.
But it's adequate for the "is it visibly better than Round 2.1?" decision.

The truth EXR (e.g. disguise_KKK_only_K1.exr from Round 2.2) encodes:
    R[py, px] = source U at output pixel (px, py)  (after over-scan affine)
    G[py, px] = source V at output pixel (px, py)
This script de-affines over-scan, then cv2.remap's the input image so each
output pixel samples from the source UV that Disguise actually used.

Usage:
  ./.venv/bin/python apply_stmap_offline.py \\
      --displacement validation_results/k1k2k3_independence/disguise_KKK_only_K1.exr \\
      --input charuco_1920x1080.png \\
      --output /tmp/stmap_K1_p0p5_demo.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from _exr import read_uvprobe_exr

DEFAULT_OVERSCAN_FACTOR = 1.5
DEFAULT_OVERSCAN_MARGIN = 1.0 / 6.0


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--displacement", type=Path, required=True,
        help="Disguise UV-probe truth EXR baked at the K value to apply "
             "(e.g. disguise_KKK_only_K1.exr → applies K1=+0.5)",
    )
    ap.add_argument(
        "--input", type=Path, required=True,
        help="undistorted source image (any format/resolution, "
             "BGR or grayscale, 8/16/32-bit)",
    )
    ap.add_argument(
        "--output", type=Path, required=True,
        help="output path; format inferred from extension (.png / .jpg / .exr)",
    )
    ap.add_argument("--overscan-factor", type=float, default=DEFAULT_OVERSCAN_FACTOR)
    ap.add_argument("--overscan-margin", type=float, default=DEFAULT_OVERSCAN_MARGIN)
    ap.add_argument(
        "--interp", choices=("nearest", "linear", "cubic", "lanczos"),
        default="cubic",
        help="resampling kernel for cv2.remap (default: cubic)",
    )
    args = ap.parse_args()

    # Truth displacement: shape (H_disp, W_disp), float32 EXR
    R, G = read_uvprobe_exr(args.displacement)
    H_disp, W_disp = R.shape

    # Inverse over-scan affine → source UV in nominal LED space [0, 1]
    factor = args.overscan_factor
    margin = args.overscan_margin
    if factor > 1.01 or abs(margin) > 1e-6:
        usable_span = 1.0 - 2.0 * margin
        R_real = (R - margin) / usable_span
        G_real = (G - margin) / usable_span
    else:
        R_real, G_real = R, G

    # Source image (LED content before distortion)
    src = cv2.imread(str(args.input), cv2.IMREAD_UNCHANGED)
    if src is None:
        raise RuntimeError(f"cannot read input: {args.input}")
    H_src, W_src = src.shape[:2]

    print(f"Displacement: {args.displacement.name}  shape={R.shape}  dtype={R.dtype}")
    print(f"  R range: [{R.min():.4f}, {R.max():.4f}]  R_real range: [{R_real.min():.4f}, {R_real.max():.4f}]")
    print(f"  over-scan: factor={factor}, margin={margin:.4f}")
    print(f"Source image: {args.input.name}  shape={src.shape}  dtype={src.dtype}")
    print(f"Output target: {H_disp}×{W_disp}, interp={args.interp}")
    print()

    # cv2.remap maps:
    #   map_x[y, x] = source pixel x in input image (∈ [0, W_src))
    #   map_y[y, x] = source pixel y in input image (∈ [0, H_src))
    # so output[y, x] = input[map_y, map_x]
    map_x = (R_real * W_src).astype(np.float32)
    map_y = (G_real * H_src).astype(np.float32)

    # Diagnostic: range of source UV (anything outside [0, W) or [0, H) sampled
    # with BORDER_CONSTANT = 0 i.e. black). For K=+0.5 the over-scan provides
    # ~50% headroom so the displacement should keep source UVs in-range.
    in_range = ((map_x >= 0) & (map_x < W_src) & (map_y >= 0) & (map_y < H_src))
    print(f"Source UV in-range: {100 * in_range.mean():.2f}% of output pixels")
    print(f"  map_x range: [{map_x.min():.1f}, {map_x.max():.1f}]  (input W = {W_src})")
    print(f"  map_y range: [{map_y.min():.1f}, {map_y.max():.1f}]  (input H = {H_src})")

    interp_map = {
        "nearest": cv2.INTER_NEAREST,
        "linear":  cv2.INTER_LINEAR,
        "cubic":   cv2.INTER_CUBIC,
        "lanczos": cv2.INTER_LANCZOS4,
    }
    out = cv2.remap(
        src, map_x, map_y,
        interpolation=interp_map[args.interp],
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_ok = cv2.imwrite(str(args.output), out)
    if not write_ok:
        raise RuntimeError(f"cv2.imwrite failed for {args.output}")
    print(f"\nWrote: {args.output}  shape={out.shape}  dtype={out.dtype}")
    print()
    print(f"This is the STMap-strategy upper bound (no UE LUT quantization).")
    print(f"To compare: pair this output with your existing")
    print(f"  Disguise direct render at K=+0.5 (ground truth)")
    print(f"  UE Round 2.1 render at K=+0.5 (existing)")
    print(f"and visually diff. If STMap-vs-Disguise is tighter than Round2.1-vs-Disguise,")
    print(f"the STMap dictionary strategy is worth full integration.")


if __name__ == "__main__":
    main()
