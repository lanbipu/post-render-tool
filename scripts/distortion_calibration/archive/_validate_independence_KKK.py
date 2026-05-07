"""STMap 字典法前置阻塞验证 (Round 2.2): K1/K2/K3 在位移上是否"独立可加".

Reads 4 Disguise UV-probe renders:
  - disguise_KKK_only_K1.exr   (K1=0.00147,  K2=0,        K3=0)
  - disguise_KKK_only_K2.exr   (K1=0,        K2=0.01059,  K3=0)
  - disguise_KKK_only_K3.exr   (K1=0,        K2=0,        K3=-0.09008)
  - disguise_KKK_combined.exr  (K1=0.00147,  K2=0.01059,  K3=-0.09008)

For each output pixel, computes the displacement field from EXR R/G channels
(after over-scan de-affining), where displacement = source_pixel - output_pixel
in camera pixels. The independence assumption is:

    displacement(combined) ≈ displacement(only_K1)
                            + displacement(only_K2)
                            + displacement(only_K3)

Reports max / mean / RMS / p95 / p99 of the magnitude residual, plus per-radius
stats (center / mid / edge) and a 4-panel diagnostic PNG (|err|, dx err, dy err,
histogram).

Decision tree (max diff @ 4K camera):
  < 0.5 px → independence holds → 1D dictionary strategy works
              (separate K1/K2/K3 sweeps, sum at runtime, ~170 frames total)
  0.5–2 px → borderline coupling → 1D dictionary usable but capped precision
              (decide if acceptable with the user)
  > 2 px   → strong coupling → 1D additive dictionary fails; must switch
              (per-frame production-CSV rendering, or fit cross-term models)

Why this gate exists: the working hypothesis for the STMap dictionary strategy
is that one sweep per K axis is enough and the runtime adds three displacement
maps. If Disguise's internal formula is sufficiently rational (M_RAT8 won
the BIC race), cross-terms could break this — and if so, no amount of denser
sweeping rescues the additive plan. 4 frames here ≈ 1 hour of stage time
versus 200–300 frames of sweep that would be wasted if the plan is invalid.

Usage:
  cd scripts/distortion_calibration
  ./.venv/bin/python _validate_independence_KKK.py \\
      --input-dir validation_results/k1k2k3_independence
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from _exr import load_probe_meta, read_uvprobe_exr

# 4 frames expected in --input-dir, in this exact naming scheme.
EXPECTED_FRAMES = {
    "only_K1":  "disguise_KKK_only_K1.exr",
    "only_K2":  "disguise_KKK_only_K2.exr",
    "only_K3":  "disguise_KKK_only_K3.exr",
    "combined": "disguise_KKK_combined.exr",
}

# K values used at render time (m2_jj_47 production sample, captured 2026-05-01).
# Stored here only for the report header — the math is independent of them.
K_VALUES = {
    "K1": 0.00147,
    "K2": 0.01059,
    "K3": -0.09008,
}

# Round 2.1 default: Disguise lens over-scan 1.5×, margin = (1 - 1/1.5) / 2 = 1/6.
# Override with --overscan-factor / --overscan-margin if Disguise was set differently.
DEFAULT_OVERSCAN_FACTOR = 1.5
DEFAULT_OVERSCAN_MARGIN = 1.0 / 6.0

# Validity mask thresholds (matches analyze_renders.py): drops black-edge / FOV-mask
# pixels where Disguise sourced from outside the LED surface. Applied on raw R/G,
# not on de-affined R/G — the affine map preserves the [0,1] interior.
VALID_UV_MIN = 0.005
VALID_UV_MAX = 0.995

# Decision tree thresholds.
# Absolute (px @ 4K camera): only conclusive when signal is similar magnitude.
THRESHOLD_INDEPENDENT_PX = 0.5
THRESHOLD_BORDERLINE_PX = 2.0
# Ratio (residual / signal): the meaningful gauge once signal >> quant floor.
# Disguise outputs 16-bit half float internally → ~1-3 px quant floor @ 4K, which
# stays constant regardless of signal magnitude. With small K (sub-pixel signal)
# the absolute residual reads as "strong coupling" purely from quantization.
# At K=±0.5 (signal 100-400 px, SNR 50-200×) ratio is the honest read.
THRESHOLD_INDEPENDENT_RATIO = 0.05    # < 5% → coupling is at noise floor, additivity holds
THRESHOLD_BORDERLINE_RATIO = 0.15     # < 15% → mild cross-term, 1D dictionary usable with caps


def deaffinize_RG(
    R: np.ndarray, G: np.ndarray, factor: float, margin: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse the Disguise lens over-scan affine compression on R/G channels.

    Disguise's lens over-scan 1.5× compresses the rendered UV range into
    [margin, 1-margin] on the exported nominal-resolution EXR. The forward map
    is R_observed = R_real / factor + margin; this function inverts it.

    For factor ≈ 1 (no over-scan) this is a no-op.
    """
    if factor <= 1.01 and abs(margin) < 1e-6:
        return R, G
    usable_span = 1.0 - 2.0 * margin  # = 1/factor for the canonical 1.5× / 1/6 case
    return (R - margin) / usable_span, (G - margin) / usable_span


