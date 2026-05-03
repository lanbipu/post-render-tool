"""Self-test for _validate_independence_KKK.py using synthetic additive data.

Generates 4 synthetic 4K UV-probe EXRs with a strictly polynomial distortion:
    source = output + (K1·r² + K2·r⁴ + K3·r⁶) · (output - center)
which is mathematically additive in (K1, K2, K3) per pixel. Wraps each with
the canonical 1.5× / margin=1/6 over-scan affine to mirror the Round 2.1+
Disguise pipeline. Runs _validate_independence_KKK.py end-to-end and asserts
the verdict comes back INDEPENDENT with sub-0.05 px residual (the only error
sources should be float32 EXR quantization and the 1.5× de-affine amplification
of that noise).

Failure here means the validator has a math bug — fix it before trusting the
script on real Disguise data.

Usage:
    cd scripts/distortion_calibration
    ./.venv/bin/python _self_test_independence.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
W, H = 3840, 2160
OVERSCAN_FACTOR = 1.5
OVERSCAN_MARGIN = 1.0 / 6.0

# Same K values the validator labels in its own header — keeps synth and real
# runs visually aligned in logs.
K_VALUES = {"K1": 0.00147, "K2": 0.01059, "K3": -0.09008}

# Float32 EXR quantization gives ~1e-7 R precision → ~4e-4 px at 4K. Three frames
# summed amplifies that, then the over-scan de-affine multiplies by factor=1.5.
# 0.05 px is conservative — actual measured residual is well under 0.01 px.
MAX_RESIDUAL_PX = 0.05


def synth_probe_exr(k1: float, k2: float, k3: float) -> np.ndarray:
    """Returns (H, W, 3) float32 BGR EXR with strictly additive distortion + over-scan.

    Uses Disguise's empirical top-left pixel convention (R = px/W, no +0.5),
    matching _validate_independence_KKK.compute_displacement after the
    2026-05-02 fix. Mismatching conventions injects a 1.4 px residual offset.
    """
    cx, cy = W / 2.0, H / 2.0
    half_w = W / 2.0
    xs = np.arange(W).astype(np.float64)
    ys = np.arange(H).astype(np.float64)

    out_x_norm = (xs[None, :] - cx) / half_w
    out_y_norm = (ys[:, None] - cy) / half_w
    r2 = out_x_norm ** 2 + out_y_norm ** 2

    factor = k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3

    src_x_px = xs[None, :] + factor * (xs[None, :] - cx)
    src_y_px = ys[:, None] + factor * (ys[:, None] - cy)

    R_real = src_x_px / W
    G_real = src_y_px / H

    R_obs = R_real / OVERSCAN_FACTOR + OVERSCAN_MARGIN
    G_obs = G_real / OVERSCAN_FACTOR + OVERSCAN_MARGIN

    img = np.zeros((H, W, 3), dtype=np.float32)
    img[..., 0] = 0.0
    img[..., 1] = G_obs.astype(np.float32)
    img[..., 2] = R_obs.astype(np.float32)
    return img


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="independence_self_test_") as td_str:
        td = Path(td_str)
        print(f"synth dir: {td}")

        cases = [
            ("disguise_KKK_only_K1.exr",  K_VALUES["K1"], 0.0,            0.0),
            ("disguise_KKK_only_K2.exr",  0.0,            K_VALUES["K2"], 0.0),
            ("disguise_KKK_only_K3.exr",  0.0,            0.0,            K_VALUES["K3"]),
            ("disguise_KKK_combined.exr", K_VALUES["K1"], K_VALUES["K2"], K_VALUES["K3"]),
        ]
        for fname, k1, k2, k3 in cases:
            img = synth_probe_exr(k1, k2, k3)
            cv2.imwrite(str(td / fname), img)
            print(f"  wrote {fname}: K1={k1:+.5f}, K2={k2:+.5f}, K3={k3:+.5f}")

        report_png = td / "report.png"
        report_json = td / "report.json"
        result = subprocess.run(
            [
                sys.executable, str(HERE / "_validate_independence_KKK.py"),
                "--input-dir", str(td),
                "--report", str(report_png),
                "--json", str(report_json),
                "--overscan-factor", str(OVERSCAN_FACTOR),
                "--overscan-margin", str(OVERSCAN_MARGIN),
            ],
            check=False, capture_output=True, text=True,
        )
        print()
        print("=" * 60)
        print("validator stdout:")
        print("=" * 60)
        print(result.stdout)
        if result.returncode != 0:
            print("validator stderr:")
            print(result.stderr)
            raise SystemExit(f"validator failed with exit code {result.returncode}")

        report = json.loads(report_json.read_text())
        max_diff = report["stats_px"]["max"]
        verdict_tag = report["verdict"]["tag"]

        assert verdict_tag == "INDEPENDENT", (
            f"Expected verdict INDEPENDENT, got {verdict_tag} (max={max_diff:.4f} px). "
            f"Validator is mis-classifying strictly-additive synth data."
        )
        assert max_diff < MAX_RESIDUAL_PX, (
            f"Expected max < {MAX_RESIDUAL_PX} px (synth is exactly additive), "
            f"got {max_diff:.4f} px. Validator is amplifying numerical noise."
        )
        assert report_png.exists(), f"Report PNG missing at {report_png}"

        print()
        print(f"self-test PASS — verdict={verdict_tag}, max={max_diff:.4f} px")


if __name__ == "__main__":
    main()
