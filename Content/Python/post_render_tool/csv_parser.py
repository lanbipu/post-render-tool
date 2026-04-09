"""CSV Dense parser for Disguise Designer → UE pipeline.

Parses the 'dense' CSV format exported by Disguise Designer, extracts
per-frame camera data and metadata, and returns a structured result.
"""

import csv
import re
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import config


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CsvParseError(Exception):
    """Raised when the CSV cannot be parsed due to structural or field issues."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FrameData:
    """Per-frame camera data extracted from one CSV row."""
    timestamp: str
    frame_number: int
    offset_x: float
    offset_y: float
    offset_z: float
    rotation_x: float
    rotation_y: float
    rotation_z: float
    focal_length_mm: float
    sensor_width_mm: float  # paWidthMM
    aspect_ratio: float
    aperture: float
    focus_distance: float
    k1: float
    k2: float
    k3: float
    center_shift_x_mm: float
    center_shift_y_mm: float
    fov_h: float
    fov_v: Optional[float]
    resolution_x: Optional[int]
    resolution_y: Optional[int]


@dataclass
class CsvDenseResult:
    """Aggregated result of parsing a CSV Dense file."""
    file_path: str
    camera_prefix: str
    frames: List[FrameData]
    frame_count: int
    timecode_start: str
    timecode_end: str
    focal_length_range: Tuple[float, float]
    sensor_width_mm: float
    detected_fps: Optional[float]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Common broadcast/cinema frame rates for snapping
_COMMON_FPS = [23.976, 24.0, 25.0, 29.97, 30.0, 48.0, 50.0, 59.94, 60.0]


def _detect_camera_prefix(headers: List[str]) -> str:
    """Find the camera prefix by locating the 'camera:xxx.offset.x' column."""
    pattern = re.compile(r"^(camera:\w+)\.offset\.x$")
    for h in headers:
        m = pattern.match(h)
        if m:
            return m.group(1)
    raise CsvParseError(
        "Cannot detect camera prefix: no column matching 'camera:<name>.offset.x' found."
    )


def _validate_required_fields(headers: List[str], prefix: str) -> None:
    """Raise CsvParseError if any REQUIRED_SUFFIXES column is absent."""
    missing = []
    for suffix in config.REQUIRED_SUFFIXES:
        col = f"{prefix}.{suffix}"
        if col not in headers:
            missing.append(suffix)
    if missing:
        raise CsvParseError(
            f"Missing required column(s) for prefix '{prefix}': {', '.join(missing)}"
        )


def _parse_timestamp_seconds(ts: str) -> float:
    """Convert 'HH:MM:SS.ff' timecode to fractional seconds.

    The '.ff' part is treated as hundredths of a second (centiseconds),
    matching Disguise Designer's export convention.
    """
    try:
        hms, centiseconds = ts.split(".")
        h, m, s = hms.split(":")
        total = int(h) * 3600 + int(m) * 60 + int(s) + int(centiseconds) / 100.0
        return total
    except (ValueError, AttributeError) as exc:
        raise CsvParseError(f"Cannot parse timestamp '{ts}': {exc}") from exc


def _detect_fps(timestamps: List[float]) -> Optional[float]:
    """Estimate frame rate from a sequence of timestamp floats.

    Algorithm:
    1. Compute consecutive deltas.
    2. Discard zero deltas (duplicate timestamps).
    3. If no non-zero deltas remain → return None.
    4. Check consistency: std/mean < 10 %.
    5. Snap to nearest common FPS value (within 5 %).
    """
    if len(timestamps) < 2:
        return None

    deltas = [
        timestamps[i + 1] - timestamps[i]
        for i in range(len(timestamps) - 1)
    ]
    nonzero = [d for d in deltas if d > 0]

    if not nonzero:
        return None

    mean_delta = statistics.mean(nonzero)

    if len(nonzero) > 1:
        stdev = statistics.stdev(nonzero)
        if stdev / mean_delta >= 0.10:
            # Timestamps too irregular to call a stable FPS
            return None

    raw_fps = 1.0 / mean_delta

    # Snap to nearest common FPS within 5 %
    best = None
    best_diff = float("inf")
    for common in _COMMON_FPS:
        diff = abs(raw_fps - common)
        rel = diff / common
        if rel < 0.05 and diff < best_diff:
            best = common
            best_diff = diff

    if best is not None:
        return best

    # No snap found — return raw estimate
    return raw_fps


def _get_float(row: dict, key: str) -> float:
    return float(row[key])


def _get_opt_float(row: dict, key: str) -> Optional[float]:
    val = row.get(key)
    if val is None or val == "":
        return None
    return float(val)


def _get_opt_int(row: dict, key: str) -> Optional[int]:
    val = row.get(key)
    if val is None or val == "":
        return None
    return int(float(val))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_csv_dense(file_path: str) -> CsvDenseResult:
    """Parse a Disguise Designer CSV Dense export file.

    Parameters
    ----------
    file_path:
        Absolute or relative path to the .csv file.

    Returns
    -------
    CsvDenseResult
        Populated result dataclass.

    Raises
    ------
    CsvParseError
        On structural problems (missing columns, empty file, bad format).
    """
    with open(file_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)

        headers = reader.fieldnames
        if not headers:
            raise CsvParseError(f"File is empty or has no headers: {file_path}")

        headers = list(headers)

        # --- Detect prefix and validate required columns ---
        prefix = _detect_camera_prefix(headers)
        _validate_required_fields(headers, prefix)

        # --- Column shortcuts ---
        def col(suffix: str) -> str:
            return f"{prefix}.{suffix}"

        # --- Parse rows ---
        frames: List[FrameData] = []
        timestamps_sec: List[float] = []

        for row in reader:
            ts = row["timestamp"]
            timestamps_sec.append(_parse_timestamp_seconds(ts))

            fd = FrameData(
                timestamp=ts,
                frame_number=int(float(row["frame"])),
                offset_x=_get_float(row, col("offset.x")),
                offset_y=_get_float(row, col("offset.y")),
                offset_z=_get_float(row, col("offset.z")),
                rotation_x=_get_float(row, col("rotation.x")),
                rotation_y=_get_float(row, col("rotation.y")),
                rotation_z=_get_float(row, col("rotation.z")),
                focal_length_mm=_get_float(row, col("focalLengthMM")),
                sensor_width_mm=_get_float(row, col("paWidthMM")),
                aspect_ratio=_get_float(row, col("aspectRatio")),
                aperture=_get_float(row, col("aperture")),
                focus_distance=_get_float(row, col("focusDistance")),
                k1=_get_float(row, col("k1k2k3.x")),
                k2=_get_float(row, col("k1k2k3.y")),
                k3=_get_float(row, col("k1k2k3.z")),
                center_shift_x_mm=_get_float(row, col("centerShiftMM.x")),
                center_shift_y_mm=_get_float(row, col("centerShiftMM.y")),
                fov_h=_get_float(row, col("fieldOfViewH")),
                fov_v=_get_opt_float(row, col("fieldOfViewV")),
                resolution_x=_get_opt_int(row, col("resolution.x")),
                resolution_y=_get_opt_int(row, col("resolution.y")),
            )
            frames.append(fd)

    if not frames:
        raise CsvParseError(f"No data rows found in file: {file_path}")

    focal_lengths = [f.focal_length_mm for f in frames]
    sensor_widths = [f.sensor_width_mm for f in frames]

    return CsvDenseResult(
        file_path=file_path,
        camera_prefix=prefix,
        frames=frames,
        frame_count=len(frames),
        timecode_start=frames[0].timestamp,
        timecode_end=frames[-1].timestamp,
        focal_length_range=(min(focal_lengths), max(focal_lengths)),
        sensor_width_mm=sensor_widths[0],
        detected_fps=_detect_fps(timestamps_sec),
    )
