"""Emit a small diagnostic for the Path A normalization contract."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANALYZE = ROOT / "scripts" / "distortion_calibration" / "analyze_renders.py"
README = ROOT / "scripts" / "distortion_calibration" / "README.md"


def main() -> None:
    analyze_text = ANALYZE.read_text(encoding="utf-8")
    readme_text = README.read_text(encoding="utf-8")
    payload = {
        "status": "PASS",
        "path_a_contract": "camera half-width",
        "path_c_contract": "sensor full-width UV",
        "analyze_renders_contains_half_w": "half_w = W_camera / 2.0" in analyze_text,
        "readme_contains_half_width": "half_width" in readme_text,
        "decision": "Do not use Path A residuals as Path C shader correctness evidence.",
    }
    if not (payload["analyze_renders_contains_half_w"] and payload["readme_contains_half_width"]):
        payload["status"] = "FAIL"
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
