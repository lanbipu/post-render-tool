"""Validate analyze_renders.py end-to-end with synthetic distortion.

Synthesize three Disguise-style distorted UV-probe EXRs by remapping the
identity probe through the forward map r' = r*(1+K*r^2) for K in
{-0.3, 0.0, +0.3}. Drop them as EXRs into a tmp dir, run analyze_renders,
and verify recovered dr matches the closed-form prediction K * r_anchor^3
within ACCEPTANCE_PX (covers cv2.remap LANCZOS4 + EXR float precision).
"""
from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from _exr import HERE, PROBE_EXR  # noqa: E402  (sets OPENCV_IO_ENABLE_OPENEXR)
import cv2

K_TESTS = [(-0.3, "n0p3"), (0.0, "zero"), (0.3, "p0p3")]

# Newton converges quadratically for r·(1+K·r²) on |K|≤0.5; 8 iters bring
# residuals well under the NEWTON_RESIDUAL_TOL acceptance gate.
NEWTON_ITERS = 8
NEWTON_RESIDUAL_TOL = 1e-3
OUT_OF_DOMAIN_SENTINEL = -1e6  # remap with BORDER_CONSTANT returns 0 on this

ACCEPTANCE_PX = 0.5
TRIM_KEEP = 0.95


def synthesize_distortion(src: np.ndarray, K: float, half_width: float) -> np.ndarray:
    """Apply forward distortion r' = r·(1+K·r²) via cv2.remap (backward warp).

    For K<0 (barrel) f peaks at r = 1/sqrt(-3K) and has no inverse beyond.
    Output pixels in that no-inverse region get routed off-image so
    cv2.remap returns the configured borderValue (zeros).
    """
    H, W = src.shape[:2]
    cx, cy = W / 2.0, H / 2.0
    yy, xx = np.indices((H, W), dtype=np.float64)
    xx -= cx
    yy -= cy
    r_out = np.hypot(xx, yy) / half_width

    if K < -1e-9:
        r_peak = 1.0 / np.sqrt(-3.0 * K)
        f_max = r_peak * (1.0 + K * r_peak * r_peak)
        domain = r_out < (f_max - NEWTON_RESIDUAL_TOL)
    else:
        domain = np.ones_like(r_out, dtype=bool)

    r_in = r_out.copy()
    for _ in range(NEWTON_ITERS):
        f = r_in * (1.0 + K * r_in * r_in) - r_out
        fp = 1.0 + 3.0 * K * r_in * r_in
        r_in = r_in - f / np.where(np.abs(fp) > 1e-6, fp, 1e-6)
        r_in = np.clip(r_in, 0.0, 2.0)

    residual = np.abs(r_in * (1.0 + K * r_in * r_in) - r_out)
    valid = domain & (residual < NEWTON_RESIDUAL_TOL)
    safe = r_out > 1e-9
    scale = np.where(valid & safe, r_in / np.where(safe, r_out, 1.0), 1.0)
    src_x = np.where(valid, xx * scale + cx, OUT_OF_DOMAIN_SENTINEL).astype(np.float32)
    src_y = np.where(valid, yy * scale + cy, OUT_OF_DOMAIN_SENTINEL).astype(np.float32)
    return cv2.remap(
        src, src_x, src_y, cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(0.0, 0.0, 0.0),
    )


def main() -> None:
    src = cv2.imread(str(PROBE_EXR), cv2.IMREAD_UNCHANGED)
    if src is None or src.dtype != np.float32:
        raise SystemExit("run generate_uv_probe.py first")
    H, W = src.shape[:2]
    half_width = W / 2.0

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for K, tag in K_TESTS:
            dst = synthesize_distortion(src, K, half_width)
            out_exr = tmp_path / f"disguise_K_{tag}.exr"
            if not cv2.imwrite(str(out_exr), dst):
                raise RuntimeError(f"failed to write synthetic K={K} EXR to {out_exr}")

        out_csv = tmp_path / "displacements.csv"
        result = subprocess.run(
            [
                sys.executable,
                str(HERE / "analyze_renders.py"),
                "--input-dir", str(tmp_path),
                "--output", str(out_csv),
            ],
            check=True, capture_output=True, text=True,
        )
        print(result.stdout)
        if result.stderr.strip():
            relevant = "\n".join(
                line for line in result.stderr.splitlines()
                if line and "compileWithCache" not in line
                and "opencv-python" not in line
                and "OpenCV(4.13" not in line
                and "WARN" not in line
                and "Assertion" not in line
            )
            if relevant:
                print("[stderr]", relevant, file=sys.stderr)

        rows: list[dict[str, float | int]] = []
        with open(out_csv) as f:
            for row in csv.DictReader(f):
                rows.append({
                    k: float(v) if k != "pixel_id" else int(float(v))
                    for k, v in row.items()
                })

        for K, _ in K_TESTS:
            if abs(K) < 1e-9:
                continue
            samples = [r for r in rows if abs(r["K"] - K) < 1e-9]
            if not samples:
                raise SystemExit(f"missing K={K} in output")
            dr_meas = np.array([r["dr"] for r in samples])
            r_anchor = np.array([r["r_anchor"] for r in samples])
            dr_pred = K * r_anchor ** 3
            err_px = np.abs(dr_meas - dr_pred) * half_width
            n = len(samples)
            median = float(np.median(err_px))
            sorted_err = np.sort(err_px)
            trimmed = sorted_err[: int(n * TRIM_KEEP)]
            trimmed_rms = float(np.sqrt(np.mean(trimmed ** 2)))
            print(f"K={K:+.2f}: n={n}  median={median:.3f} px  "
                  f"trimmed_rms_{int(TRIM_KEEP * 100)}={trimmed_rms:.3f} px  "
                  f"max={float(err_px.max()):.3f} px")
            assert median < ACCEPTANCE_PX, f"K={K}: median {median:.3f} px exceeds tolerance"
            assert trimmed_rms < ACCEPTANCE_PX, f"K={K}: trimmed RMS {trimmed_rms:.3f} px exceeds tolerance"

    print("self-test PASS")


if __name__ == "__main__":
    main()
