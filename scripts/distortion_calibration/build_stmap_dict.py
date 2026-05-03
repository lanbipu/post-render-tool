"""STMap dictionary builder: convert Round 2.3 K1/K2/K3 sweep EXRs into a single
queryable npz dictionary for STMap-mode PostRenderTool rendering.

Inputs (each axis sweep contains 49 frames with the canonical Round 2.3
stepped step sizes: dense [-0.1, +0.1] step 0.005, buffer ±0.2 step 0.025):
  --k1-dir: 49 EXR for K1 sweep (K2=K3=0 during render)
  --k2-dir: 49 EXR for K2 sweep (K1=K3=0)
  --k3-dir: 49 EXR for K3 sweep (K1=K2=0)

Each frame is processed:
  1. Read R/G channels (float32 EXR, cv2 BGR layout)
  2. De-affine over-scan affine: R_real = (R - margin) / (1 - 2 * margin)
  3. Compute source UV in pixels: (R_real * W, G_real * H)
  4. Subtract the K=0 anchor (frame disguise_K{axis}_zero.exr) on the same
     axis to get the displacement field. Anchor subtraction kills the
     Disguise pixel-convention 0.5 px constant offset that bit us in
     Round 2.2 — at K=0 the displacement is exactly zero by construction,
     independent of whether Disguise uses px or px+0.5 origin.

Output:
  stmap_dict.npz with:
    k1_values      (49,)               sorted K1 sweep values
    k1_displace    (49, H, W, 2) float32  per-K displacement fields in pixels
    k2_values, k2_displace             same for K2 axis
    k3_values, k3_displace             same for K3 axis
    overscan_factor                    1.5
    overscan_margin                    1/6
    camera_resolution                  (W, H)
    anchor_source_path                 which EXR was used as the global anchor

Runtime PostRenderTool usage: load via stmap_lookup.STMapDictionary, call
  lookup(k1, k2, k3) -> (H, W, 2) displacement field. Independence (Round 2.2,
  verified residual/signal max 1.86%) lets us sum the three axes additively
  at runtime with negligible cross-term error.

Sanity self-test: _self_test_stmap_dict.py runs synthetic strictly-additive
sweeps through this builder and asserts dictionary lookup matches the synth
ground truth within float32 precision.

Usage:
  ./.venv/bin/python build_stmap_dict.py \\
      --k1-dir validation_results/k1_sweep_round23 \\
      --k2-dir validation_results/k2_sweep \\
      --k3-dir validation_results/k3_sweep \\
      --output validation_results/stmap_dict.npz
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import numpy as np

from _exr import load_probe_meta, read_uvprobe_exr
from analyze_renders import parse_k_value

DEFAULT_OVERSCAN_FACTOR = 1.5
DEFAULT_OVERSCAN_MARGIN = 1.0 / 6.0

# K=0 frame, when sampled from any of the three axes, should produce nearly
# identical source UV (since K1=K2=K3=0 in all three cases). Cross-axis diff
# above this threshold suggests probe drift between sweeps and warrants a warning.
ANCHOR_CROSS_AXIS_TOL_PX = 0.5


def deaffinize_RG(
    R: np.ndarray, G: np.ndarray, factor: float, margin: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse the Disguise lens over-scan affine compression on R/G channels.

    For factor ≈ 1 (no over-scan) this is a no-op.
    """
    if factor <= 1.01 and abs(margin) < 1e-6:
        return R, G
    span = 1.0 - 2.0 * margin
    return (R - margin) / span, (G - margin) / span


