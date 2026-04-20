"""CSV Dense parser for Disguise Designer → UE pipeline.

Parses the 'dense' CSV format exported by Disguise Designer, extracts
per-frame camera data and metadata, and returns a structured result.
"""

import csv
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import config


logger = logging.getLogger(__name__)


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
    if val is None or val == "":
        raise _EmptyFieldError(key)
    return float(val)


def _get_required_int(row: dict, key: str) -> int:
    val = row.get(key)
    if val is None or val == "":
        raise _EmptyFieldError(key)
    return int(float(val))


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
        # Disguise Designer 在 tracker 丢帧 / 校准未就绪时导出的 CSV 行中
        # 必填字段可能是空串。按帧跳过 + 记数，避免整条 pipeline 因一行炸掉。
        # frame_number 驱动 LevelSequence cadence，跳帧会在 sequence 里产生
        # keyframe gap，UE 会线性插值，效果等价于"丢失帧用前后插值补"。
        frames: List[FrameData] = []
        skipped = 0
        first_skip_sample: Optional[str] = None

        for row in reader:
            try:
                ts = row["timestamp"]
                fd = FrameData(
                    timestamp=ts,
                    frame_number=_get_required_int(row, "frame"),
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
            except _EmptyFieldError as exc:
                skipped += 1
                if first_skip_sample is None:
                    first_skip_sample = f"frame={row.get('frame', '?')} field={exc.key}"
                continue
            frames.append(fd)

        if skipped:
            logger.warning(
                "parse_csv_dense: skipped %d row(s) with empty required fields "
                "(first example: %s). LevelSequence will interpolate across the gap.",
                skipped, first_skip_sample,
            )

    if not frames:
        raise CsvParseError(
            f"No usable data rows found in file: {file_path} "
            f"(skipped {skipped} row(s) with empty required fields)"
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
