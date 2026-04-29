"""Fit candidate distortion formulas to (K, r, dr) measurements.

Reads displacements.csv (produced by analyze_renders.py) and fits each
candidate model globally across all K values. For each model reports
the best-fit parameters, RMS residual, max residual, and per-K residual
breakdown so structural mismatches at specific K values are visible.

Models (forward map: undistorted r -> distorted r'):
  M1  Polynomial scaled:           r' = r * (1 + alpha * K * r^2)
  M2  Division:                    r' = r / (1 + alpha * K * r^2)
  M3  Polynomial higher-order:     r' = r * (1 + a*K*r^2 + b*K^2*r^4)
  M4  Free radial power:           r' = r + alpha * K * r^p
  M5  OpenCV-style cubic in K:     r' = r * (1 + a*K*r^2 + b*K*r^4 + c*K*r^6)

M1 with alpha=1.0 is exactly what UE uses today (after the Path-A sign
flip in commit 3468a67). Reduction in RMS over M1 is the signal that
the candidate captures Disguise's actual formula better.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from scipy.optimize import curve_fit

from _exr import load_probe_meta

HERE = Path(__file__).resolve().parent


@dataclass
class FitModel:
    name: str
    description: str
    func: Callable[..., np.ndarray]  # signed residual, dr_pred = func(K, r, *params)
    p0: tuple[float, ...]
    param_names: tuple[str, ...]
    uses_joint_K: bool = False  # True for joint K1/K2/K3 candidates


def _m1(KR: tuple[np.ndarray, np.ndarray], alpha: float) -> np.ndarray:
    K, r = KR
    return r * alpha * K * r * r


def _m2(KR: tuple[np.ndarray, np.ndarray], alpha: float) -> np.ndarray:
    K, r = KR
    denom = 1.0 + alpha * K * r * r
    return r / denom - r


def _m3(KR: tuple[np.ndarray, np.ndarray], a: float, b: float) -> np.ndarray:
    K, r = KR
    return r * (a * K * r ** 2 + b * (K * r ** 2) ** 2)


def _m4(KR: tuple[np.ndarray, np.ndarray], alpha: float, p: float) -> np.ndarray:
    K, r = KR
    return alpha * K * np.power(np.maximum(r, 1e-12), p)


def _m5(KR: tuple[np.ndarray, np.ndarray], a: float, b: float, c: float) -> np.ndarray:
    K, r = KR
    return r * K * (a * r ** 2 + b * r ** 4 + c * r ** 6)


def _m6(
    KR: tuple[np.ndarray, np.ndarray], a: float, b: float, c: float,
) -> np.ndarray:
    """M3 + K^3·r^6 term — full K-cubic radial polynomial."""
    K, r = KR
    return a * K * r ** 3 + b * K ** 2 * r ** 5 + c * K ** 3 * r ** 7


def _m7(
    KR: tuple[np.ndarray, np.ndarray], a: float, b: float,
) -> np.ndarray:
    """K-coupled rational: r' = r·(1+a·K·r²)/(1+b·K·r²) → dr = K·r³·(a-b)/(1+b·K·r²)."""
    K, r = KR
    denom = 1.0 + b * K * r ** 2
    return K * r ** 3 * (a - b) / denom


def _m8(
    KR: tuple[np.ndarray, np.ndarray], a: float, b: float, c: float,
) -> np.ndarray:
    """M3 with separate K and K^2 coefficients on r^4 term."""
    K, r = KR
    return a * K * r ** 3 + (b * K + c * K ** 2) * r ** 5


def _m9(
    KR: tuple[np.ndarray, np.ndarray],
    a: float, b: float, c: float, d: float,
) -> np.ndarray:
    """M6 + K^4·r^8 — 4-K-power radial polynomial."""
    K, r = KR
    return a * K * r ** 3 + b * K ** 2 * r ** 5 + c * K ** 3 * r ** 7 + d * K ** 4 * r ** 9


