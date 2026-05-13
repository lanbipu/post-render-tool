"""SMPTE Timecode parser + arithmetic.

Pure Python, no UE dependency. Supports 24/23.976/25/29.97/30/50/59.94/60 fps.
Drop-frame (NTSC 29.97 / 59.94) uses the Bevin standard formula.

`to_frames()` returns the continuous wall-clock frame counter starting from
00:00:00:00. Drop-frame skips frame *labels* (e.g. 00:01:00;00 / ;01 do not
exist), not the real frame stream — so 00:01:00;02 == frame 1800.

All invariants are enforced in `Timecode.__post_init__`, so direct
construction (`Timecode(h, m, s, f, drop_frame, num, den)`) from DataAsset
fields gets the same guarantees as `Timecode.parse()`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_FRACTIONAL_FPS: dict[float, tuple[int, int]] = {
    23.976: (24000, 1001),
    29.97:  (30000, 1001),
    59.94:  (60000, 1001),
}

_INTEGER_FPS = (24, 25, 30, 50, 60)
_DROP_FRAME_FPS = (29.97, 59.94)

# HH:MM:SS<sep>FF — sep ∈ { ':', ';', '.' }, ASCII digits only (no fullwidth).
_TC_RE = re.compile(r"^([0-9]{1,2}):([0-9]{2}):([0-9]{2})([:;.])([0-9]{2,3})$")


def _resolve_frame_rate(fps: float) -> tuple[int, int]:
    for known_fps, fraction in _FRACTIONAL_FPS.items():
        if abs(fps - known_fps) < 0.01:
            return fraction
    rounded = int(round(fps))
    if rounded in _INTEGER_FPS and abs(fps - rounded) < 0.01:
        return (rounded, 1)
    raise ValueError(
        f"Unsupported frame rate {fps}; supported: "
        "23.976, 24, 25, 29.97, 30, 50, 59.94, 60"
    )


def _is_drop_frame_for_fps(fps: float) -> bool:
    return any(abs(fps - df) < 0.01 for df in _DROP_FRAME_FPS)


def _drop_count(rate_num: int, rate_den: int) -> int:
    """How many frame labels are skipped at each non-10th-minute boundary."""
    return 2 if abs(rate_num / rate_den - 29.97) < 0.01 else 4


def _nominal_fps_int(rate_num: int, rate_den: int) -> int:
    return round(rate_num / rate_den)


@dataclass(frozen=True)
class Timecode:
    hours: int
    minutes: int
    seconds: int
    frames: int
    drop_frame: bool
    rate_num: int
    rate_den: int

    def __post_init__(self) -> None:
        nominal_fps = _nominal_fps_int(self.rate_num, self.rate_den)
        # field ranges
        if not (0 <= self.hours < 24):
            raise ValueError(f"hours out of range [0,24): {self.hours}")
        if not (0 <= self.minutes < 60):
            raise ValueError(f"minutes out of range [0,60): {self.minutes}")
        if not (0 <= self.seconds < 60):
            raise ValueError(f"seconds out of range [0,60): {self.seconds}")
        if not (0 <= self.frames < nominal_fps):
            raise ValueError(
                f"frames out of range [0,{nominal_fps}): {self.frames} (fps={nominal_fps})"
            )
        # drop-frame label legality: at non-10th-minute boundaries,
        # the first drop_count labels of second 00 do not exist.
        if (
            self.drop_frame
            and self.seconds == 0
            and self.minutes % 10 != 0
            and self.frames < _drop_count(self.rate_num, self.rate_den)
        ):
            raise ValueError(
                f"Illegal drop-frame label {self}: "
                f"minute {self.minutes} is not a multiple of 10, frames "
                f"< {_drop_count(self.rate_num, self.rate_den)} at second 00 are dropped"
            )

    @classmethod
    def parse(cls, s: str, fps: float) -> "Timecode":
        m = _TC_RE.match(s.strip())
        if m is None:
            raise ValueError(f"Invalid timecode string: {s!r}")
        hh, mm, ss, sep, ff = m.groups()
        rate_num, rate_den = _resolve_frame_rate(fps)
        drop = _is_drop_frame_for_fps(fps)
        # Enforce separator/drop_frame consistency to catch CSV/NLE mismatches early.
        # '.' is accepted for both (Disguise's loose convention); ':' implies non-drop;
        # ';' implies drop.
        if sep == ";" and not drop:
            raise ValueError(
                f"Separator ';' (drop-frame) used with non-drop fps {fps}: {s!r}"
            )
        if sep == ":" and drop:
            raise ValueError(
                f"Separator ':' (non-drop) used with drop-frame fps {fps}: {s!r}"
            )
        return cls(
            hours=int(hh),
            minutes=int(mm),
            seconds=int(ss),
            frames=int(ff),
            drop_frame=drop,
            rate_num=rate_num,
            rate_den=rate_den,
        )

    def to_frames(self) -> int:
        """Continuous frame counter since 00:00:00:00.

        Non-drop: pure positional arithmetic.
        Drop-frame: Bevin formula —
            nominal_count - drop_count * (total_minutes - total_minutes // 10).
        """
        nominal_fps = _nominal_fps_int(self.rate_num, self.rate_den)
        nominal_count = (
            ((self.hours * 60 + self.minutes) * 60 + self.seconds) * nominal_fps
            + self.frames
        )
        if not self.drop_frame:
            return nominal_count
        dc = _drop_count(self.rate_num, self.rate_den)
        total_minutes = self.hours * 60 + self.minutes
        full_tens = total_minutes // 10
        total_drop = dc * (total_minutes - full_tens)
        return nominal_count - total_drop

    def __str__(self) -> str:
        sep = ";" if self.drop_frame else ":"
        return (
            f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}"
            f"{sep}{self.frames:02d}"
        )


def _frames_per_24h(rate_num: int, rate_den: int, drop_frame: bool) -> int:
    """Total continuous frames in one 24h cycle (used for cross-midnight unwrap)."""
    nominal = _nominal_fps_int(rate_num, rate_den)
    if not drop_frame:
        return nominal * 24 * 3600
    dc = _drop_count(rate_num, rate_den)
    # 24h = 144 ten-minute blocks; each block = nominal*600 - dc*9 real frames.
    return 144 * (nominal * 600 - dc * 9)


def unwrap_timecode_frames(first: "Timecode | None", later: "Timecode | None") -> int:
    """Real frame delta from `first` to `later`, adding 24h on wrap-around.

    Used by csv_parser to validate `frame_number` ↔ `timestamp` equivalence
    across midnight boundary. Raises ValueError on `None` input or mismatched
    rates.
    """
    if first is None or later is None:
        raise ValueError("unwrap_timecode_frames: timecode is None")
    if (first.rate_num, first.rate_den, first.drop_frame) != (
        later.rate_num, later.rate_den, later.drop_frame,
    ):
        raise ValueError("Cannot unwrap timecodes with mismatched rates")
    delta = later.to_frames() - first.to_frames()
    if delta >= 0:
        return delta
    return delta + _frames_per_24h(first.rate_num, first.rate_den, first.drop_frame)
