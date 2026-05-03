"""Self-test for build_stmap_dict.py + stmap_lookup.STMapDictionary using
synthetic strictly-additive polynomial sweeps.

Generates synthetic K1/K2/K3 sweeps where displacement is exactly:
    disp(K1, K2, K3) = (K1·r² + K2·r⁴ + K3·r⁶) · (output_pixel - center)
which is mathematically additive in the three K axes. Wraps each frame in
the canonical 1.5× / margin=1/6 over-scan affine to mirror Disguise output.

Pipeline tested:
  synth EXR (49+49+49 frames + K=0 anchor)
    → build_stmap_dict.py (read, de-affine, anchor-subtract, save npz)
    → STMapDictionary.lookup() at known K values
    → assert lookup ≈ synth ground truth within float32 noise

Failure means the builder or the dictionary lookup has a math bug — fix
before running on real Disguise data.

Usage:
    cd scripts/distortion_calibration
    ./.venv/bin/python _self_test_stmap_dict.py
"""
from __future__ import annotations

import os
import shutil
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

# Round 2.3 阶梯步长 K 值列表
DENSE_KS = np.round(np.arange(-0.100, 0.100 + 1e-9, 0.005), 4)  # 41 frames
BUFFER_KS = np.array([-0.200, -0.175, -0.150, -0.125,
                      +0.125, +0.150, +0.175, +0.200])
ALL_KS = np.unique(np.concatenate([DENSE_KS, BUFFER_KS]))  # 49 sorted values

# Synthetic distortion coefficients (strict additive polynomial). The actual
# numbers don't matter for the test, only that disp is linear in (k1, k2, k3).
# Match the m2_jj_47 production magnitudes loosely.
SYNTH_K_COEFFS = (1.0, 1.0, 1.0)

# Tolerance: synth EXR is float32, sweep × dict load × interpolation introduces
# only quantization noise. Real precision should be < 0.05 px.
MAX_RESIDUAL_PX = 0.05


def _camera_norm_radial_squared() -> np.ndarray:
    """r² per pixel (output coordinates), normalized to half-width=1 at sensor edge."""
    cx, cy = W / 2.0, H / 2.0
    half_w = W / 2.0
    xs = np.arange(W).astype(np.float64)
    ys = np.arange(H).astype(np.float64)
    out_x_norm = (xs[None, :] - cx) / half_w
    out_y_norm = (ys[:, None] - cy) / half_w
    return out_x_norm ** 2 + out_y_norm ** 2


def synth_probe_exr(k1: float, k2: float, k3: float) -> np.ndarray:
    """Returns (H, W, 3) float32 BGR EXR following Disguise output format
    with strictly additive polynomial distortion + over-scan affine.

    Uses Disguise's empirical top-left pixel convention (R = px/W).
    """
    cx = W / 2.0
    cy = H / 2.0
    xs = np.arange(W).astype(np.float64)
    ys = np.arange(H).astype(np.float64)
    r2 = _camera_norm_radial_squared()
    factor = (
        SYNTH_K_COEFFS[0] * k1 * r2 +
        SYNTH_K_COEFFS[1] * k2 * r2 ** 2 +
        SYNTH_K_COEFFS[2] * k3 * r2 ** 3
    )
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


def _filename_for_K(axis: int, k: float) -> str:
    if k == 0.0:
        return f"disguise_K{axis}_zero.exr"
    sign = "p" if k > 0 else "n"
    abs_k = abs(k)
    # Round 2.3 命名: 三位小数 + 'p' 替小数点
    s = f"{abs_k:.3f}".replace(".", "p")
    return f"disguise_K{axis}_{sign}{s}.exr"