def _m10(
    KR: tuple[np.ndarray, np.ndarray],
    a: float, b: float, c: float, d: float,
) -> np.ndarray:
    """Extended rational with K^2 terms in both numerator and denominator."""
    K, r = KR
    num = 1.0 + a * K * r ** 2 + b * K ** 2 * r ** 4
    denom = 1.0 + c * K * r ** 2 + d * K ** 2 * r ** 4
    return r * (num / denom - 1.0)


def _m_rat6(
    KR: tuple[np.ndarray, np.ndarray],
    a: float, b: float, c: float, d: float, e: float, f: float,
) -> np.ndarray:
    """6-coefficient rational matching UE BrownConradyUD shader form.

    r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶) / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶)

    Direct map to UE FBrownConradyUDDistortionParameters:
        K1 = a·csv_K  K2 = b·csv_K²  K3 = c·csv_K³
        K4 = d·csv_K  K5 = e·csv_K²  K6 = f·csv_K³
    """
    K, r = KR
    r2 = r * r
    K2 = K * K
    K3 = K2 * K
    num = 1.0 + a * K * r2 + b * K2 * r2 * r2 + c * K3 * r2 * r2 * r2
    den = 1.0 + d * K * r2 + e * K2 * r2 * r2 + f * K3 * r2 * r2 * r2
    return r * (num / den - 1.0)


def _m_rat8(
    KR: tuple[np.ndarray, np.ndarray],
    a: float, b: float, c: float, d: float, e: float, f: float, g: float, h: float,
) -> np.ndarray:
    """8-coefficient rational, 4 阶 numerator + 4 阶 denominator (K1 only).

    r' = r · (1 + a·K·r² + b·K²·r⁴ + c·K³·r⁶ + g·K⁴·r⁸)
        / (1 + d·K·r² + e·K²·r⁴ + f·K³·r⁶ + h·K⁴·r⁸)

    比 M_RAT6 多两个 r⁸ 项, 在外圈 r > 0.9 处对发散控制更精确.
    BIC 应该跟 M_RAT6 接近 (Round 1 数据范围下), 但 Round 2 高密度数据可能
    显示 M_RAT8 表面下 r⁸ 项的真实贡献.
    """
    K, r = KR
    r2 = r * r; r4 = r2 * r2; r6 = r4 * r2; r8 = r4 * r4
    K2 = K * K; K3 = K2 * K; K4 = K3 * K
    num = 1.0 + a * K * r2 + b * K2 * r4 + c * K3 * r6 + g * K4 * r8
    den = 1.0 + d * K * r2 + e * K2 * r4 + f * K3 * r6 + h * K4 * r8
    return r * (num / den - 1.0)


def _m_rat_kkk_cross(
    KR: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    a1: float, a2: float, a3: float,    # numerator 单 K 系数
    b12: float, b13: float, b23: float, # numerator cross-term 系数 K1·K2 / K1·K3 / K2·K3
    d1: float, d2: float, d3: float,    # denominator 单 K 系数
) -> np.ndarray:
    """Joint K1/K2/K3 rational with cross-terms.

    r' = r · (1 + a1·K1·r² + a2·K2·r⁴ + a3·K3·r⁶
              + b12·K1·K2·r² + b13·K1·K3·r² + b23·K2·K3·r²)
        / (1 + d1·K1·r² + d2·K2·r⁴ + d3·K3·r⁶)

    9 参数 (vs M_RAT6 的 6). 显式建模 K1/K2/K3 三轴各自贡献 + 两两 cross-term.
    如果 BIC 选这个, 说明 Disguise 内部公式不是简单 OpenCV Brown-Conrady,
    而是有 K1·K2 类 cross 项耦合.
    """
    K1, K2, K3, r = KR
    r2 = r * r; r4 = r2 * r2; r6 = r4 * r2
    num = (1.0
           + a1 * K1 * r2 + a2 * K2 * r4 + a3 * K3 * r6
           + b12 * K1 * K2 * r2 + b13 * K1 * K3 * r2 + b23 * K2 * K3 * r2)
    den = 1.0 + d1 * K1 * r2 + d2 * K2 * r4 + d3 * K3 * r6
    return r * (num / den - 1.0)


