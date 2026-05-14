"""EXR header SMPTE timecode patcher.

Offline (post-render) — uses the `oiio-static-python` PyPI wheel
(OpenImageIO 3.0.8 statically built, with Python bindings) to write
typed `smpte:TimeCode` + `FramesPerSecond` rational attributes to EXR
files matching a filename pattern. In-process; same OIIO C++ library
that backs the `oiiotool` CLI, so spike-validated preservation of
channels / compression / multipart / pixelAspectRatio transfers
directly.

Backend rationale: see `scripts/exr_timecode_spike_report.md`
(2026-05-14 addendum). The conda-forge Windows `openimageio` package
does not ship `oiiotool.exe`, and PyPI `OpenEXR` 3.x had API
mismatches verified empirically. `oiio-static-python` (the same OIIO
library, wheel-bundled) was the chosen swap.

Install:
    pip install --user oiio-static-python==3.0.8.1.1
    (already on lanPC UE Python alongside opentimelineio.)

Public API:
    patch_exr_timecode_in_dir(output_dir, filename_pattern,
                              start_csv_frame, start_timecode, fps)
        Walks `output_dir`, matches `filename_pattern` to extract the
        absolute CSV frame number from each filename, calculates the
        per-frame SMPTE timecode, and rewrites the EXR with that
        timecode in the header. All subimages are rewritten via
        `ImageInput.seek_subimage` + `ImageOutput` multi-subimage
        open + 'AppendSubimage' (multipart-safe; ImageBuf.write has no
        multi-subimage semantics). Atomic — `os.replace` over the
        original only after every subimage wrote successfully. Returns
        the count of patched files.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .timecode import Timecode, _frames_per_24h


def _ensure_oiio() -> None:
    """Lazy import + clear error message if the OIIO Python wheel is
    missing. Imported on first call rather than at module scope so the
    pure-Python `_frame_to_timecode` helper remains testable without
    `oiio-static-python` installed.
    """
    try:
        import OpenImageIO  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "OpenImageIO Python binding not installed on the current "
            "Python. Install with `pip install --user "
            "oiio-static-python==3.0.8.1.1` (same install pattern as "
            "opentimelineio). Backend was swapped from "
            "subprocess+oiiotool on 2026-05-14 — see "
            "scripts/exr_timecode_spike_report.md."
        ) from e


def _smpte_encode_time_field(hh: int, mm: int, ss: int, ff: int,
                              drop_frame: bool = False) -> int:
    """Encode SMPTE 12M timecode `time` field as packed uint32 BCD.
    Mirrors the OpenEXR / OIIO C++ Imath::TimeCode constructor — the
    oiio-static-python 3.0.8 wheel does NOT expose `oiio.TimeCode`,
    so encoding is done by hand here.

    Layout (low-bit-first per SMPTE 12M):
      bits 0-3   frame units (BCD)
      bits 4-5   frame tens (2 bits)
      bit  6     drop-frame flag
      bit  7     color-frame flag (0)
      bits 8-11  seconds units
      bits 12-14 seconds tens (3 bits)
      bit  15    binary group flag 0
      bits 16-19 minutes units
      bits 20-22 minutes tens (3 bits)
      bit  23    binary group flag 1
      bits 24-27 hours units
      bits 28-29 hours tens (2 bits)
      bits 30-31 binary group flag 2 + field/bgf
    """
    val = (ff % 10) | ((ff // 10) << 4)
    if drop_frame:
        val |= 1 << 6
    val |= ((ss % 10) << 8) | ((ss // 10) << 12)
    val |= ((mm % 10) << 16) | ((mm // 10) << 20)
    val |= ((hh % 10) << 24) | ((hh // 10) << 28)
    return val


def _frame_to_timecode(start: Timecode, offset_frames: int) -> Timecode:
    """Inverse of Timecode.to_frames(): given an offset in real frames
    from `start`, return the SMPTE display timecode at that offset.

    Drop-frame aware (Bevin 29.97 / 59.94 NTSC reversed).
    """
    total = start.to_frames() + offset_frames
    # Wrap at 24h so cross-midnight renders (start near 23:59 + render
    # spans past 00:00:00:00) don't produce hours>=24 that would be
    # rejected by Timecode.__post_init__.
    day_frames = _frames_per_24h(start.rate_num, start.rate_den, start.drop_frame)
    total = total % day_frames
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


_UNRESOLVED_TOKEN_RE = re.compile(r"\{(?!frame:)\w+\}")


def _validate_filename_pattern(pattern: str) -> None:
    """Catch subdir / unresolved MRQ tokens before silent zero-count match."""
    # MRQ formats like `{sequence_name}/render.{frame_number}` produce
    # patterns with `/` after token resolution. patch_exr_timecode_in_dir
    # only scans the top-level dir, so subdir patterns silently fail.
    if "/" in pattern or "\\" in pattern:
        raise ValueError(
            f"filename_pattern contains a path separator ({pattern!r}); "
            "this is usually because MRQ file_name_format includes a "
            "subdirectory token (e.g. '{sequence_name}/render.{frame_number}'). "
            "Point `output_dir` at the resolved subdirectory and pass only "
            "the basename portion of the pattern, e.g. 'render.{frame:07d}.exr'."
        )
    # Unresolved MRQ tokens (e.g. {shot_name}, {date}, {render_pass}) survive
    # `_filename_pattern_to_regex` as escaped literals and never match.
    remaining = _UNRESOLVED_TOKEN_RE.findall(pattern)
    if remaining:
        raise ValueError(
            f"filename_pattern has unresolved tokens {remaining}: {pattern!r}; "
            "derive_mrq_filename_pattern only resolves {sequence_name} + "
            "{frame_number}. Remove other MRQ tokens from file_name_format "
            "or pass an explicit pattern."
        )


def _filename_pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert `"render.{frame:07d}.exr"` → compiled regex with the frame
    number as group 1.
    """
    _validate_filename_pattern(pattern)
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
    _ensure_oiio()
    import OpenImageIO as oiio

    fn_regex = _filename_pattern_to_regex(filename_pattern)
    # Preserve fractional NTSC rates exactly (23.976 = 24000/1001 etc.) so
    # EXR readers don't drift over long takes when interpreting the
    # SMPTE timecode at the wrong playback rate.
    rate_num = start_timecode.rate_num
    rate_den = start_timecode.rate_den

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
        time_field = _smpte_encode_time_field(
            tc.hours, tc.minutes, tc.seconds, tc.frames,
            drop_frame=tc.drop_frame,
        )
        tc_value = (time_field, 0)  # (time, user) — user field unused
        fps_value = (rate_num, rate_den)

        # Step A: read every subimage's spec + pixels via ImageInput.
        # ImageInput.seek_subimage is the authoritative subimage iterator;
        # ImageBuf.has_error past last subimage is unreliable.
        inp = oiio.ImageInput.open(str(file))
        if inp is None:
            # Not a readable EXR (or a non-image file matching the
            # filename pattern by accident) — skip silently.
            continue
        subimages = []  # [(mutated_spec, pixels_ndarray), ...]
        try:
            si = 0
            while inp.seek_subimage(si, 0):
                spec = inp.spec()
                spec.attribute("smpte:TimeCode", oiio.TypeTimeCode, tc_value)
                spec.attribute("FramesPerSecond", oiio.TypeRational, fps_value)
                pixels = inp.read_image(spec.format)
                if pixels is None:
                    raise RuntimeError(
                        f"OIIO read_image subimage {si} of {file}: "
                        f"{inp.geterror()}"
                    )
                subimages.append((spec, pixels))
                si += 1
        finally:
            inp.close()

        if not subimages:
            continue

        # Step B: write all subimages to <file>.tmp via ImageOutput.
        # Multipart path: pass list of specs to declare layout, write
        # subimage 0, then re-open with mode='AppendSubimage' for each
        # additional subimage. Single-part path: pass the single spec.
        # Use ".partial.exr" suffix so ImageOutput infers the format from
        # extension. ".tmp" would fail with "could not find a format
        # writer" since OIIO infers by extension.
        tmp = str(file) + ".partial.exr"
        try:
            out = oiio.ImageOutput.create(tmp)
            if out is None:
                raise RuntimeError(
                    f"OIIO ImageOutput.create for {tmp}"
                )
            specs_only = [sp for sp, _ in subimages]
            if len(specs_only) == 1:
                ok = out.open(tmp, specs_only[0])
            else:
                ok = out.open(tmp, specs_only)
            if not ok:
                raise RuntimeError(
                    f"OIIO open {tmp}: {out.geterror()}"
                )
            for i, (spec, pixels) in enumerate(subimages):
                if i > 0:
                    # 'AppendSubimage' is a string mode in OIIO Python
                    # 3.0.8.1 (verified by probe Phase A.7 on 2026-05-14).
                    if not out.open(tmp, spec, "AppendSubimage"):
                        raise RuntimeError(
                            f"OIIO AppendSubimage #{i}: {out.geterror()}"
                        )
                if not out.write_image(pixels):
                    raise RuntimeError(
                        f"OIIO write_image subimage {i}: {out.geterror()}"
                    )
            out.close()
            # Step C: atomic swap. On any prior raise, tmp is not
            # promoted — original file untouched.
            os.replace(tmp, str(file))
            processed += 1
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    return processed