def load_axis_sweep(
    directory: Path, axis: int,
    factor: float, margin: float,
    camera_w: int, camera_h: int,
) -> tuple[list[float], list[np.ndarray], Path]:
    """Reads all `disguise_K{axis}_*.exr` files in a directory.

    Returns (sorted_k_values, src_uv_arrays, anchor_path) where:
      - sorted_k_values: list of Python floats, sorted ascending
      - src_uv_arrays: list of (H, W, 2) float32 arrays in the same order
      - anchor_path: file path for the K=0 frame

    Returns lists (not a K-indexed dict) to avoid float32 hash key mismatches:
    sorting Python floats then iterating by index keeps the K↔array mapping
    intact without round-tripping through np.float32 keys.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"sweep dir does not exist: {directory}")
    files = sorted(directory.glob("disguise_K*_*.exr"))
    if not files:
        raise FileNotFoundError(f"no disguise_K*_*.exr in {directory}")

    pairs: list[tuple[float, np.ndarray]] = []
    anchor_path: Path | None = None

    for path in files:
        try:
            parsed_axis, k_val = parse_k_value(path.stem)
        except ValueError as e:
            print(f"  [skip] {path.name}: {e}")
            continue
        if parsed_axis != axis:
            print(f"  [skip] {path.name}: parsed axis {parsed_axis} != target axis {axis}")
            continue

        R, G = read_uvprobe_exr(path)
        if R.shape != (camera_h, camera_w):
            raise ValueError(
                f"{path.name}: shape {R.shape} != camera ({camera_h}, {camera_w})",
            )
        R_real, G_real = deaffinize_RG(R, G, factor, margin)
        src_x = (R_real * camera_w).astype(np.float32)
        src_y = (G_real * camera_h).astype(np.float32)
        pairs.append((float(k_val), np.stack([src_x, src_y], axis=-1)))
        if k_val == 0.0:
            anchor_path = path

    if anchor_path is None:
        raise RuntimeError(
            f"axis {axis} sweep dir missing K=0 anchor "
            f"(expected disguise_K{axis}_zero.exr in {directory})",
        )

    pairs.sort(key=lambda p: p[0])
    sorted_ks = [p[0] for p in pairs]
    src_arrays = [p[1] for p in pairs]
    return sorted_ks, src_arrays, anchor_path


def build_axis_displacements(
    src_arrays: list[np.ndarray], anchor: np.ndarray,
) -> np.ndarray:
    """Per-K displacement = source UV - global anchor, stacked into (n, H, W, 2)."""
    H, W = anchor.shape[:2]
    n = len(src_arrays)
    out = np.zeros((n, H, W, 2), dtype=np.float32)
    for i, src in enumerate(src_arrays):
        out[i] = (src - anchor).astype(np.float32)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--k1-dir", type=Path, required=True,
                    help="directory containing K1 sweep EXRs (K2=K3=0)")
    ap.add_argument("--k2-dir", type=Path, required=True,
                    help="directory containing K2 sweep EXRs (K1=K3=0)")
    ap.add_argument("--k3-dir", type=Path, required=True,
                    help="directory containing K3 sweep EXRs (K1=K2=0)")
    ap.add_argument("--output", type=Path, required=True,
                    help="output npz dictionary path")
    ap.add_argument("--overscan-factor", type=float, default=DEFAULT_OVERSCAN_FACTOR)
    ap.add_argument("--overscan-margin", type=float, default=DEFAULT_OVERSCAN_MARGIN)
    args = ap.parse_args()

    _, _, camera_w, camera_h = load_probe_meta()
    print(f"Camera resolution: {camera_w}×{camera_h}")
    print(f"Over-scan: factor={args.overscan_factor}, margin={args.overscan_margin:.4f}")
    print()

    print(f"Loading K1 sweep from {args.k1_dir} ...")
    k1_ks, k1_src, k1_anchor_path = load_axis_sweep(
        args.k1_dir, 1, args.overscan_factor, args.overscan_margin, camera_w, camera_h,
    )
    print(f"  {len(k1_ks)} frames, K range [{min(k1_ks):+.4f}, {max(k1_ks):+.4f}]")
    print(f"  anchor: {k1_anchor_path.name}")
    print()

    print(f"Loading K2 sweep from {args.k2_dir} ...")
    k2_ks, k2_src, k2_anchor_path = load_axis_sweep(
        args.k2_dir, 2, args.overscan_factor, args.overscan_margin, camera_w, camera_h,
    )
    print(f"  {len(k2_ks)} frames, K range [{min(k2_ks):+.4f}, {max(k2_ks):+.4f}]")
    print(f"  anchor: {k2_anchor_path.name}")
    print()

    print(f"Loading K3 sweep from {args.k3_dir} ...")
    k3_ks, k3_src, k3_anchor_path = load_axis_sweep(
        args.k3_dir, 3, args.overscan_factor, args.overscan_margin, camera_w, camera_h,
    )
    print(f"  {len(k3_ks)} frames, K range [{min(k3_ks):+.4f}, {max(k3_ks):+.4f}]")
    print(f"  anchor: {k3_anchor_path.name}")
    print()

    # K=0 anchor is at index where K==0 in each sorted list.
    k1_zero_i = k1_ks.index(0.0)
    k2_zero_i = k2_ks.index(0.0)
    k3_zero_i = k3_ks.index(0.0)
    k1_anchor = k1_src[k1_zero_i]
    k2_anchor = k2_src[k2_zero_i]
    k3_anchor = k3_src[k3_zero_i]
    diff_12 = float(np.abs(k1_anchor - k2_anchor).max())
    diff_13 = float(np.abs(k1_anchor - k3_anchor).max())
    diff_23 = float(np.abs(k2_anchor - k3_anchor).max())
    print(f"K=0 anchor cross-axis consistency check:")
    print(f"  K1 vs K2 max diff: {diff_12:.4f} px")
    print(f"  K1 vs K3 max diff: {diff_13:.4f} px")
    print(f"  K2 vs K3 max diff: {diff_23:.4f} px")
    if max(diff_12, diff_13, diff_23) > ANCHOR_CROSS_AXIS_TOL_PX:
        print(f"  [WARN] cross-axis anchor diff > {ANCHOR_CROSS_AXIS_TOL_PX} px — "
              f"Disguise probe may have drift between sweeps")
    else:
        print(f"  ✓ within {ANCHOR_CROSS_AXIS_TOL_PX} px tolerance")
    print()

    global_anchor = k1_anchor.astype(np.float32)
    print(f"Using K1 K=0 frame as global anchor for all three axes.")
    print()

    print("Building displacement arrays (source UV − anchor) ...")
    k1_displace = build_axis_displacements(k1_src, global_anchor)
    k2_displace = build_axis_displacements(k2_src, global_anchor)
    k3_displace = build_axis_displacements(k3_src, global_anchor)
    k1_values = np.array(k1_ks, dtype=np.float32)
    k2_values = np.array(k2_ks, dtype=np.float32)
    k3_values = np.array(k3_ks, dtype=np.float32)
    for name, vals, disps in [("K1", k1_values, k1_displace),
                              ("K2", k2_values, k2_displace),
                              ("K3", k3_values, k3_displace)]:
        zero_idx = int(np.argmin(np.abs(vals)))
        zero_max = float(np.abs(disps[zero_idx]).max())
        max_disp = float(np.abs(disps).max())
        print(f"  {name}: shape {disps.shape}  K=0 max |disp|={zero_max:.5f} px  "
              f"axis max |disp|={max_disp:.2f} px")
    print()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Saving dictionary to {args.output} ...")
    np.savez_compressed(
        args.output,
        k1_values         = k1_values,
        k1_displace       = k1_displace,
        k2_values         = k2_values,
        k2_displace       = k2_displace,
        k3_values         = k3_values,
        k3_displace       = k3_displace,
        overscan_factor   = np.float32(args.overscan_factor),
        overscan_margin   = np.float32(args.overscan_margin),
        camera_resolution = np.array([camera_w, camera_h], dtype=np.int32),
        anchor_source_path = str(k1_anchor_path),
    )
    raw_mb = (k1_displace.nbytes + k2_displace.nbytes + k3_displace.nbytes) / 1e6
    out_mb = args.output.stat().st_size / 1e6
    print(f"  raw size:        {raw_mb:>7.1f} MB (float32)")
    print(f"  compressed size: {out_mb:>7.1f} MB (npz zip-deflate)")
    print(f"  ratio: {100 * out_mb / raw_mb:.1f}%")
    print()
    print("Done. Use stmap_lookup.STMapDictionary to query at runtime.")


if __name__ == "__main__":
    main()