def _m_bcud_full(
    KR: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    a: float, b: float, c: float, d: float, e: float, f: float,
    p1_scale: float, p2_scale: float,
) -> np.ndarray:
    """UE BrownConradyUD 8 槽完整 fit, 含 P1/P2 切向项贡献.

    Radial part 同 M_RAT6:
        r' = r · (1 + a·K1·r² + b·K1²·r⁴ + c·K1³·r⁶)
            / (1 + d·K1·r² + e·K1²·r⁴ + f·K1³·r⁶)

    切向项贡献到 dr (径向位移上的近似投影):
        dr_tangential ≈ p1_scale · K2 · r² + p2_scale · K3 · r²

    8 参数 (a-f + p1_scale + p2_scale). 假设切向贡献只在径向投影上有效项,
    本质上是 OpenCV BrownConrady 的 P1/P2 在径向距离上的小角度近似.
    """
    K1, K2, K3, r = KR
    r2 = r * r; r4 = r2 * r2; r6 = r4 * r2
    K1_sq = K1 * K1; K1_cu = K1_sq * K1
    num = 1.0 + a * K1 * r2 + b * K1_sq * r4 + c * K1_cu * r6
    den = 1.0 + d * K1 * r2 + e * K1_sq * r4 + f * K1_cu * r6
    radial = r * (num / den - 1.0)
    tangential = p1_scale * K2 * r2 + p2_scale * K3 * r2
    return radial + tangential


