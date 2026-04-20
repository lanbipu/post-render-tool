"""CSV Dense parser for Disguise Designer → UE pipeline.

Parses the 'dense' CSV format exported by Disguise Designer, extracts
per-frame camera data and metadata, and returns a structured result.
"""

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import config


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CsvParseError(Exception):
    """Raised when the CSV cannot be parsed due to structural or field issues."""


class _EmptyFieldError(ValueError):
    """Internal marker for a required field that is blank on a given row.

    parse_csv_dense catches this per-row to skip trackers-dropped frames
    rather than aborting the whole pipeline. Not part of the public API.
    """

    def __init__(self, key: str):
        super().__init__(f"Field {key!r} is empty")
        self.key = key


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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


def _get_float(row: dict, key: str) -> float:
    val = row.get(key)
    if val in (None, ""):
        raise _EmptyFieldError(key)
    return float(val)


def _get_required_int(row: dict, key: str) -> int:
    val = row.get(key)
    if val in (None, ""):
        raise _EmptyFieldError(key)
    return int(float(val))


def _get_opt_float(row: dict, key: str) -> Optional[float]:
    val = row.get(key)
    if val in (None, ""):
        return None
    return float(val)


def _get_opt_int(row: dict, key: str) -> Optional[int]:
    val = row.get(key)
    if val in (None, ""):
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
        headers = list(reader.fieldnames or [])
        if not headers:
            raise CsvParseError(f"File is empty or has no headers: {file_path}")

        prefix = _detect_camera_prefix(headers)
        _validate_required_fields(headers, prefix)
        all_rows = list(reader)

    # Precompute prefixed column names (Disguise: "<prefix>.<suffix>")
    def col(suffix: str) -> str:
        return f"{prefix}.{suffix}"

    # Per-frame dense fields: blank → skip the whole row (tracker drop frame).
    # LevelSequence interpolates across the gap from neighbour keyframes.
    STRICT_COLS = {
        "offset_x":   col("offset.x"),
        "offset_y":   col("offset.y"),
        "offset_z":   col("offset.z"),
        "rotation_x": col("rotation.x"),
        "rotation_y": col("rotation.y"),
        "rotation_z": col("rotation.z"),
    }

    # Lens / optics: Disguise emits these ONLY on rows where they change
    # (sparse change-only format). Blank → carry forward last seen value.
    # For blanks before the first populated row, seed backward from the first
    # value found anywhere in the CSV (typical: tracker warmup frames).
    CARRY_COLS = {
        "focal_length_mm":   col("focalLengthMM"),
        "sensor_width_mm":   col("paWidthMM"),
        "aspect_ratio":      col("aspectRatio"),
        "aperture":          col("aperture"),
        "focus_distance":    col("focusDistance"),
        "k1":                col("k1k2k3.x"),
        "k2":                col("k1k2k3.y"),
        "k3":                col("k1k2k3.z"),
        "center_shift_x_mm": col("centerShiftMM.x"),
        "center_shift_y_mm": col("centerShiftMM.y"),
        "fov_h":             col("fieldOfViewH"),
    }

    seeds: dict = {}
    for c in CARRY_COLS.values():
        for row in all_rows:
            v = row.get(c)
            if v not in (None, ""):
                seeds[c] = float(v)
                break

    frames: List[FrameData] = []
    skipped = 0
    first_skip_sample: Optional[str] = None
    never_seen: Counter = Counter()
    last = dict(seeds)

    col_fov_v = col("fieldOfViewV")
    col_res_x = col("resolution.x")
    col_res_y = col("resolution.y")

    for row in all_rows:
        try:
            ts = row["timestamp"]
            frame_num = _get_required_int(row, "frame")
            transform = {k: _get_float(row, c) for k, c in STRICT_COLS.items()}
        except _EmptyFieldError as exc:
            skipped += 1
            if first_skip_sample is None:
                first_skip_sample = f"frame={row.get('frame', '?')} field={exc.key}"
            continue

        optics: dict = {}
        for key, c in CARRY_COLS.items():
            v = row.get(c)
            if v not in (None, ""):
                last[c] = float(v)
                optics[key] = last[c]
            elif c in last:
                optics[key] = last[c]
            else:
                # Field was blank in every row; no seed. Fall back to 0.
                optics[key] = 0.0
                never_seen[c] += 1

        frames.append(FrameData(
            timestamp=ts,
            frame_number=frame_num,
            **transform,
            **optics,
            fov_v=_get_opt_float(row, col_fov_v),
            resolution_x=_get_opt_int(row, col_res_x),
            resolution_y=_get_opt_int(row, col_res_y),
        ))

    if skipped:
        # print → UE LogPython (Output Log). Python's logging module is not
        # wired into LogPython in UE Editor, so print is the only visible path.
        print(
            f"[csv_parser] skipped {skipped} row(s) with empty transform field "
            f"(first: {first_skip_sample}); LevelSequence interpolates across gaps."
        )

    if never_seen:
        summary = ", ".join(f"{k}={n}" for k, n in sorted(never_seen.items()))
        print(
            f"[csv_parser] lens/optics fields blank in ALL rows, defaulted to 0.0: "
            f"{summary}"
        )

    if not frames:
        raise CsvParseError(
            f"No usable data rows found in file: {file_path} "
            f"(skipped {skipped} row(s) with empty transform field)"
        )

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
    )
