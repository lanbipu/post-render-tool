"""Validate fit_distortion_models.py with synthetic ground truth.

Generate (K, r, dr) data from a known model, plus realistic noise, and
verify the fitter reports parameters within a small tolerance and the
correct model winning by RMS.
"""
from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

# Build synthetic data: M1 with alpha=1.5 (i.e., dr = 1.5 * K * r^3) plus 0.5 px noise.
ALPHA_TRUE = 1.5
K_VALUES = (-0.5, -0.3, -0.1, 0.1, 0.3, 0.5)
HALF_W = 960.0


def main() -> None:
    rng = np.random.default_rng(42)
    rows = []
    cid = 0
    # 128 corner anchor positions like the real board (r in 0.05..0.55)
    r_anchors = np.linspace(0.05, 0.55, 128)
    for K in K_VALUES:
        for i, r in enumerate(r_anchors):
            dr_true = ALPHA_TRUE * K * r ** 3
            dr_meas = dr_true + rng.normal(0, 0.5 / HALF_W)  # ~0.5 px noise
            rows.append({
                "K": K, "corner_id": cid, "ax_px": 0, "ay_px": 0,
                "dx_px": 0, "dy_px": 0,
                "r_anchor": r, "r_dist": r + dr_meas, "dr": dr_meas,
            })
            cid += 1
    # Plus K=0 anchor rows (zero contribution but fitter ignores them)
    for r in r_anchors:
        rows.append({
            "K": 0.0, "corner_id": cid, "ax_px": 0, "ay_px": 0,
            "dx_px": 0, "dy_px": 0,
            "r_anchor": r, "r_dist": r, "dr": 0.0,
        })
        cid += 1

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "displacements.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        result = subprocess.run(
            [
                str(HERE / ".venv" / "bin" / "python"),
                str(HERE / "fit_distortion_models.py"),
                "--input", str(csv_path),
            ],
            check=True, capture_output=True, text=True,
        )
        print(result.stdout)
        if result.stderr:
            print("[stderr]", result.stderr, file=sys.stderr)

        # M1 should win and recover alpha ~= 1.5
        out = result.stdout
        # BIC favors simpler models when fits are tied — M1 should win
        assert "BEST FIT (BIC): M1" in out, (
            "expected M1 to win on BIC for synthetic M1 data"
        )
        # Verify recovered alpha for M1
        for line in out.splitlines():
            s = line.lstrip()
            if s.startswith("=== M1"):
                # parse "alpha=+1.50013" out of the header
                tail = s.split("(", 1)[1].rstrip(")")
                kv = dict(p.strip().split("=") for p in tail.split(","))
                alpha = float(kv["alpha"])
                print(f"recovered alpha={alpha:+.4f}, true={ALPHA_TRUE:+.4f}")
                assert abs(alpha - ALPHA_TRUE) < 0.02, "alpha not recovered"
                break
        else:
            raise SystemExit("could not parse M1 alpha from fit output")
    print("self-test PASS")


if __name__ == "__main__":
    main()