MODELS: tuple[FitModel, ...] = (
    FitModel(
        name="M1",
        description="r' = r * (1 + alpha * K * r^2)  (UE polynomial, single scale)",
        func=_m1, p0=(1.0,), param_names=("alpha",),
    ),
    FitModel(
        name="M2",
        description="r' = r / (1 + alpha * K * r^2)  (division model)",
        func=_m2, p0=(1.0,), param_names=("alpha",),
    ),
    FitModel(
        name="M3",
        description="r' = r * (1 + a*K*r^2 + b*K^2*r^4)  (mixed K-order)",
        func=_m3, p0=(1.0, 0.0), param_names=("a", "b"),
    ),
    FitModel(
        name="M4",
        description="r' = r + alpha * K * r^p          (free radial exponent)",
        func=_m4, p0=(1.0, 3.0), param_names=("alpha", "p"),
    ),
    FitModel(
        name="M5",
        description="r' = r * (1 + a*K*r^2 + b*K*r^4 + c*K*r^6)  (OpenCV-K1-only style)",
        func=_m5, p0=(1.0, 0.0, 0.0), param_names=("a", "b", "c"),
    ),
    FitModel(
        name="M6",
        description="r' = r * (1 + a*K*r^2 + b*K^2*r^4 + c*K^3*r^6)  (M3 + K^3 term)",
        func=_m6, p0=(-0.262, 0.195, 0.0), param_names=("a", "b", "c"),
    ),
    FitModel(
        name="M7",
        description="r' = r * (1 + a*K*r^2) / (1 + b*K*r^2)  (K-coupled rational)",
        func=_m7, p0=(-0.262, 0.0), param_names=("a", "b"),
    ),
    FitModel(
        name="M8",
        description="r' = r * (1 + a*K*r^2 + (b*K + c*K^2)*r^4)  (M3 + K*r^4 cross)",
        func=_m8, p0=(-0.262, 0.0, 0.195), param_names=("a", "b", "c"),
    ),
    FitModel(
        name="M9",
        description="r' = r * (1 + a*K*r^2 + b*K^2*r^4 + c*K^3*r^6 + d*K^4*r^8)  (M6 + K^4 term)",
        func=_m9, p0=(-0.251, 0.210, -0.193, 0.0),
        param_names=("a", "b", "c", "d"),
    ),
    FitModel(
        name="M10",
        description="r' = r * (1 + a*K*r^2 + b*K^2*r^4) / (1 + c*K*r^2 + d*K^2*r^4)  (extended rational)",
        func=_m10, p0=(0.531, 0.0, 0.784, 0.0),
        param_names=("a", "b", "c", "d"),
    ),
    FitModel(
        name="M_RAT6",
        description="r·(1+a·K·r²+b·K²·r⁴+c·K³·r⁶)/(1+d·K·r²+e·K²·r⁴+f·K³·r⁶)  (UE BrownConradyUD)",
        func=_m_rat6,
        p0=(-0.251, 0.21, -0.19, 0.0, 0.0, 0.0),
        param_names=("a", "b", "c", "d", "e", "f"),
    ),
    FitModel(
        name="M_RAT8",
        description="r·(1+a·K·r²+b·K²·r⁴+c·K³·r⁶+g·K⁴·r⁸)/(1+d·K·r²+...+h·K⁴·r⁸)",
        func=_m_rat8,
        p0=(-3.18, +7.24, +5.12, -2.93, +6.30, +7.51, 0.0, 0.0),
        param_names=("a", "b", "c", "d", "e", "f", "g", "h"),
        uses_joint_K=False,
    ),
    FitModel(
        name="M_RAT_K1K2K3_CROSS",
        description="联合 K1/K2/K3 rational + cross-terms (K1·K2 / K1·K3 / K2·K3)",
        func=_m_rat_kkk_cross,
        p0=(-3.18, -1.0, +1.0, 0.0, 0.0, 0.0, -2.93, -1.0, +1.0),
        param_names=("a1", "a2", "a3", "b12", "b13", "b23", "d1", "d2", "d3"),
        uses_joint_K=True,
    ),
    FitModel(
        name="M_BCUD_FULL",
        description="UE BrownConradyUD 8 槽 (radial M_RAT6 + P1/P2 切向 K2/K3 贡献)",
        func=_m_bcud_full,
        p0=(-3.18, +7.24, +5.12, -2.93, +6.30, +7.51, -1.0, +1.0),
        param_names=("a", "b", "c", "d", "e", "f", "p1_scale", "p2_scale"),
        uses_joint_K=True,
    ),
)


