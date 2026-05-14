"""OpenTimelineIO sidecar exporter.

Pure Python, no `unreal` dependency. Produces a `.otio` file describing the
rendered CG image sequence so DaVinci 19+ / Nuke Studio / Flame can ingest
the timeline + SMPTE timecode + ImageSequenceReference in one drag-drop.

Public API:
    export_sidecar(sidecar_path, shot_name, cg_render_dir,
                   cg_filename_pattern, start_csv_frame, frame_count,
                   start_timecode, fps)

Timeline layout:
    Timeline(name=shot_name, global_start_time=<RationalTime at SMPTE start>)
     └─ Track "CG Render" (Video)
          └─ Clip
               media_reference = ImageSequenceReference(
                   target_url_base=<file://cg_render_dir/>,
                   name_prefix=<from filename_pattern>,
                   name_suffix=<from filename_pattern>,
                   start_frame=start_csv_frame,
                   frame_zero_padding=<from filename_pattern>,
                   rate=fps)
               source_range = TimeRange(0, frame_count) @ fps

`global_start_time` is what conform tools key off to align the CG timeline
with on-set footage's embedded SMPTE timecode.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

import opentimelineio as otio  # noqa: I001

from .timecode import Timecode


_PATTERN_RE = re.compile(r"^(.*?)\{frame:0?(\d+)d\}(.*)$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _to_file_uri_base(cg_render_dir: str) -> str:
    """`E:/RenderStream Projects/take_4` →
    `file:///E:/RenderStream%20Projects/take_4/`.

    Platform-aware: Windows drive paths go through `PureWindowsPath` so
    DaVinci/Nuke can locate the EXRs; POSIX paths use `PurePosixPath`.
    """
    if _WINDOWS_DRIVE_RE.match(cg_render_dir):
        uri = PureWindowsPath(cg_render_dir).as_uri()
    else:
        uri = PurePosixPath(cg_render_dir).as_uri()
    return uri.rstrip("/") + "/"


def _split_filename_pattern(pattern: str) -> tuple[str, str, int]:
    """`"render.{frame:07d}.exr"` → (`"render."`, `".exr"`, 7)."""
    match = _PATTERN_RE.match(pattern)
    if match is None:
        raise ValueError(
            f"Unsupported filename pattern (missing `{{frame:Nd}}`): {pattern!r}"
        )
    return match.group(1), match.group(3), int(match.group(2))


def export_sidecar(
    sidecar_path: str,
    shot_name: str,
    cg_render_dir: str,
    cg_filename_pattern: str,
    start_csv_frame: int,
    frame_count: int,
    start_timecode: Timecode,
    fps: float,
) -> None:
    """Dump a `.otio` timeline at `sidecar_path` for the given shot.

    Parameters
    ----------
    sidecar_path:
        Output `.otio` file path.
    shot_name:
        Timeline + clip name (e.g. "take_4_dense" or "LS_take_4").
    cg_render_dir:
        Directory containing the rendered CG EXR sequence.
    cg_filename_pattern:
        Python-style format string for the EXR filenames; must contain a
        `{frame:Nd}` placeholder (e.g. `"render.{frame:07d}.exr"`).
    start_csv_frame:
        Absolute CSV frame number of the first rendered EXR. Goes into
        `ImageSequenceReference.start_frame` so DaVinci/Nuke can locate
        the files on disk.
    frame_count:
        Number of rendered frames (= clip duration in frames).
    start_timecode:
        SMPTE timecode of the first rendered frame. Becomes the
        timeline's `global_start_time`.
    fps:
        Frame rate (24, 23.976, 25, 29.97, 30, 50, 59.94, 60).
    """
    name_prefix, name_suffix, padding = _split_filename_pattern(cg_filename_pattern)

    # Derive the exact rate from the start_timecode (which preserves the
    # 24000/1001 / 30000/1001 / 60000/1001 NTSC fractionals); the caller's
    # `fps` is the rounded UI value (23.976 vs 23.97602...). Using the
    # exact rate avoids long-take drift in DaVinci/Nuke conform.
    rate = start_timecode.rate_num / start_timecode.rate_den

    timeline = otio.schema.Timeline(name=shot_name)
    # global_start_time encodes the SMPTE start anchor conform tools snap
    # to. SMPTE frame count since 00:00:00:00 + exact rate.
    timeline.global_start_time = otio.opentime.RationalTime(
        start_timecode.to_frames(), rate
    )

    track = otio.schema.Track(
        name="CG Render", kind=otio.schema.TrackKind.Video
    )

    url_base = _to_file_uri_base(cg_render_dir)

    img_ref = otio.schema.ImageSequenceReference(
        target_url_base=url_base,
        name_prefix=name_prefix,
        name_suffix=name_suffix,
        start_frame=start_csv_frame,
        frame_zero_padding=padding,
        rate=rate,
        available_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, rate),
            duration=otio.opentime.RationalTime(frame_count, rate),
        ),
    )
    clip = otio.schema.Clip(
        name=f"{shot_name}_cg",
        media_reference=img_ref,
        source_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, rate),
            duration=otio.opentime.RationalTime(frame_count, rate),
        ),
    )
    track.append(clip)
    timeline.tracks.append(track)

    otio.adapters.write_to_file(timeline, sidecar_path)
