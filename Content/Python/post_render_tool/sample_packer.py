"""Pure-Python CSV FrameData → camera sample packer for Custom MovieScene Track.

Produces (source_frame_numbers, samples) ready for one-shot ingestion into
UPostRenderCameraSamples DataAsset via the PostRenderToolBuildHelper bridge.

Coordinate transforms are applied here (so unit tests don't need UE). The
output sample dict's keys match FPostRenderCameraSample USTRUCT field names
(snake_case here; the C++ bridge maps to PascalCase).

No `unreal` import — testable outside UE.
"""

from __future__ import annotations

from typing import List, Tuple

from .coordinate_transform import (
    TransformConfig,
    transform_focus_distance,
    transform_position,
    transform_rotation,
)
from .csv_parser import csv_overscan_to_ue_overscan
from .timecode import unwrap_timecode_frames


# Sample field schema. Order is informational only; consumers index by key.
SAMPLE_FIELDS = (
    "location_x", "location_y", "location_z",
    "rotation_pitch", "rotation_yaw", "rotation_roll",
    "focal_length_mm",
    "aperture",
    "focus_distance_cm",
    "k1", "k2", "k3",
    "aspect",
    "sensor_horizontal_offset_mm", "sensor_vertical_offset_mm",
    "overscan",
)


def pack_samples(frames) -> Tuple[List[int], List[dict]]:
    """Convert a list of csv_parser.FrameData to (frame_numbers, samples).

    Parameters
    ----------
    frames:
        Iterable of csv_parser.FrameData (or duck-typed equivalent).

    Returns
    -------
    (frame_numbers, samples)
        ``frame_numbers`` is a list[int] of CSV source frame numbers (preserves
        gaps from tracker drop frames). ``samples`` is a list[dict] of equal
        length; each dict has every key in SAMPLE_FIELDS.
    """
    cfg = TransformConfig()
    frame_numbers: List[int] = []
    samples: List[dict] = []

    # Use timecode-derived frame index (CSV `timestamp` column) as the
    # sequence frame, NOT Disguise's free-running CSV `frame` counter.
    # The two streams are not 1:1 — `timestamp` is the wall-clock SMPTE
    # the user shoots against (LTC / free-run), `frame` is Disguise's
    # internal session counter. For Sequencer ruler + MRQ filename to
    # line up with on-set footage, we anchor on the SMPTE stream.
    #
    # Cross-midnight unwrap: `Timecode.to_frames()` wraps at 24h, so a
    # take crossing 00:00:00:00 would produce non-monotonic raw values
    # and fail WriteCameraSamples' strictly-ascending invariant. Anchor
    # on `frames[0].timecode` and add `unwrap_timecode_frames(first, f)`
    # so every output frame index is base + monotonic delta.
    if not frames:
        return frame_numbers, samples
    if frames[0].timecode is None:
        raise RuntimeError(
            f"sample_packer requires FrameData.timecode populated. "
            f"frame {frames[0].frame_number}: call parse_csv_dense(..., "
            "fps=fps) first."
        )
    first_tc = frames[0].timecode
    base_frame = first_tc.to_frames()

    for f in frames:
        ue_x, ue_y, ue_z = transform_position(
            f.offset_x, f.offset_y, f.offset_z, cfg=cfg
        )
        pitch, yaw, roll = transform_rotation(
            f.rotation_x, f.rotation_y, f.rotation_z, cfg=cfg
        )
        focus_cm = transform_focus_distance(f.focus_distance)
        overscan = csv_overscan_to_ue_overscan(
            f.overscan_x, f.overscan_y, frame_number=f.frame_number
        )

        if f.timecode is None:
            raise RuntimeError(
                f"sample_packer requires FrameData.timecode populated. "
                f"frame {f.frame_number}: call parse_csv_dense(..., fps=fps) first."
            )
        frame_numbers.append(base_frame + unwrap_timecode_frames(first_tc, f.timecode))
        samples.append({
            "location_x": ue_x,
            "location_y": ue_y,
            "location_z": ue_z,
            "rotation_pitch": pitch,
            "rotation_yaw": yaw,
            "rotation_roll": roll,
            "focal_length_mm": f.focal_length_mm,
            "aperture": f.aperture,
            "focus_distance_cm": focus_cm,
            "k1": f.k1,
            "k2": f.k2,
            "k3": f.k3,
            "aspect": f.aspect_ratio,
            "sensor_horizontal_offset_mm": -f.center_shift_x_mm,
            "sensor_vertical_offset_mm": -f.center_shift_y_mm,
            "overscan": overscan,
        })

    return frame_numbers, samples


def detect_contiguous(frame_numbers: List[int]) -> bool:
    """Return True iff frame_numbers is a strictly +1 ascending run.

    Empty list and single-element list are both considered contiguous
    (vacuous case). Used by the evaluator to choose between O(1) direct
    index lookup vs. O(log N) binary search.
    """
    if len(frame_numbers) < 2:
        return True
    expected = frame_numbers[0] + 1
    for n in frame_numbers[1:]:
        if n != expected:
            return False
        expected += 1
    return True
