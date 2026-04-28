"""Detect ChArUco chess corners in Disguise transmission frames, match each
corner across frames by its stable charuco ID, emit per-corner displacement
records to displacements.csv.

Why ChArUco (vs plain chess board): each chess corner is identified by ID
from the surrounding ArUco markers. Three direct gains over plain chess:
  1. Partial detection — outer ring clipping at high pincushion K leaves
     mid/inner ring data intact (plain chess fails the whole frame).
  2. No topology guessing — corner k in frame A and corner k in frame B are
     the same physical corner. canonicalize_grid sort-by-y bin tricks gone.
  3. Robust to non-radial distortion (P1/P2 tangential) — IDs decouple
     from spatial layout.

Custom precision tweak: after CharucoDetector returns corners, we re-run
cornerSubPix with winSize=(11,11) (vs detector's smaller default) for
0.02-0.03 px precision instead of 0.05-0.10 px.

Conventions:
  - Pixel coordinates: OpenCV pixel-center origin (pixel (0,0) = top-left CENTER).
  - r normalized by image half-width (W/2). r=1 at horizontal image edge.
  - dr = r_dist - r_anchor (positive = pushed outward / barrel-like in source).

File naming (place renders under --input-dir):
  disguise_K_zero.png              K = 0.0 (mandatory anchor)
  disguise_K_p0p1.png              K = +0.1     ('p'=positive, second 'p'=decimal point)
  disguise_K_n0p3.png              K = -0.3     ('n'=negative)

Usage (after delivery):
  ./.venv/bin/python analyze_renders.py \\
      --input-dir /tmp/disguise_renders \\
      --output displacements.csv
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
TRUTH_NPZ = HERE / "charuco_truth.npz"

# cornerSubPix tuning — winSize=(11,11) gives a 23x23 patch which lands
# strictly inside the 16-px white margin around each chess corner (no
# overlap with marker pattern), so gradient noise from the marker doesn't
# bias the saddle-point fit.
SUBPIX_WIN = (11, 11)
SUBPIX_ZERO_ZONE = (-1, -1)
SUBPIX_CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-5)


def load_truth() -> tuple[cv2.aruco.CharucoBoard, np.ndarray, tuple[int, int]]:
    truth = np.load(TRUTH_NPZ)
    cols, rows = (int(v) for v in truth["board_squares"])
    square_px = int(truth["square_px"])
    marker_px = int(truth["marker_px"])
    dict_id = int(truth["dictionary_id"])
    dictionary = cv2.aruco.getPredefinedDictionary(dict_id)
    board = cv2.aruco.CharucoBoard(
        size=(cols, rows),
        squareLength=float(square_px),
        markerLength=float(marker_px),
        dictionary=dictionary,
    )
    image_size = tuple(int(v) for v in truth["image_size"])
    return board, truth["corners_px"], image_size


def detect_corners(
    image_path: Path,
    detector: cv2.aruco.CharucoDetector,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Returns (charuco_ids, refined_corners) or None if detection fails.

    Pipeline:
      1. CharucoDetector.detectBoard finds markers, decodes IDs, locates
         chess corners between markers (already subpixel via internal logic).
      2. Custom cornerSubPix(winSize=(11,11)) tightens saddle-point fit.
    """
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"cannot read image: {image_path}")
    charuco_corners, charuco_ids, _, _ = detector.detectBoard(img)
    if charuco_corners is None or len(charuco_corners) == 0:
        return None
    refined = cv2.cornerSubPix(
        img,
        charuco_corners.astype(np.float32),
        SUBPIX_WIN,
        SUBPIX_ZERO_ZONE,
        SUBPIX_CRITERIA,
    ).reshape(-1, 2).astype(np.float64)
    return charuco_ids.flatten().astype(np.int32), refined


_K_PATTERN = re.compile(
    r"^disguise_K_(?:(zero)|([pn])(\d+(?:p\d+)?))$", re.IGNORECASE,
)


def parse_k_value(stem: str) -> float:
    m = _K_PATTERN.match(stem)
    if not m:
        raise ValueError(f"cannot parse K from filename stem: {stem}")
    if m.group(1):
        return 0.0
    sign = +1.0 if m.group(2).lower() == "p" else -1.0
    return sign * float(m.group(3).replace("p", "."))


