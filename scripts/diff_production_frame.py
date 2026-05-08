"""Production frame diff: Disguise reference EXR vs UE MRQ EXR.

读两张 linear EXR (Disguise Sequence Shot screenshot + UE MRQ output),
算像素 diff,生成 overlay/heatmap PNG + summary.md。

Usage:
    python diff_production_frame.py \\
        --reference path/to/screen_mr_set_1_xxxxx.exr \\
        --ue-render path/to/LS_xxx.NNNN.exr \\
        --output-dir path/to/diff_output_dir \\
        --label take_6
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402


def _read_linear_exr(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit(f"failed to read EXR: {path}")
    if img.ndim == 2:
        img = img[..., None]
    if img.shape[2] == 4:
        img = img[:, :, :3]
    return img.astype(np.float32)


def _linear_to_srgb_u8(linear: np.ndarray) -> np.ndarray:
    x = np.clip(linear, 0.0, 1.0)
    out = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def _diff_metrics(ref: np.ndarray, ue: np.ndarray) -> dict[str, float]:
    diff = np.abs(ref - ue).reshape(-1)
    return {
        "rms": float(np.sqrt(np.mean(diff * diff))),
        "median": float(np.median(diff)),
        "p95": float(np.percentile(diff, 95.0)),
        "max": float(np.max(diff)),
        "mean": float(np.mean(diff)),
        "ref_mean": float(ref.mean()),
        "ue_mean": float(ue.mean()),
    }


def _save_overlay_50_50(ref_u8: np.ndarray, ue_u8: np.ndarray, dst: Path) -> None:
    blend = ((ref_u8.astype(np.uint16) + ue_u8.astype(np.uint16)) // 2).astype(np.uint8)
    cv2.imwrite(str(dst), blend)


def _save_overlay_cyan_magenta(ref_u8: np.ndarray, ue_u8: np.ndarray, dst: Path) -> None:
    ref_gray = cv2.cvtColor(ref_u8, cv2.COLOR_BGR2GRAY)
    ue_gray = cv2.cvtColor(ue_u8, cv2.COLOR_BGR2GRAY)
    out = np.zeros_like(ref_u8)
    out[..., 0] = ref_gray
    out[..., 1] = ref_gray
    out[..., 2] = ue_gray
    out[..., 1] = np.maximum(out[..., 1], ue_gray)
    cv2.imwrite(str(dst), out)


def _save_heatmap(ref: np.ndarray, ue: np.ndarray, dst: Path) -> None:
    diff = np.abs(ref - ue).mean(axis=2)
    norm = np.clip(diff / max(diff.max(), 1e-6), 0.0, 1.0)
    heat = (norm * 255).astype(np.uint8)
    color = cv2.applyColorMap(heat, cv2.COLORMAP_TURBO)
    cv2.imwrite(str(dst), color)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--ue-render", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--label", type=str, default="diff")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    ref = _read_linear_exr(args.reference)
    ue = _read_linear_exr(args.ue_render)

    if ref.shape != ue.shape:
        raise SystemExit(f"shape mismatch: ref={ref.shape} ue={ue.shape}")

    metrics = _diff_metrics(ref, ue)

    ref_u8 = _linear_to_srgb_u8(ref)
    ue_u8 = _linear_to_srgb_u8(ue)

    _save_overlay_50_50(ref_u8, ue_u8, args.output_dir / "diff_overlay_50_50.png")
    _save_overlay_cyan_magenta(ref_u8, ue_u8, args.output_dir / "diff_overlay_cyan_magenta.png")
    _save_heatmap(ref, ue, args.output_dir / "diff_heatmap.png")
    cv2.imwrite(str(args.output_dir / "ref_srgb.png"), ref_u8)
    cv2.imwrite(str(args.output_dir / "ue_srgb.png"), ue_u8)

    print(f"[{args.label}] shape={ref.shape}")
    for k, v in metrics.items():
        print(f"  {k:10s} = {v:.6f}")

    summary = (args.output_dir / "metrics.txt")
    summary.write_text(
        "\n".join(f"{k}\t{v:.8f}" for k, v in metrics.items()),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