def _write_axis_sweep(out_dir: Path, axis: int) -> int:
    """Writes 49 EXR frames for a single axis sweep into out_dir.
    Returns the count of frames written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for k in ALL_KS:
        if axis == 1:
            img = synth_probe_exr(float(k), 0.0, 0.0)
        elif axis == 2:
            img = synth_probe_exr(0.0, float(k), 0.0)
        elif axis == 3:
            img = synth_probe_exr(0.0, 0.0, float(k))
        else:
            raise ValueError(f"bad axis {axis}")
        fname = _filename_for_K(axis, float(k))
        cv2.imwrite(str(out_dir / fname), img)
        count += 1
    return count


def _expected_displacement(k1: float, k2: float, k3: float) -> np.ndarray:
    """Synth ground truth displacement for given K triple, shape (H, W, 2)."""
    cx, cy = W / 2.0, H / 2.0
    xs = np.arange(W).astype(np.float64)
    ys = np.arange(H).astype(np.float64)
    r2 = _camera_norm_radial_squared()
    factor = (
        SYNTH_K_COEFFS[0] * k1 * r2 +
        SYNTH_K_COEFFS[1] * k2 * r2 ** 2 +
        SYNTH_K_COEFFS[2] * k3 * r2 ** 3
    )
    dx = factor * (xs[None, :] - cx)
    dy = factor * (ys[:, None] - cy)
    return np.stack([dx, dy], axis=-1)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="stmap_dict_self_test_") as td_str:
        td = Path(td_str)
        print(f"synth dir: {td}")

        k1_dir = td / "k1_sweep"
        k2_dir = td / "k2_sweep"
        k3_dir = td / "k3_sweep"

        print(f"\nGenerating synthetic K1 sweep ({len(ALL_KS)} frames) ...")
        n1 = _write_axis_sweep(k1_dir, 1)
        print(f"  wrote {n1} frames")

        print(f"Generating synthetic K2 sweep ...")
        n2 = _write_axis_sweep(k2_dir, 2)
        print(f"  wrote {n2} frames")

        print(f"Generating synthetic K3 sweep ...")
        n3 = _write_axis_sweep(k3_dir, 3)
        print(f"  wrote {n3} frames")

        # Run build_stmap_dict.py
        npz_path = td / "stmap_dict.npz"
        result = subprocess.run(
            [
                sys.executable, str(HERE / "build_stmap_dict.py"),
                "--k1-dir", str(k1_dir),
                "--k2-dir", str(k2_dir),
                "--k3-dir", str(k3_dir),
                "--output", str(npz_path),
                "--overscan-factor", str(OVERSCAN_FACTOR),
                "--overscan-margin", str(OVERSCAN_MARGIN),
            ],
            check=False, capture_output=True, text=True,
            cwd=str(HERE),  # so build_stmap_dict can find _exr.py & analyze_renders.py
        )
        print()
        print("=" * 60)
        print("build_stmap_dict.py stdout:")
        print("=" * 60)
        print(result.stdout)
        if result.returncode != 0:
            print("STDERR:")
            print(result.stderr)
            raise SystemExit(f"builder failed with exit code {result.returncode}")

        # Load via STMapDictionary and run lookup tests
        from stmap_lookup import STMapDictionary
        d = STMapDictionary(npz_path)
        print(f"Loaded: {d}")
        print()

        # Test 1: K=0 lookup should give zero displacement
        disp = d.lookup(0.0, 0.0, 0.0)
        max_err = float(np.abs(disp).max())
        print(f"Test 1: lookup(0, 0, 0) max |disp| = {max_err:.5f} px  "
              f"(should be 0)")
        assert max_err < MAX_RESIDUAL_PX, f"K=0 lookup non-zero: {max_err}"

        # Test 2: lookup at exact stored K values matches expected synth disp
        test_cases = [
            (+0.005,  0.0,    0.0),
            (-0.050,  0.0,    0.0),
            ( 0.0,   +0.025,  0.0),
            ( 0.0,    0.0,   -0.100),
            (+0.020, -0.040, +0.010),  # three axes simultaneously
            (+0.080, +0.080, -0.080),
        ]
        for k1, k2, k3 in test_cases:
            disp = d.lookup(k1, k2, k3)
            expected = _expected_displacement(k1, k2, k3)
            err = np.abs(disp - expected).max()
            print(f"Test 2: lookup(K1={k1:+.3f}, K2={k2:+.3f}, K3={k3:+.3f}) "
                  f"max err = {err:.5f} px")
            assert err < MAX_RESIDUAL_PX, f"lookup err {err} exceeds {MAX_RESIDUAL_PX}"

        # Test 3: linear interpolation between stored K values
        # K=0.0025 falls between stored K=0 and K=0.005
        for k_test in [0.0025, -0.0075, 0.0123, -0.099, 0.137]:
            disp = d.lookup(k_test, 0.0, 0.0)
            expected = _expected_displacement(k_test, 0.0, 0.0)
            err = np.abs(disp - expected).max()
            print(f"Test 3: K1={k_test:+.4f} interp max err = {err:.5f} px")
            # Loosen threshold for interp (synth is polynomial in K so linear interp
            # is exact for K1 axis since K1 enters linearly)
            assert err < MAX_RESIDUAL_PX, f"interp err {err} exceeds {MAX_RESIDUAL_PX}"

        # Test 4: clamp behavior (K outside dictionary range)
        disp_clamp = d.lookup(+0.500, 0.0, 0.0)
        disp_max = d.lookup(+0.200, 0.0, 0.0)
        clamp_err = float(np.abs(disp_clamp - disp_max).max())
        print(f"Test 4: K1=+0.5 (outside range, clamped to +0.2) diff vs K1=+0.2 = {clamp_err:.5f} px")
        assert clamp_err < 1e-4, f"clamp not exact: {clamp_err}"

        print()
        print("self-test PASS")


if __name__ == "__main__":
    main()
