"""EXR header SMPTE timecode patcher.

Offline (post-render) — shells out to `oiiotool` (OpenImageIO CLI) to
write typed `smpte:TimeCode` + `FramesPerSecond` rational attributes to
EXR files matching a filename pattern.

Backend choice rationale: see `scripts/exr_timecode_spike_report.md`.
oiiotool was picked over PyPI `OpenEXR` because it preserves multipart
EXR layout, all channels, and `compression` / `pixelAspectRatio` attrs
intact while emitting typed timecode (not a string alias).

Install:
    macOS:   brew install openimageio
    Windows: scoop install openimageio    (or install OpenImageIO MSI)

Public API:
    patch_exr_timecode_in_dir(output_dir, filename_pattern,
                              start_csv_frame, start_timecode, fps)
        Walks `output_dir`, matches `filename_pattern` to extract the
        absolute CSV frame number from each filename, calculates the
        per-frame SMPTE timecode, and rewrites the EXR with that
        timecode in the header. Returns the count of patched files.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .timecode import Timecode


def _ensure_oiiotool() -> None:
    if shutil.which("oiiotool") is None:
        raise RuntimeError(
            "oiiotool not on PATH. Install OpenImageIO: "
            "macOS=`brew install openimageio`, "
            "Windows=`scoop install openimageio` (or the MSI)."
        )


def _frame_to_timecode(start: Timecode, offset_frames: int) -> Timecode:
    """Inverse of Timecode.to_frames(): given an offset in real frames
    from `start`, return the SMPTE display timecode at that offset.

    Drop-frame aware (Bevin 29.97 / 59.94 NTSC reversed).
    """
    total = start.to_frames() + offset_frames
    nominal_fps = round(start.rate_num / start.rate_den)

    if not start.drop_frame:
        ff = total % nominal_fps
        ts = total // nominal_fps
        ss = ts % 60
        mm = (ts // 60) % 60
        hh = ts // 3600
        return Timecode(
            hours=hh, minutes=mm, seconds=ss, frames=ff,
            drop_frame=False,
            rate_num=start.rate_num, rate_den=start.rate_den,
        )

    # NTSC drop-frame reverse — for each non-10-minute boundary, the
    # display "skips" `drop_count` frame labels at second :00 of that
    # minute, but the real frame counter ticks continuously. We need
    # to undo that mapping.
    drop_count = 2 if nominal_fps == 30 else 4
    frames_per_10min = nominal_fps * 600 - drop_count * 9   # 17982 (29.97) / 35964 (59.94)
    frames_per_minute_minus = nominal_fps * 60 - drop_count  # 1798 / 3596

    d = total // frames_per_10min               # full 10-min blocks
    m = total - d * frames_per_10min            # frames inside the current block

    # Block layout:
    #   minute 0:  `nominal_fps*60` frames (no drop on 10-min boundary)
    #   minutes 1..9: each `frames_per_minute_minus` frames
    if m < nominal_fps * 60:
        minute_in_block = 0
        m_in_minute = m
    else:
        m_remainder = m - nominal_fps * 60
        minute_in_block = 1 + m_remainder // frames_per_minute_minus
        m_in_minute = m_remainder % frames_per_minute_minus + drop_count

    total_minutes = d * 10 + minute_in_block
    hh = total_minutes // 60
    mm = total_minutes % 60
    ss = m_in_minute // nominal_fps
    ff = m_in_minute % nominal_fps
    return Timecode(
        hours=hh, minutes=mm, seconds=ss, frames=ff,
        drop_frame=True,
        rate_num=start.rate_num, rate_den=start.rate_den,
    )


def _filename_pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert `"render.{frame:07d}.exr"` → compiled regex with the frame
    number as group 1.
    """
    placeholder = re.compile(r"\{frame:(\d+)d\}")
    parts: list[str] = []
    last_end = 0
    for match in placeholder.finditer(pattern):
        # Literal chunk before the placeholder — re.escape to be safe.
        parts.append(re.escape(pattern[last_end:match.start()]))
        # The placeholder itself becomes a capturing group of N digits.
        parts.append(r"(\d{" + match.group(1) + r"})")
        last_end = match.end()
    parts.append(re.escape(pattern[last_end:]))
    return re.compile(f"^{''.join(parts)}$")


def patch_exr_timecode_in_dir(
    output_dir: str,
    filename_pattern: str,
    start_csv_frame: int,
    start_timecode: Timecode,
    fps: float,
) -> int:
    """Add SMPTE typed `timeCode` + rational `FramesPerSecond` to every
    EXR in `output_dir` matching `filename_pattern`.

    Parameters
    ----------
    output_dir:
        Path to the MRQ render output directory.
    filename_pattern:
        Python format string (e.g. `"render.{frame:07d}.exr"`). The
        `{frame:<N>d}` placeholder marks where the absolute CSV frame
        number appears in the filename; N digits of zero-pad.
    start_csv_frame:
        Absolute CSV frame number of the first rendered frame (= MRQ
        `FrameNumberOffset`). Files with absolute frame < this value
        are skipped — they likely belong to a different sequence.
    start_timecode:
        SMPTE timecode at `start_csv_frame`.
    fps:
        Frame rate (24, 23.976, 25, 29.97, 30, 50, 59.94, 60).

    Returns
    -------
    int
        Number of files patched.
    """
    out_path = Path(output_dir)
    if not out_path.is_dir():
        return 0
    _ensure_oiiotool()

    fn_regex = _filename_pattern_to_regex(filename_pattern)
    nominal_fps = int(round(fps))

    processed = 0
    for file in sorted(out_path.iterdir()):
        match = fn_regex.match(file.name)
        if match is None:
            continue
        frame = int(match.group(1))
        offset = frame - start_csv_frame
        if offset < 0:
            continue
        tc = _frame_to_timecode(start_timecode, offset)
        subprocess.check_call([
            "oiiotool", str(file),
            "--attrib:type=timecode", "smpte:TimeCode", str(tc),
            "--attrib:type=rational", "FramesPerSecond", f"{nominal_fps}/1",
            "-o", str(file),
        ])
        processed += 1
    return processed