def compute_displacement(
    R_real: np.ndarray, G_real: np.ndarray, W_camera: int, H_camera: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel displacement field in camera-pixel units.

    Each output pixel (px, py) sampled from source UV (R_real, G_real). Since
    the EXR is rendered at camera resolution (over-scan is internal to Disguise
    and doesn't change the export grid), source position in pixels is
    (R_real * W_camera, G_real * H_camera).

    Disguise encodes pixel positions with the top-left convention
    (R = px/W, not (px+0.5)/W) — empirically verified 2026-05-02 from
    a K=0 anchor row where R[py, px=W/2] reads exactly 0.5 / 1.5 + 1/6 = 0.5.
    The python (px+0.5)/W convention would predict 0.50009. The 0.5 px gap
    leaks into the residual as a +1 px constant offset (×2 amplified by the
    additivity formula) and masquerades as 1.4 px of "coupling" everywhere
    if not handled. Stick with px (no +0.5).

    Returns (dx, dy) where dx, dy ∈ R^(H, W), and:
        dx[py, px] = R_real[py, px] * W_camera - px
        dy[py, px] = G_real[py, px] * H_camera - py

    For K=0 (no distortion), displacement is zero everywhere by construction.
    """
    H, W = R_real.shape
    if (H, W) != (H_camera, W_camera):
        raise ValueError(f"R shape {R_real.shape} ≠ camera {(H_camera, W_camera)}")
    xs = np.arange(W, dtype=np.float64)
    ys = np.arange(H, dtype=np.float64)
    dx = R_real * W_camera - xs[None, :]
    dy = G_real * H_camera - ys[:, None]
    return dx, dy


def load_one_frame(
    path: Path, factor: float, margin: float, camera_w: int, camera_h: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (dx, dy, valid_mask) for one EXR frame."""
    R, G = read_uvprobe_exr(path)
    if R.shape != (camera_h, camera_w):
        raise ValueError(
            f"{path.name}: shape {R.shape} ≠ camera {(camera_h, camera_w)}. "
            f"Round 2.2 expects 4K renders.",
        )
    valid = (
        (R > VALID_UV_MIN) & (R < VALID_UV_MAX) &
        (G > VALID_UV_MIN) & (G < VALID_UV_MAX)
    )
    R_real, G_real = deaffinize_RG(R, G, factor, margin)
    dx, dy = compute_displacement(R_real, G_real, camera_w, camera_h)
    return dx, dy, valid


def _verdict(max_diff_px: float, signal_max_px: float) -> tuple[str, str]:
    """Returns (tag, sentence) for the decision tree.

    Uses ratio (residual / signal) when signal is large enough, falls back to
    absolute px threshold when signal is too small to evaluate ratio. This
    handles the Disguise 16-bit half quantization floor (~1-3 px @ 4K) that
    stays constant regardless of K magnitude.
    """
    # Absolute fast-path: anything under 0.5 px is independent regardless of signal.
    if max_diff_px < THRESHOLD_INDEPENDENT_PX:
        return (
            "INDEPENDENT",
            "独立可加成立(绝对残差极小) → 走 1D 字典策略",
        )
    # Signal too small to compute meaningful ratio (signal ≈ quant floor).
    if signal_max_px < 5.0:
        return (
            "INCONCLUSIVE",
            f"信号 max ({signal_max_px:.2f} px) 量级跟量化底相当, ratio 无意义。"
            f"用 K=±0.5 量级 (信号 100+ px) 重渲再测",
        )
    # Ratio-based judgment (signal >> quant floor).
    ratio = max_diff_px / signal_max_px
    if ratio < THRESHOLD_INDEPENDENT_RATIO:
        return (
            "INDEPENDENT",
            f"独立可加成立 (residual/signal = {100*ratio:.2f}% < {100*THRESHOLD_INDEPENDENT_RATIO:.0f}%)"
            f" → 走 1D 字典策略 (K1/K2/K3 各一套字典, 运行时叠加)",
        )
    if ratio < THRESHOLD_BORDERLINE_RATIO:
        return (
            "BORDERLINE",
            f"边界耦合 (residual/signal = {100*ratio:.2f}%) → 1D 字典近似可用,"
            f" 跟用户讨论是否接受 cross-term 残差",
        )
    return (
        "STRONG_COUPLING",
        f"强耦合 (residual/signal = {100*ratio:.2f}% > {100*THRESHOLD_BORDERLINE_RATIO:.0f}%)"
        f" → 1D 字典叠加废, 必须换方案",
    )


def _format_stats(err_mag: np.ndarray) -> dict[str, float]:
    return {
        "max":    float(err_mag.max()),
        "mean":   float(err_mag.mean()),
        "rms":    float(np.sqrt(np.mean(err_mag ** 2))),
        "median": float(np.median(err_mag)),
        "p95":    float(np.percentile(err_mag, 95)),
        "p99":    float(np.percentile(err_mag, 99)),
    }


def _radius_buckets(
    err_mag: np.ndarray, r_valid: np.ndarray,
) -> list[dict[str, float | int | str]]:
    bins = [(0.0, 0.3, "center"), (0.3, 0.7, "mid"), (0.7, 1.5, "edge")]
    rows: list[dict[str, float | int | str]] = []
    for r_lo, r_hi, name in bins:
        mask = (r_valid >= r_lo) & (r_valid < r_hi)
        if mask.sum() == 0:
            continue
        e = err_mag[mask]
        rows.append({
            "name":   name,
            "r_lo":   r_lo,
            "r_hi":   r_hi,
            "n":      int(mask.sum()),
            "max":    float(e.max()),
            "mean":   float(e.mean()),
            "rms":    float(np.sqrt(np.mean(e ** 2))),
        })
    return rows


def render_report(
    err_dx: np.ndarray, err_dy: np.ndarray, err_mag: np.ndarray,
    joint_valid: np.ndarray, camera_w: int, camera_h: int,
    out_path: Path, max_diff: float, verdict_sentence: str,
) -> None:
    """4-panel diagnostic PNG: |err| heatmap, dx err, dy err, histogram."""
    err_full = np.full((camera_h, camera_w), np.nan, dtype=np.float32)
    err_full[joint_valid] = err_mag.astype(np.float32)

    err_dx_full = np.full((camera_h, camera_w), np.nan, dtype=np.float32)
    err_dx_full[joint_valid] = err_dx.astype(np.float32)
    err_dy_full = np.full((camera_h, camera_w), np.nan, dtype=np.float32)
    err_dy_full[joint_valid] = err_dy.astype(np.float32)

    # Cap colorbar at min(max, 5px) so a single outlier doesn't wash out structure.
    vmax_mag = min(max_diff, 5.0) if max_diff > 0 else 1.0
    vmax_signed = vmax_mag

    fig, axes = plt.subplots(2, 2, figsize=(14, 8))

    ax = axes[0, 0]
    im = ax.imshow(err_full, cmap="hot", vmin=0, vmax=vmax_mag)
    ax.set_title(f"|residual| (px)  max = {max_diff:.3f}")
    plt.colorbar(im, ax=ax, fraction=0.04)

    ax = axes[0, 1]
    im = ax.imshow(err_dx_full, cmap="seismic", vmin=-vmax_signed, vmax=vmax_signed)
    ax.set_title("dx residual (px)")
    plt.colorbar(im, ax=ax, fraction=0.04)

    ax = axes[1, 0]
    im = ax.imshow(err_dy_full, cmap="seismic", vmin=-vmax_signed, vmax=vmax_signed)
    ax.set_title("dy residual (px)")
    plt.colorbar(im, ax=ax, fraction=0.04)

    ax = axes[1, 1]
    ax.hist(err_mag, bins=100, color="steelblue", log=True)
    ax.axvline(THRESHOLD_INDEPENDENT_PX, color="g", linestyle="--",
               label=f"{THRESHOLD_INDEPENDENT_PX} px (abs threshold)")
    ax.axvline(THRESHOLD_BORDERLINE_PX, color="r", linestyle="--",
               label=f"{THRESHOLD_BORDERLINE_PX} px (abs threshold)")
    ax.set_xlabel("|residual| (px)")
    ax.set_ylabel("pixel count (log)")
    ax.set_title("residual magnitude histogram")
    ax.legend()

    fig.suptitle(
        f"STMap independence check — max {max_diff:.3f} px\n{verdict_sentence}",
        fontsize=13,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--input-dir", type=Path, required=True,
        help="directory containing the 4 disguise_KKK_*.exr renders",
    )
    ap.add_argument(
        "--report", type=Path, default=None,
        help="PNG output path (default: <input-dir>/independence_report.png)",
    )
    ap.add_argument(
        "--json", type=Path, default=None,
        help="JSON output path for machine-readable summary "
             "(default: <input-dir>/independence_report.json)",
    )
    ap.add_argument("--overscan-factor", type=float, default=DEFAULT_OVERSCAN_FACTOR)
    ap.add_argument("--overscan-margin", type=float, default=DEFAULT_OVERSCAN_MARGIN)
    args = ap.parse_args()

    paths: dict[str, Path] = {}
    for label, fname in EXPECTED_FRAMES.items():
        p = args.input_dir / fname
        if not p.exists():
            raise FileNotFoundError(
                f"missing required EXR for Round 2.2: {p}\n"
                f"See USER_INSTRUCTIONS.md §Round 2.2 for the rendering checklist.",
            )
        paths[label] = p

    probe_w, probe_h, camera_w, camera_h = load_probe_meta()
    print(f"Camera frame: {camera_w}×{camera_h}, probe: {probe_w}×{probe_h}")
    print(f"Over-scan: factor={args.overscan_factor}, margin={args.overscan_margin:.4f}")
    print(f"K values rendered: K1={K_VALUES['K1']}, K2={K_VALUES['K2']}, K3={K_VALUES['K3']}")
    print()

    displacements: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    valid_masks: dict[str, np.ndarray] = {}
    for label, path in paths.items():
        dx, dy, valid = load_one_frame(
            path, args.overscan_factor, args.overscan_margin, camera_w, camera_h,
        )
        displacements[label] = (dx, dy)
        valid_masks[label] = valid
        print(f"{label:<10} ({path.name})")
        print(f"  valid pixels: {valid.sum():>10}/{valid.size} ({100 * valid.mean():.2f}%)")
        if valid.any():
            print(f"  dx range:    [{dx[valid].min():+.3f}, {dx[valid].max():+.3f}] px")
            print(f"  dy range:    [{dy[valid].min():+.3f}, {dy[valid].max():+.3f}] px")
            print(f"  |disp| max:  {np.hypot(dx[valid], dy[valid]).max():.3f} px")
        print()

    joint_valid = (
        valid_masks["only_K1"] & valid_masks["only_K2"] &
        valid_masks["only_K3"] & valid_masks["combined"]
    )
    if joint_valid.sum() == 0:
        raise RuntimeError(
            "no jointly-valid pixels across all 4 frames; "
            "check over-scan settings or shape mismatch.",
        )
    print(f"jointly-valid pixels (all 4): {joint_valid.sum()} ({100 * joint_valid.mean():.2f}%)")
    print()

    pred_dx = (
        displacements["only_K1"][0] + displacements["only_K2"][0] + displacements["only_K3"][0]
    )
    pred_dy = (
        displacements["only_K1"][1] + displacements["only_K2"][1] + displacements["only_K3"][1]
    )
    actual_dx, actual_dy = displacements["combined"]

    err_dx = (actual_dx - pred_dx)[joint_valid]
    err_dy = (actual_dy - pred_dy)[joint_valid]
    err_mag = np.hypot(err_dx, err_dy)

    # Signal magnitude (combined frame |displacement|) for ratio-based verdict.
    signal_mag = np.hypot(actual_dx[joint_valid], actual_dy[joint_valid])
    signal_max = float(signal_mag.max())
    signal_mean = float(signal_mag.mean())

    stats = _format_stats(err_mag)
    ratio_max = stats["max"] / signal_max if signal_max > 0 else 0.0
    ratio_mean = stats["mean"] / signal_mean if signal_mean > 0 else 0.0

    cx, cy = camera_w / 2.0, camera_h / 2.0
    half_w = camera_w / 2.0
    xs = np.arange(camera_w, dtype=np.float64) + 0.5
    ys = np.arange(camera_h, dtype=np.float64) + 0.5
    r_grid = np.hypot(xs[None, :] - cx, ys[:, None] - cy) / half_w
    r_valid = r_grid[joint_valid]
    buckets = _radius_buckets(err_mag, r_valid)

    print("=" * 64)
    print("Independence residual statistics")
    print("=" * 64)
    print(f"  max:    {stats['max']:.4f} px")
    print(f"  mean:   {stats['mean']:.4f} px")
    print(f"  RMS:    {stats['rms']:.4f} px")
    print(f"  median: {stats['median']:.4f} px")
    print(f"  p95:    {stats['p95']:.4f} px")
    print(f"  p99:    {stats['p99']:.4f} px")
    print()
    print(f"  by radius:")
    print(f"    {'name':<8}{'range':<14}{'n':<12}{'max':<10}{'mean':<10}{'RMS':<10}")
    for b in buckets:
        rng = f"[{b['r_lo']:.1f}, {b['r_hi']:.1f})"
        print(f"    {b['name']:<8}{rng:<14}{b['n']:<12}{b['max']:<10.4f}{b['mean']:<10.4f}{b['rms']:<10.4f}")
    print()

    print(f"  signal (combined |disp|): max = {signal_max:.2f} px, mean = {signal_mean:.2f} px")
    print(f"  ratio max:  residual_max / signal_max  = {100*ratio_max:.3f}%")
    print(f"  ratio mean: residual_mean / signal_mean = {100*ratio_mean:.3f}%")
    print()

    verdict_tag, verdict_sentence = _verdict(stats["max"], signal_max)
    print("=" * 64)
    print(f"VERDICT [{verdict_tag}]: residual max = {stats['max']:.3f} px, signal max = {signal_max:.1f} px")
    print(f"  → {verdict_sentence}")
    print("=" * 64)

    report_path = args.report or args.input_dir / "independence_report.png"
    render_report(
        err_dx=err_dx, err_dy=err_dy, err_mag=err_mag,
        joint_valid=joint_valid, camera_w=camera_w, camera_h=camera_h,
        out_path=report_path, max_diff=stats["max"], verdict_sentence=verdict_sentence,
    )
    print(f"\nDiagnostic PNG: {report_path}")

    json_path = args.json or args.input_dir / "independence_report.json"
    json_path.write_text(json.dumps({
        "k_values":         K_VALUES,
        "overscan":         {"factor": args.overscan_factor, "margin": args.overscan_margin},
        "camera":           {"width": camera_w, "height": camera_h},
        "joint_valid_pct":  float(100 * joint_valid.mean()),
        "stats_px":         stats,
        "signal_px":        {"max": signal_max, "mean": signal_mean},
        "ratio":            {"max": ratio_max, "mean": ratio_mean},
        "by_radius":        buckets,
        "verdict":          {"tag": verdict_tag, "sentence": verdict_sentence},
    }, indent=2, ensure_ascii=False))
    print(f"JSON summary:   {json_path}")


if __name__ == "__main__":
    main()