def discover_anchor(input_dir: Path) -> Path:
    candidates = list(input_dir.glob("disguise_K_zero*.png"))
    if not candidates:
        raise SystemExit(
            f"no anchor render found under {input_dir} "
            f"(expected disguise_K_zero.png)"
        )
    if len(candidates) > 1:
        print(f"warning: multiple anchor renders found, using {candidates[0]}")
    return candidates[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input-dir", type=Path, default=Path("/tmp/disguise_renders"),
        help="directory of disguise_K_*.png renders",
    )
    ap.add_argument(
        "--output", type=Path, default=HERE / "displacements.csv",
        help="output CSV path",
    )
    args = ap.parse_args()

    if not args.input_dir.is_dir():
        raise SystemExit(f"input dir not found: {args.input_dir}")

    board, truth_corners, image_size = load_truth()
    # checkMarkers=False bypasses the marker quadrilateral integrity check
    # which falsely rejects markers warped by heavy barrel distortion (K<0
    # squashes markers near the image periphery). DICT_5X5_250 has strong
    # Hamming distance so misidentification risk is low even without it.
    # minMarkers=1 lets corners be interpolated from a single neighboring
    # marker (vs default 2), recovering the outer-most corners.
    cparams = cv2.aruco.CharucoParameters()
    cparams.checkMarkers = False
    cparams.minMarkers = 1
    cparams.tryRefineMarkers = True
    detector = cv2.aruco.CharucoDetector(board, cparams)
    W, H = image_size
    cx, cy = W / 2.0, H / 2.0
    half_width = W / 2.0
    n_total = truth_corners.shape[0]

    # 1. Anchor (K=0): sets the reference position for each corner ID.
    #    These positions, not truth_corners, are used as r_anchor —
    #    captures any subpixel shift the rendering pipeline introduces
    #    even at K=0 (camera/projection geometry).
    anchor_path = discover_anchor(args.input_dir)
    anchor_result = detect_corners(anchor_path, detector)
    if anchor_result is None:
        raise SystemExit(f"anchor detection failed on {anchor_path}")
    anchor_ids, anchor_corners = anchor_result
    anchor_map: dict[int, np.ndarray] = {
        int(i): c for i, c in zip(anchor_ids, anchor_corners)
    }

    # Anchor sanity vs static truth (sub-px expected on a flat-LED 1:1 setup;
    # any large RMS here flags a camera/projection mismatch worth investigating
    # before trusting downstream fits).
    truth_in_anchor = truth_corners[anchor_ids]
    anchor_err = anchor_corners - truth_in_anchor
    anchor_rms = float(np.sqrt(np.mean(np.sum(anchor_err ** 2, axis=1))))
    print(f"anchor: {anchor_path.name} — {len(anchor_corners)}/{n_total} corners")
    print(f"anchor rms vs static truth: {anchor_rms:.3f} px")

    # 2. For every render, detect, look up by ID, emit displacement rows.
    rows: list[dict[str, float]] = []
    seen_K: list[float] = []
    for png in sorted(args.input_dir.glob("disguise_K_*.png")):
        K = parse_k_value(png.stem)
        seen_K.append(K)
        result = detect_corners(png, detector)
        if result is None:
            print(f"  [warn] {png.name}: detection failed (skipping)")
            continue
        det_ids, det_corners = result
        n_matched = 0
        n_missing_anchor = 0
        for cid, det in zip(det_ids, det_corners):
            cid_int = int(cid)
            if cid_int not in anchor_map:
                n_missing_anchor += 1
                continue
            ax, ay = anchor_map[cid_int]
            dx, dy = det
            r_a = float(np.hypot(ax - cx, ay - cy) / half_width)
            r_d = float(np.hypot(dx - cx, dy - cy) / half_width)
            rows.append({
                "K": K,
                "corner_id": cid_int,
                "ax_px": float(ax),
                "ay_px": float(ay),
                "dx_px": float(dx),
                "dy_px": float(dy),
                "r_anchor": r_a,
                "r_dist": r_d,
                "dr": r_d - r_a,
            })
            n_matched += 1
        warn = f", {n_missing_anchor} not in anchor" if n_missing_anchor else ""
        print(f"  {png.name}: K={K:+.3f}, {n_matched}/{n_total} matched{warn}")

    if not rows:
        raise SystemExit("no rows emitted — check input directory")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.output}")
    print(f"K values: {sorted(set(seen_K))}")


if __name__ == "__main__":
    main()