def load_data(
    csv_path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load (K1, K2, K3, r_anchor, dr) columns from displacements.csv.

    Skips rows where all three K are ~0 (anchor frames contribute no signal).
    """
    K1, K2, K3, r, dr = [], [], [], [], []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            k1 = float(row.get("K1", row.get("K", 0.0)))  # backward compat: legacy "K" column = K1
            k2 = float(row.get("K2", 0.0))
            k3 = float(row.get("K3", 0.0))
            if abs(k1) < 1e-9 and abs(k2) < 1e-9 and abs(k3) < 1e-9:
                continue
            K1.append(k1); K2.append(k2); K3.append(k3)
            r.append(float(row["r_anchor"]))
            dr.append(float(row["dr"]))
    return np.array(K1), np.array(K2), np.array(K3), np.array(r), np.array(dr)


def fit_one(model: FitModel, K1: np.ndarray, K2: np.ndarray, K3: np.ndarray,
            r: np.ndarray, dr: np.ndarray):
    """Fit a single candidate. K2, K3 only consumed by joint candidates;
    legacy K1-only candidates ignore K2/K3 via partial application."""
    try:
        if model.uses_joint_K:
            popt, _ = curve_fit(model.func, (K1, K2, K3, r), dr,
                                 p0=model.p0, maxfev=20000)
        else:
            popt, _ = curve_fit(model.func, (K1, r), dr,
                                 p0=model.p0, maxfev=20000)
    except (RuntimeError, ValueError) as exc:
        return None, None, None, None, str(exc)
    if model.uses_joint_K:
        dr_pred = model.func((K1, K2, K3, r), *popt)
    else:
        dr_pred = model.func((K1, r), *popt)
    err = dr - dr_pred
    rms = float(np.sqrt(np.mean(err ** 2)))
    max_e = float(np.max(np.abs(err)))
    return popt, rms, max_e, err, None


def per_k_breakdown(K1: np.ndarray, K2: np.ndarray, K3: np.ndarray,
                    err: np.ndarray) -> list[tuple[str, float, float, float]]:
    """Group residuals by (axis, K_value) and report RMS / max per group."""
    out = []
    for axis_name, K_arr in (("K1", K1), ("K2", K2), ("K3", K3)):
        # Find unique non-zero K values along this axis (other axes should be 0)
        unique_K = sorted(set(K_arr.tolist()))
        for k in unique_K:
            if abs(k) < 1e-9:
                continue
            mask = np.abs(K_arr - k) < 1e-9
            sub = err[mask]
            if len(sub) > 0:
                out.append((f"{axis_name}={k:+.3f}",
                            k, float(np.sqrt(np.mean(sub ** 2))),
                            float(np.max(np.abs(sub)))))
    return out


def robust_filter(
    K1: np.ndarray, K2: np.ndarray, K3: np.ndarray, r: np.ndarray, dr: np.ndarray,
    trim_pct: float = 5.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Drop the top `trim_pct` % of points by residual under a baseline M1 fit on K1.

    M1 baseline only uses K1 axis (single-radial). Joint-K outliers detection
    needs higher-order baseline; for our use case 5% trim removes obvious
    cornerSubPix-equivalent artifacts which are independent of joint behavior.
    """
    if trim_pct <= 0:
        return K1, K2, K3, r, dr, 0
    try:
        # Use only K1-driven samples for baseline (ignore K2/K3-only frames)
        K1_only_mask = (np.abs(K2) < 1e-9) & (np.abs(K3) < 1e-9) & (np.abs(K1) > 1e-9)
        if K1_only_mask.sum() < 10:
            print(f"[warn] only {int(K1_only_mask.sum())} K1-only samples; skipping outlier trim")
            return K1, K2, K3, r, dr, 0
        popt, _ = curve_fit(_m1, (K1[K1_only_mask], r[K1_only_mask]),
                              dr[K1_only_mask], p0=(1.0,), maxfev=10000)
        baseline = np.zeros_like(dr)
        baseline[K1_only_mask] = _m1((K1[K1_only_mask], r[K1_only_mask]), *popt)
        resid = np.abs(dr - baseline)
        # Only filter the K1-only subset; keep all K2/K3 samples (their outliers
        # would be filtered by their own per-axis pass, but for round 2 we
        # accept this as conservative).
        cutoff = np.percentile(resid[K1_only_mask], 100.0 - trim_pct)
        keep = ~K1_only_mask | (resid <= cutoff)
        return K1[keep], K2[keep], K3[keep], r[keep], dr[keep], int((~keep).sum())
    except (RuntimeError, ValueError) as exc:
        print(f"[warn] robust_filter baseline fit failed ({exc}); skipping outlier trim")
        return K1, K2, K3, r, dr, 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=HERE / "displacements.csv")
    ap.add_argument(
        "--half-width-px", type=float, default=None,
        help="r-normalization constant (W/2 in pixels). Auto-detect from "
             "probe metadata if omitted. 4K=1920, 1080p=960.",
    )
    ap.add_argument(
        "--probe-truth", type=Path, default=None,
        help="probe truth npz for half-width auto-detect (default 4K → 1080p)",
    )
    ap.add_argument(
        "--trim-pct", type=float, default=5.0,
        help="drop top X%% of points by M1-residual before final fits "
             "(removes marker decode glitches; default 5%%, set 0 to disable)",
    )
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"missing {args.input} — run analyze_renders.py first")

    if args.half_width_px is None:
        # Auto-detect from probe metadata (matching what analyze_renders.py used)
        W, H = load_probe_meta(args.probe_truth)
        half_w = W / 2.0
        print(f"[auto] half_width_px = {half_w:.1f} (from probe {W}x{H})")
    else:
        half_w = args.half_width_px

    K1, K2, K3, r, dr = load_data(args.input)
    print(f"loaded {len(K1)} samples")
    print(f"  K1 range: [{K1.min():+.3f}, {K1.max():+.3f}]  non-zero: {(np.abs(K1) > 1e-9).sum()}")
    print(f"  K2 range: [{K2.min():+.3f}, {K2.max():+.3f}]  non-zero: {(np.abs(K2) > 1e-9).sum()}")
    print(f"  K3 range: [{K3.min():+.3f}, {K3.max():+.3f}]  non-zero: {(np.abs(K3) > 1e-9).sum()}")
    print(f"  r range: [{r.min():.3f}, {r.max():.3f}]  dr range: [{dr.min():+.4f}, {dr.max():+.4f}]")
    if args.trim_pct > 0:
        K1, K2, K3, r, dr, dropped = robust_filter(K1, K2, K3, r, dr, args.trim_pct)
        print(f"robust trim: dropped {dropped} outliers (top {args.trim_pct}% by M1 K1-baseline residual)")
    print()

    N = len(K1)
    results = []
    for m in MODELS:
        popt, rms, max_e, err, fail = fit_one(m, K1, K2, K3, r, dr)
        if fail is not None:
            print(f"=== {m.name}  FAIL: {fail}")
            continue
        rms_px = rms * half_w
        max_px = max_e * half_w
        k_params = len(popt)
        ssr = float(np.sum(err ** 2))
        aic = N * np.log(max(ssr / N, 1e-30)) + 2 * k_params
        bic = N * np.log(max(ssr / N, 1e-30)) + k_params * np.log(N)
        params = ", ".join(f"{name}={val:+.5f}" for name, val in zip(m.param_names, popt))
        print(f"=== {m.name}  rms={rms_px:.3f} px  max={max_px:.3f} px  "
              f"AIC={aic:.1f}  BIC={bic:.1f}  ({params})")
        print(f"    {m.description}")
        for label, _, rms_k, max_k in per_k_breakdown(K1, K2, K3, err):
            print(f"    {label}  rms={rms_k * half_w:6.3f} px  max={max_k * half_w:6.3f} px")
        results.append({
            "name": m.name, "model": m, "popt": popt,
            "rms_px": rms_px, "max_px": max_px, "aic": aic, "bic": bic,
        })
        print()

    if not results:
        raise SystemExit("all candidate fits failed")

    print("--- ranking by RMS ---")
    for r_ in sorted(results, key=lambda t: t["rms_px"]):
        params = ", ".join(
            f"{n}={v:+.5f}" for n, v in zip(r_["model"].param_names, r_["popt"])
        )
        print(f"  {r_['name']}: rms={r_['rms_px']:.3f} px  max={r_['max_px']:.3f} px  ({params})")

    print()
    print("--- ranking by BIC (lower is better; penalizes extra parameters) ---")
    bic_sorted = sorted(results, key=lambda t: t["bic"])
    for r_ in bic_sorted:
        params = ", ".join(
            f"{n}={v:+.5f}" for n, v in zip(r_["model"].param_names, r_["popt"])
        )
        print(f"  {r_['name']}: BIC={r_['bic']:.1f}  rms={r_['rms_px']:.3f} px  ({params})")

    winner = bic_sorted[0]
    print()
    print(f"BEST FIT (BIC): {winner['name']}  ({winner['model'].description})")
    print(f"  parameters: {dict(zip(winner['model'].param_names, winner['popt']))}")


if __name__ == "__main__":
    main()
