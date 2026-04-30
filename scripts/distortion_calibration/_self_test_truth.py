"""Sanity-check the UV-probe EXR matches its identity-grid truth.

Loads uv_probe_1920x1080.exr and verifies R, G, B channels match
R = (x + 0.5)/W, G = (y + 0.5)/H, B = 0 to within EXR float-precision
(~1e-6). Failure means the probe is corrupted and downstream
analyze_renders / fit_distortion_models output is invalid.
"""
from __future__ import annotations

import numpy as np

from _exr import (
    PROBE_EXR, build_identity_uv_grid, load_probe_meta, read_uvprobe_exr,
)

IDENTITY_TOL = 1e-5


W, H, _, _ = load_probe_meta()
R, G = read_uvprobe_exr(PROBE_EXR)
u_truth, v_truth = build_identity_uv_grid(W, H)

err_R = float(np.abs(R - u_truth).max())
err_G = float(np.abs(G - v_truth).max())

# B channel: load directly since read_uvprobe_exr only returns R/G
import cv2
img = cv2.imread(str(PROBE_EXR), cv2.IMREAD_UNCHANGED)
err_B = float(np.abs(img[..., 0]).max())

print(f"probe: {PROBE_EXR}")
print(f"R (U) max err:  {err_R:.2e}  ({err_R * W:.4f} px)")
print(f"G (V) max err:  {err_G:.2e}  ({err_G * H:.4f} px)")
print(f"B max abs:      {err_B:.2e}")

assert err_R < IDENTITY_TOL, f"R channel deviates from identity ({err_R})"
assert err_G < IDENTITY_TOL, f"G channel deviates from identity ({err_G})"
assert err_B < IDENTITY_TOL, f"B channel not zero ({err_B})"
print("self-test PASS")
