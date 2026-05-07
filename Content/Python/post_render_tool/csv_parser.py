"""CSV Dense parser for Disguise Designer → UE pipeline.

Parses the 'dense' CSV format exported by Disguise Designer, extracts
per-frame camera data and metadata, and returns a structured result.

Supports two header dialects emitted by Disguise:

- ``legacy``      : ``camera:<name>.offset.x`` / ``.rotation.x`` / ``.focalLengthMM`` ...
- ``spatialmap``  : ``spatialmap:<name>.engineCameraPos.x`` / ``.engineCameraRotation.x``
                    + ``spatialmap:<name>.activeCamera.focalLengthMM`` ...

Detection is automatic from headers; downstream code consumes the same
``FrameData`` shape regardless of source dialect.
"""

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


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
    aspect_ratio: float


# ---------------------------------------------------------------------------
# CSV dialect — maps logical field names to actual column names
# ---------------------------------------------------------------------------

# Logical names used by parser output (FrameData fields).
_REQUIRED_LOGICAL = (
    "offset_x", "offset_y", "offset_z",
    "rotation_x", "rotation_y", "rotation_z",
    "focal_length_mm", "sensor_width_mm", "aspect_ratio",
    "k1", "k2", "k3",
    "center_shift_x_mm", "center_shift_y_mm",
    "fov_h",
)

# Optional logical names: missing columns or blank rows fall back silently.
_SOFT_LOGICAL = (
    "aperture", "focus_distance",     # not present in spatialmap dialect
    "fov_v", "resolution_x", "resolution_y",
)


@dataclass(frozen=True)
class _Dialect:
    """Maps logical field names to actual CSV column names for one Disguise schema."""
    name: str
    camera_prefix: str                          # public-facing "prefix" reported in result
    columns: Dict[str, str]                     # required columns: logical → actual
    soft_columns: Dict[str, str]                # optional columns: logical → actual


def _build_legacy_dialect(prefix: str) -> _Dialect:
    """Schema: ``camera:<name>.<field>``."""
    p = prefix
    cols = {
        "offset_x":          f"{p}.offset.x",
        "offset_y":          f"{p}.offset.y",
        "offset_z":          f"{p}.offset.z",
        "rotation_x":        f"{p}.rotation.x",
        "rotation_y":        f"{p}.rotation.y",
        "rotation_z":        f"{p}.rotation.z",
        "focal_length_mm":   f"{p}.focalLengthMM",
        "sensor_width_mm":   f"{p}.paWidthMM",
        "aspect_ratio":      f"{p}.aspectRatio",
        "k1":                f"{p}.k1k2k3.x",
        "k2":                f"{p}.k1k2k3.y",
        "k3":                f"{p}.k1k2k3.z",
        "center_shift_x_mm": f"{p}.centerShiftMM.x",
        "center_shift_y_mm": f"{p}.centerShiftMM.y",
        "fov_h":             f"{p}.fieldOfViewH",
    }
    soft = {
        "aperture":          f"{p}.aperture",
        "focus_distance":    f"{p}.focusDistance",
        "fov_v":             f"{p}.fieldOfViewV",
        "resolution_x":      f"{p}.resolution.x",
        "resolution_y":      f"{p}.resolution.y",
    }
    return _Dialect(name="legacy", camera_prefix=prefix, columns=cols, soft_columns=soft)


