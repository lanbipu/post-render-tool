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

HERE = Path(__file__).resolve().parent


@dataclass
class FitModel:
    name: str
    description: str
    func: Callable[..., np.ndarray]  # signed residual, dr_pred = func(K, r, *params)
    p0: tuple[float, ...]
    param_names: tuple[str, ...]


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
)


def load_data(csv_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    K, r, dr = [], [], []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            k = float(row["K"])
            if abs(k) < 1e-9:
                continue  # K=0 anchor contributes no signal
            K.append(k)
            r.append(float(row["r_anchor"]))
            dr.append(float(row["dr"]))
    return np.array(K), np.array(r), np.array(dr)


def fit_one(model: FitModel, K: np.ndarray, r: np.ndarray, dr: np.ndarray):
    try:
        popt, _ = curve_fit(model.func, (K, r), dr, p0=model.p0, maxfev=20000)
    except (RuntimeError, ValueError) as exc:
        return None, None, None, None, str(exc)
    dr_pred = model.func((K, r), *popt)
    err = dr - dr_pred
    rms = float(np.sqrt(np.mean(err ** 2)))
    max_e = float(np.max(np.abs(err)))
    return popt, rms, max_e, err, None


def per_k_breakdown(K: np.ndarray, err: np.ndarray) -> list[tuple[float, float, float]]:
    out = []
    for k in sorted(set(K.tolist())):
        mask = np.abs(K - k) < 1e-9
        sub = err[mask]
        out.append((k, float(np.sqrt(np.mean(sub ** 2))), float(np.max(np.abs(sub)))))
    return out


def robust_filter(
    K: np.ndarray, r: np.ndarray, dr: np.ndarray, trim_pct: float = 5.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Drop the top `trim_pct` % of points by residual under a baseline M1 fit.

    Designed to remove measurement outliers (marker-decode glitches,
    cornerSubPix flailing on heavily-aliased edge markers) without
    discarding genuinely-informative high-r samples — those will have
    structurally-correct dr that lines up with the true formula and
    won't appear as residual outliers under a reasonable baseline.
    """
    if trim_pct <= 0:
        return K, r, dr, 0
    try:
        popt, _ = curve_fit(_m1, (K, r), dr, p0=(1.0,), maxfev=10000)
    except (RuntimeError, ValueError) as exc:
        print(f"[warn] robust_filter baseline fit failed ({exc}); skipping outlier trim")
        return K, r, dr, 0
    baseline = _m1((K, r), *popt)
    resid = np.abs(dr - baseline)
    cutoff = np.percentile(resid, 100.0 - trim_pct)
    keep = resid <= cutoff
    return K[keep], r[keep], dr[keep], int((~keep).sum())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=HERE / "displacements.csv")
    ap.add_argument(
        "--half-width-px", type=float, default=960.0,
        help="r-normalization constant (W/2 in pixels) for px conversion",
    )
    ap.add_argument(
        "--trim-pct", type=float, default=5.0,
        help="drop top X%% of points by M1-residual before final fits "
             "(removes marker decode glitches; default 5%%, set 0 to disable)",
    )
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"missing {args.input} — run analyze_renders.py first")

    K, r, dr = load_data(args.input)
    print(f"loaded {len(K)} samples, K values: {sorted(set(K.tolist()))}")
    print(f"r range: [{r.min():.3f}, {r.max():.3f}]  dr range: [{dr.min():+.4f}, {dr.max():+.4f}]")
    if args.trim_pct > 0:
        K, r, dr, dropped = robust_filter(K, r, dr, args.trim_pct)
        print(f"robust trim: dropped {dropped} outliers (top {args.trim_pct}% by M1 residual)")
        print(f"after trim: {len(K)} samples, r range: [{r.min():.3f}, {r.max():.3f}]")
    print()

    half_w = args.half_width_px
    N = len(K)
    results = []
    for m in MODELS:
        popt, rms, max_e, err, fail = fit_one(m, K, r, dr)
        if fail is not None:
            print(f"=== {m.name}  FAIL: {fail}")
            continue
        rms_px = rms * half_w
        max_px = max_e * half_w
        k_params = len(popt)
        # Sum of squared residuals in normalized r units
        ssr = float(np.sum(err ** 2))
        # AIC / BIC use ln(SSR/N); add tiny epsilon to avoid log(0)
        aic = N * np.log(max(ssr / N, 1e-30)) + 2 * k_params
        bic = N * np.log(max(ssr / N, 1e-30)) + k_params * np.log(N)
        params = ", ".join(
            f"{name}={val:+.5f}" for name, val in zip(m.param_names, popt)
        )
        print(f"=== {m.name}  rms={rms_px:.3f} px  max={max_px:.3f} px  "
              f"AIC={aic:.1f}  BIC={bic:.1f}  ({params})")
        print(f"    {m.description}")
        for k, rms_k, max_k in per_k_breakdown(K, err):
            print(f"    K={k:+.2f}  rms={rms_k * half_w:6.3f} px  max={max_k * half_w:6.3f} px")
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
