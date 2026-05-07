# scripts/distortion_calibration/_fit_helpers.py
"""Shared helpers for normalization-candidate fit harness.

12-frame EXR (validation_results/disguise_next_data/) → reverse-engineered
d3 distortion formula. Each frame's filename encodes (focal_mm, K1/K2/K3,
centerShift_x_mm); we parse it once here.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import numpy as np

# Reuse archived helpers (cwd-independent). The archive scripts already use
# the same OPENCV_IO_ENABLE_OPENEXR convention.
HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "archive"
sys.path.insert(0, str(ARCHIVE))
from _exr import read_uvprobe_exr, load_probe_meta  # noqa: E402
from analyze_renders import (  # noqa: E402
    VALID_UV_MAX,
    VALID_UV_MIN,
    detect_overscan_from_anchor,
)

# ── Filename parsing ──────────────────────────────────────────────────

# Set A: disguise_focal{24,30p302,50}_K1_{zero,p0p5}.exr
# Set B: disguise_focal30p302_{K2,K3}_p0p5.exr
# Set C: disguise_focal30p302_csx_{p,n}{0p05,0p10}.exr
_FOCAL_RE = re.compile(
    r"^disguise_focal(?P<focal>\d+(?:p\d+)?)"
    r"_(?P<axis>K1|K2|K3|csx)"
    r"(?:_(?P<sign>p|n)(?P<val>\d+(?:p\d+)?)|_zero)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FrameSpec:
    path: Path
    focal_mm: float
    axis: str          # "K1", "K2", "K3", "csx"
    value: float       # 0 for zero anchor; signed for non-zero
    is_anchor: bool


def _decode_p(s: str) -> float:
    return float(s.lower().replace("p", "."))


def parse_disguise_next_filename(path: Path) -> FrameSpec:
    m = _FOCAL_RE.match(path.stem)
    if not m:
        raise ValueError(f"cannot parse disguise_next filename: {path.name}")
    focal_mm = _decode_p(m.group("focal"))
    axis = m.group("axis").upper() if m.group("axis").lower() != "csx" else "csx"
    if m.group("val") is None:
        return FrameSpec(path, focal_mm, axis, 0.0, True)
    sign = +1.0 if m.group("sign").lower() == "p" else -1.0
    value = sign * _decode_p(m.group("val"))
    return FrameSpec(path, focal_mm, axis, value, False)


# ── EXR → corrected source pixel (full-resolution arrays) ─────────────

@dataclass(frozen=True)
class CorrectedArrays:
    """Full-resolution source-pixel arrays + valid mask. No sampling."""
    R_corr: np.ndarray             # (H, W) float64
    G_corr: np.ndarray             # (H, W) float64
    source_x_px: np.ndarray        # (H, W) float64, = R_corr * width
    source_y_px: np.ndarray        # (H, W) float64, = G_corr * height
    valid: np.ndarray              # (H, W) bool — VALID_UV_MIN < R < VALID_UV_MAX & same for G
    overscan_factor: float
    overscan_margin: float


def load_corrected_arrays(
    spec: FrameSpec,
    *,
    width: int,
    height: int,
    anchor_overscan: tuple[float, float] | None = None,
) -> CorrectedArrays:
    """Read EXR, undo over-scan affine, return full-res arrays + mask.

    If `anchor_overscan` is provided, use it (frames in a focal group share
    one anchor's affine — guarantees delta-residual cancels common floor).
    Otherwise, detect from this frame.
    """
    R, G = read_uvprobe_exr(spec.path)
    if R.shape != (height, width):
        raise ValueError(f"{spec.path.name}: shape {R.shape} != {(height, width)}")
    if anchor_overscan is None:
        of, om = detect_overscan_from_anchor(R, G)
    else:
        of, om = anchor_overscan
    span = 1.0 - 2.0 * om
    R_corr = ((R.astype(np.float64) - om) / span)
    G_corr = ((G.astype(np.float64) - om) / span)
    valid = (
        (R > VALID_UV_MIN) & (R < VALID_UV_MAX) &
        (G > VALID_UV_MIN) & (G < VALID_UV_MAX)
    )
    source_x_px = R_corr * float(width)
    source_y_px = G_corr * float(height)
    return CorrectedArrays(
        R_corr=R_corr,
        G_corr=G_corr,
        source_x_px=source_x_px,
        source_y_px=source_y_px,
        valid=valid,
        overscan_factor=float(of),
        overscan_margin=float(om),
    )


@dataclass(frozen=True)
class JointSamples:
    """Sampled pixel positions where BOTH anchor and frame are valid."""
    output_x_px: np.ndarray        # (N,) = xs + 0.5
    output_y_px: np.ndarray        # (N,) = ys + 0.5
    anchor_source_x_px: np.ndarray # (N,)
    anchor_source_y_px: np.ndarray # (N,)
    frame_source_x_px: np.ndarray  # (N,)
    frame_source_y_px: np.ndarray  # (N,)


def joint_sample(
    anchor: CorrectedArrays,
    frame: CorrectedArrays,
    *,
    rng: np.random.Generator,
    samples: int,
) -> JointSamples:
    """One rng.choice; both anchor and frame indexed at SAME (ys, xs)."""
    if anchor.valid.shape != frame.valid.shape:
        raise ValueError(
            f"shape mismatch: anchor {anchor.valid.shape} vs frame {frame.valid.shape}"
        )
    joint_valid = anchor.valid & frame.valid
    valid_idx = np.flatnonzero(joint_valid.ravel())
    if valid_idx.size == 0:
        raise RuntimeError("no joint-valid pixels")
    n = min(samples, int(valid_idx.size))
    sample = rng.choice(valid_idx, size=n, replace=False)
    H, W = anchor.valid.shape
    ys, xs = np.unravel_index(sample, (H, W))
    out_x = xs.astype(np.float64) + 0.5
    out_y = ys.astype(np.float64) + 0.5
    return JointSamples(
        output_x_px=out_x,
        output_y_px=out_y,
        anchor_source_x_px=anchor.source_x_px[ys, xs],
        anchor_source_y_px=anchor.source_y_px[ys, xs],
        frame_source_x_px=frame.source_x_px[ys, xs],
        frame_source_y_px=frame.source_y_px[ys, xs],
    )


# ── Candidate normalization factors ───────────────────────────────────

def candidate_norm_factor(
    candidate: str,
    *,
    width_px: int,
    height_px: int,
    focal_mm: float,
    sensor_width_mm: float,
) -> float:
    """Return per-pixel normalization denominator (in pixels).

    Forward Brown-Conrady is `(src - c)/N = (out - c)/N · (1 + K · ((out-c)/N)²)`.
    The N cancels in `src - c = (out - c) · (1 + K · ((out-c)/N)²)`, so
    different candidates only differ in the K_eff value they imply.
    """
    if candidate == "full-width":
        return float(width_px)
    if candidate == "half-width":
        return float(width_px) / 2.0
    if candidate == "height":
        return float(height_px)
    if candidate == "diagonal":
        return float(np.hypot(width_px, height_px))
    if candidate == "focal-length":
        # Pinhole: fx_pixels = (focal_mm / sensor_width_mm) · width_px.
        return (focal_mm / sensor_width_mm) * float(width_px)
    raise ValueError(f"unknown candidate: {candidate!r}")


CANDIDATES: tuple[str, ...] = (
    "full-width",
    "focal-length",
    "diagonal",
    "height",
    "half-width",
)


# ── Forward Brown-Conrady predictor (pixel-space) ─────────────────────

def forward_brown_conrady_pixel(
    out_x_px: np.ndarray,
    out_y_px: np.ndarray,
    *,
    cx_px: float,
    cy_px: float,
    norm_px: float,
    k1: float,
    k2: float,
    k3: float,
) -> tuple[np.ndarray, np.ndarray]:
    dx = out_x_px - cx_px
    dy = out_y_px - cy_px
    rx = dx / norm_px
    ry = dy / norm_px
    r2 = rx * rx + ry * ry
    factor = k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
    src_x = out_x_px + factor * dx
    src_y = out_y_px + factor * dy
    return src_x, src_y


# ── Stats ─────────────────────────────────────────────────────────────

def format_stats(values_px: np.ndarray) -> dict:
    if values_px.size == 0:
        return {"n": 0, "median_px": float("nan"), "p95_px": float("nan"),
                "rms_px": float("nan"), "max_px": float("nan")}
    return {
        "n": int(values_px.size),
        "median_px": float(np.percentile(values_px, 50)),
        "p95_px": float(np.percentile(values_px, 95)),
        "rms_px": float(np.sqrt(np.mean(values_px * values_px))),
        "max_px": float(np.max(values_px)),
    }


# Module re-exports for unittest discovery
__all__ = [
    "CANDIDATES",
    "CorrectedArrays",
    "FrameSpec",
    "JointSamples",
    "VALID_UV_MAX",
    "VALID_UV_MIN",
    "candidate_norm_factor",
    "format_stats",
    "forward_brown_conrady_pixel",
    "joint_sample",
    "load_corrected_arrays",
    "load_probe_meta",
    "parse_disguise_next_filename",
]
