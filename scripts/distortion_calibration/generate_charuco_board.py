"""Generate the calibration ChArUco board PNG + ground-truth corner archive.

ChArUco vs plain chessboard: each white square contains a unique ArUco
marker (5x5 binary matrix from DICT_5X5_250). cv2.aruco.CharucoDetector
identifies each chess corner by ID from the surrounding markers — no
topology guessing, partial-frame detection works, full-frame coverage
without the 'all-or-nothing' detection failure that plain chess hits
under heavy distortion.

Outputs (next to the script):
  - charuco_1920x1080.png        the render-target image
  - charuco_truth.npz            board specs + ID-indexed inner-corner positions

Layout (locked, optimized for sub-0.05 px corner precision):
  - DICT_5X5_250 ArUco dictionary
  - 24 cols x 13 rows of squares × 80 px each (= 1920 x 1040 board)
  - Marker length: 48 px (60% of square — 16 px margin around chess corners
    so cornerSubPix winSize=(11,11) patches stay clear of marker pattern)
  - Centered in 1920x1080 with 20 px vertical margins
  - 23 x 12 = 276 inner chess corners, IDs 0..275 in row-major order
  - r_max ≈ 1.025 (outermost corner just past image half-width — outer ring
    will clip at high pincushion K values, inner-mid rings always detected
    via partial-detection support).
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

W, H = 1920, 1080
COLS, ROWS = 24, 13
SQUARE_LEN_PX = 80
MARKER_LEN_PX = 48
DICTIONARY_ID = cv2.aruco.DICT_5X5_250
BOARD_W = COLS * SQUARE_LEN_PX
BOARD_H = ROWS * SQUARE_LEN_PX
MARGIN_X = (W - BOARD_W) // 2
MARGIN_Y = (H - BOARD_H) // 2
INNER_COLS = COLS - 1
INNER_ROWS = ROWS - 1
N_INNER = INNER_COLS * INNER_ROWS


def make_board() -> cv2.aruco.CharucoBoard:
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARY_ID)
    return cv2.aruco.CharucoBoard(
        size=(COLS, ROWS),
        squareLength=float(SQUARE_LEN_PX),
        markerLength=float(MARKER_LEN_PX),
        dictionary=dictionary,
    )


def truth_corners() -> np.ndarray:
    """ID-indexed inner-corner positions in OpenCV pixel-center coords.

    ChArUco assigns IDs row-major (top-left to bottom-right of inner corner
    grid); -0.5 lands the integer-square boundary in OpenCV pixel-center origin.
    """
    cols, rows = np.meshgrid(np.arange(INNER_COLS), np.arange(INNER_ROWS))
    xs = MARGIN_X + (cols + 1) * SQUARE_LEN_PX - 0.5
    ys = MARGIN_Y + (rows + 1) * SQUARE_LEN_PX - 0.5
    return np.stack([xs.ravel(), ys.ravel()], axis=1).astype(np.float64)


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    board = make_board()
    img = board.generateImage(outSize=(W, H), marginSize=0)
    truth = truth_corners()

    png_path = out_dir / "charuco_1920x1080.png"
    npz_path = out_dir / "charuco_truth.npz"
    cv2.imwrite(str(png_path), img)
    np.savez(
        npz_path,
        image_size=np.array([W, H], dtype=np.int32),
        board_squares=np.array([COLS, ROWS], dtype=np.int32),
        square_px=np.int32(SQUARE_LEN_PX),
        marker_px=np.int32(MARKER_LEN_PX),
        dictionary_id=np.int32(DICTIONARY_ID),
        margin_xy=np.array([MARGIN_X, MARGIN_Y], dtype=np.int32),
        inner_grid=np.array([INNER_COLS, INNER_ROWS], dtype=np.int32),
        corners_px=truth,
    )

    cx, cy = W / 2.0, H / 2.0
    rs = np.hypot(truth[:, 0] - cx, truth[:, 1] - cy) / (W / 2.0)
    print(f"image: {png_path}")
    print(f"truth: {npz_path}")
    print(f"squares: {COLS} x {ROWS} x {SQUARE_LEN_PX}px = {BOARD_W}x{BOARD_H} board")
    print(f"margins: {MARGIN_X}px horizontal, {MARGIN_Y}px vertical")
    print(f"inner corners: {INNER_COLS} x {INNER_ROWS} = {N_INNER}")
    print(f"marker: {MARKER_LEN_PX}px ({MARKER_LEN_PX / SQUARE_LEN_PX:.0%} of square)")
    print(f"r range (norm by half-width): [{rs.min():.3f}, {rs.max():.3f}]")


if __name__ == "__main__":
    main()
