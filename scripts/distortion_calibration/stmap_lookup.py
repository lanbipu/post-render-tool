"""STMap dictionary lookup module: load the npz built by build_stmap_dict.py
and provide per-(K1, K2, K3) displacement field via additive 1D interpolation.

Independence (verified Round 2.2, residual/signal max 1.86%) lets us treat the
three K axes as independent and sum their contributions:

    displacement(K1, K2, K3) ≈ disp_K1(K1) + disp_K2(K2) + disp_K3(K3)

Each axis is interpolated linearly between adjacent stored K values. K values
outside the dictionary range are clamped to the boundary (production K is < 0.1
and the dictionary covers ±0.2, so clamping should never trigger in practice).

This module is intended for PostRenderTool runtime: import STMapDictionary,
load once at startup, call lookup() per frame to get the displacement field
that goes into UE LensFile data_mode=ST_MAP keyframes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


class STMapDictionary:
    """Loads the npz produced by build_stmap_dict.py and serves per-frame
    displacement fields for arbitrary (K1, K2, K3) tuples.

    Memory: keeps the three displacement arrays (3 × n × H × W × 2 float32) in
    RAM. For 49 frames @ 4K that's ~3 × 250 MB ≈ 750 MB. Acceptable on a
    workstation; if needed, swap to mmap_mode='r' on the underlying npz.
    """

    def __init__(self, npz_path: Path | str) -> None:
        npz_path = Path(npz_path)
        if not npz_path.exists():
            raise FileNotFoundError(f"STMap dictionary not found: {npz_path}")
        data = np.load(npz_path, allow_pickle=False)

        self.k1_values   = np.asarray(data["k1_values"],   dtype=np.float32)
        self.k1_displace = np.asarray(data["k1_displace"], dtype=np.float32)
        self.k2_values   = np.asarray(data["k2_values"],   dtype=np.float32)
        self.k2_displace = np.asarray(data["k2_displace"], dtype=np.float32)
        self.k3_values   = np.asarray(data["k3_values"],   dtype=np.float32)
        self.k3_displace = np.asarray(data["k3_displace"], dtype=np.float32)

        self.overscan_factor = float(data["overscan_factor"])
        self.overscan_margin = float(data["overscan_margin"])
        self.camera_w, self.camera_h = (int(x) for x in data["camera_resolution"])

        # Shape sanity
        for axis_name, vals, disps in [
            ("K1", self.k1_values, self.k1_displace),
            ("K2", self.k2_values, self.k2_displace),
            ("K3", self.k3_values, self.k3_displace),
        ]:
            if disps.shape[0] != len(vals):
                raise ValueError(
                    f"{axis_name} values/displace count mismatch: "
                    f"{len(vals)} vs {disps.shape[0]}",
                )
            if disps.shape[1:3] != (self.camera_h, self.camera_w):
                raise ValueError(
                    f"{axis_name} displace shape {disps.shape} doesn't match "
                    f"camera ({self.camera_h}, {self.camera_w})",
                )
            if not np.all(np.diff(vals) > 0):
                raise ValueError(f"{axis_name} values must be strictly sorted ascending")

    @property
    def H(self) -> int:
        return self.camera_h

    @property
    def W(self) -> int:
        return self.camera_w

    def lookup(self, k1: float, k2: float, k3: float) -> np.ndarray:
        """Returns (H, W, 2) float32 displacement field for the given K triple.

        last axis is (dx, dy) in camera pixels: source_pixel = output_pixel + (dx, dy).
        """
        d1 = self._interp_axis(self.k1_values, self.k1_displace, k1)
        d2 = self._interp_axis(self.k2_values, self.k2_displace, k2)
        d3 = self._interp_axis(self.k3_values, self.k3_displace, k3)
        return (d1 + d2 + d3).astype(np.float32)

    def lookup_axis(self, axis: int, k: float) -> np.ndarray:
        """Single-axis lookup, useful for debugging or per-axis output."""
        if axis == 1:
            return self._interp_axis(self.k1_values, self.k1_displace, k)
        if axis == 2:
            return self._interp_axis(self.k2_values, self.k2_displace, k)
        if axis == 3:
            return self._interp_axis(self.k3_values, self.k3_displace, k)
        raise ValueError(f"axis must be 1, 2, or 3; got {axis}")

    @staticmethod
    def _interp_axis(
        values: np.ndarray, displaces: np.ndarray, k: float,
    ) -> np.ndarray:
        """Linear interpolation in K. Clamps outside the dictionary K range."""
        if k <= values[0]:
            return displaces[0].astype(np.float64, copy=False)
        if k >= values[-1]:
            return displaces[-1].astype(np.float64, copy=False)
        # values[i-1] < k <= values[i]
        i = int(np.searchsorted(values, k, side="left"))
        if values[i] == k:
            return displaces[i].astype(np.float64, copy=False)
        k_lo = float(values[i - 1])
        k_hi = float(values[i])
        t = (k - k_lo) / (k_hi - k_lo)
        return ((1.0 - t) * displaces[i - 1] + t * displaces[i]).astype(np.float64)

    def __repr__(self) -> str:
        return (
            f"STMapDictionary("
            f"camera={self.camera_w}×{self.camera_h}, "
            f"K1: {len(self.k1_values)} frames in [{self.k1_values.min():+.3f}, {self.k1_values.max():+.3f}], "
            f"K2: {len(self.k2_values)} in [{self.k2_values.min():+.3f}, {self.k2_values.max():+.3f}], "
            f"K3: {len(self.k3_values)} in [{self.k3_values.min():+.3f}, {self.k3_values.max():+.3f}]"
            f")"
        )