def _build_spatialmap_dialect(base: str) -> _Dialect:
    """Schema: ``spatialmap:<name>.engineCameraPos.x`` (transform) +
    ``spatialmap:<name>.activeCamera.<field>`` (intrinsic).
    """
    cam = f"{base}.activeCamera"
    cols = {
        "offset_x":          f"{base}.engineCameraPos.x",
        "offset_y":          f"{base}.engineCameraPos.y",
        "offset_z":          f"{base}.engineCameraPos.z",
        "rotation_x":        f"{base}.engineCameraRotation.x",
        "rotation_y":        f"{base}.engineCameraRotation.y",
        "rotation_z":        f"{base}.engineCameraRotation.z",
        "focal_length_mm":   f"{cam}.focalLengthMM",
        "sensor_width_mm":   f"{cam}.paWidthMM",
        "aspect_ratio":      f"{cam}.aspectRatio",
        "k1":                f"{cam}.k1k2k3.x",
        "k2":                f"{cam}.k1k2k3.y",
        "k3":                f"{cam}.k1k2k3.z",
        "center_shift_x_mm": f"{cam}.centerShiftMM.x",
        "center_shift_y_mm": f"{cam}.centerShiftMM.y",
        "fov_h":             f"{cam}.fieldOfViewH",
    }
    soft = {
        # Spatialmap export omits aperture/focusDistance entirely; treat as soft.
        "aperture":          f"{cam}.aperture",
        "focus_distance":    f"{cam}.focusDistance",
        "fov_v":             f"{cam}.fieldOfViewV",
        "resolution_x":      f"{cam}.resolution.x",
        "resolution_y":      f"{cam}.resolution.y",
    }
    return _Dialect(name="spatialmap", camera_prefix=base, columns=cols, soft_columns=soft)


_LEGACY_PROBE = re.compile(r"^(camera:\w+)\.offset\.x$")
_SPATIALMAP_PROBE = re.compile(r"^(spatialmap:[^.]+)\.engineCameraPos\.x$")


def _detect_dialect(headers: List[str]) -> _Dialect:
    """Pick a dialect by sniffing for its anchor column in headers."""
    for h in headers:
        m = _LEGACY_PROBE.match(h)
        if m:
            return _build_legacy_dialect(m.group(1))
    for h in headers:
        m = _SPATIALMAP_PROBE.match(h)
        if m:
            return _build_spatialmap_dialect(m.group(1))
    raise CsvParseError(
        "Cannot detect CSV dialect: neither 'camera:<name>.offset.x' nor "
        "'spatialmap:<name>.engineCameraPos.x' anchor column was found."
    )


def _validate_required_fields(headers: List[str], dialect: _Dialect) -> None:
    """Raise CsvParseError if any required-logical column is absent."""
    headers_set = set(headers)
    missing = []
    for logical in _REQUIRED_LOGICAL:
        col = dialect.columns[logical]
        if col not in headers_set:
            missing.append(f"{logical} ({col})")
    if missing:
        raise CsvParseError(
            f"Missing required column(s) in '{dialect.name}' dialect for prefix "
            f"'{dialect.camera_prefix}': {', '.join(missing)}"
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


def trim_static_padding(result: "CsvDenseResult") -> "CsvDenseResult":
    """Drop leading + trailing rows whose camera pos matches frames[0] / frames[-1].

    Disguise's Shot Recorder typically starts CSV before the operator hits
    "export sequencer", so the first N rows record a frozen camera pose;
    symmetrically the recorder may keep running after the rendered sequence
    ends. These segments contribute no motion data and only inflate the
    LevelSequence with redundant static keyframes.

    Detection rule: trim only if ``frames[0].pos == frames[-1].pos`` (a
    round-trip pattern — camera ends where it started). This safely
    distinguishes Shot-Recorder-style takes (head/tail static) from
    mid-shot takes where the camera moves through and out (head ≠ tail);
    the latter are returned untouched.

    The returned segment includes one tail-static "anchor" row so the
    LevelSequence freezes on the final pose at end-of-playback.

    Returns a NEW CsvDenseResult; original is unchanged when no trim happens.
    """
    frames = result.frames
    if len(frames) < 2:
        return result

    head_pos = (frames[0].offset_x, frames[0].offset_y, frames[0].offset_z)
    tail_pos = (frames[-1].offset_x, frames[-1].offset_y, frames[-1].offset_z)

    if head_pos != tail_pos:
        # Camera ends elsewhere than it started → not a Shot-Recorder
        # round-trip pattern. No padding to trim.
        return result

    start_idx = 0
    for i in range(1, len(frames)):
        p = (frames[i].offset_x, frames[i].offset_y, frames[i].offset_z)
        if p != head_pos:
            start_idx = i
            break
    else:
        # All frames at head_pos — fully static CSV, nothing to extract.
        return result

    end_idx = len(frames) - 1
    for i in range(len(frames) - 2, -1, -1):
        p = (frames[i].offset_x, frames[i].offset_y, frames[i].offset_z)
        if p != tail_pos:
            end_idx = i + 1   # +1 keeps one anchor static frame at the tail
            break

    if start_idx == 0 and end_idx == len(frames) - 1:
        return result

    trimmed = frames[start_idx:end_idx + 1]
    if not trimmed:
        return result

    focals = [f.focal_length_mm for f in trimmed]
    return CsvDenseResult(
        file_path=result.file_path,
        camera_prefix=result.camera_prefix,
        frames=trimmed,
        frame_count=len(trimmed),
        timecode_start=trimmed[0].timestamp,
        timecode_end=trimmed[-1].timestamp,
        focal_length_range=(min(focals), max(focals)),
        sensor_width_mm=trimmed[0].sensor_width_mm,
        aspect_ratio=trimmed[0].aspect_ratio,
    )




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

        dialect = _detect_dialect(headers)
        _validate_required_fields(headers, dialect)
        all_rows = list(reader)

    # Per-frame dense fields: blank → skip the whole row (tracker drop frame).
    # LevelSequence interpolates across the gap from neighbour keyframes.
    STRICT_LOGICAL = (
        "offset_x", "offset_y", "offset_z",
        "rotation_x", "rotation_y", "rotation_z",
    )

    # Lens / optics carry-forward: Disguise emits these ONLY on rows where
    # they change. Blank → carry forward last value. For blanks before the
    # first populated row, seed backward from the first value found anywhere.
    CARRY_HARD = (    # required logical fields
        "focal_length_mm", "sensor_width_mm", "aspect_ratio",
        "k1", "k2", "k3",
        "center_shift_x_mm", "center_shift_y_mm",
        "fov_h",
    )
    CARRY_SOFT = (    # optional: missing column or all-blank → silent 0.0
        "aperture", "focus_distance",
    )
    CARRY_LOGICAL = CARRY_HARD + CARRY_SOFT

    headers_set = set(headers)

    def col_for(logical: str) -> str:
        c = dialect.columns.get(logical) or dialect.soft_columns.get(logical) or ""
        # Pretend a soft column is absent if it's not actually in the CSV
        # headers — keeps the never-seen warning targeted at real anomalies.
        return c if c in headers_set else ""

    # Seed each carry-forward column from the first non-empty row found.
    seeds: dict = {}
    for logical in CARRY_LOGICAL:
        c = col_for(logical)
        if not c:
            continue
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

    col_fov_v = dialect.soft_columns["fov_v"]
    col_res_x = dialect.soft_columns["resolution_x"]
    col_res_y = dialect.soft_columns["resolution_y"]

    for row in all_rows:
        try:
            ts = row["timestamp"]
            frame_num = _get_required_int(row, "frame")
            transform = {
                logical: _get_float(row, dialect.columns[logical])
                for logical in STRICT_LOGICAL
            }
        except _EmptyFieldError as exc:
            skipped += 1
            if first_skip_sample is None:
                first_skip_sample = f"frame={row.get('frame', '?')} field={exc.key}"
            continue

        optics: dict = {}
        for logical in CARRY_LOGICAL:
            c = col_for(logical)
            v = row.get(c) if c else None
            if v not in (None, ""):
                last[c] = float(v)
                optics[logical] = last[c]
            elif c and c in last:
                optics[logical] = last[c]
            else:
                # Column missing entirely (soft) or blank in every row → 0.0.
                # Only warn for hard logical fields; soft fields default silently.
                optics[logical] = 0.0
                if c and logical in CARRY_HARD:
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
        camera_prefix=dialect.camera_prefix,
        frames=frames,
        frame_count=len(frames),
        timecode_start=frames[0].timestamp,
        timecode_end=frames[-1].timestamp,
        focal_length_range=(min(focal_lengths), max(focal_lengths)),
        sensor_width_mm=sensor_widths[0],
        aspect_ratio=frames[0].aspect_ratio,
    )
