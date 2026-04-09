"""Coordinate system transform: Disguise Designer (Y-up, meters) → UE (Z-up, cm)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from . import config


@dataclass
class TransformConfig:
    """Per-axis transform rules. Each field is (source_index, scale_factor)."""

    pos_x: Tuple[int, float] = field(default_factory=lambda: config.POSITION_MAPPING["x"])
    pos_y: Tuple[int, float] = field(default_factory=lambda: config.POSITION_MAPPING["y"])
    pos_z: Tuple[int, float] = field(default_factory=lambda: config.POSITION_MAPPING["z"])
    rot_pitch: Tuple[int, float] = field(default_factory=lambda: config.ROTATION_MAPPING["pitch"])
    rot_yaw: Tuple[int, float] = field(default_factory=lambda: config.ROTATION_MAPPING["yaw"])
    rot_roll: Tuple[int, float] = field(default_factory=lambda: config.ROTATION_MAPPING["roll"])

    def __post_init__(self) -> None:
        # Validate each field is a 2-tuple (idx, scale)
        for attr in ("pos_x", "pos_y", "pos_z", "rot_pitch", "rot_yaw", "rot_roll"):
            val = getattr(self, attr)
            if not (isinstance(val, (tuple, list)) and len(val) == 2):
                raise ValueError(f"TransformConfig.{attr} must be a 2-tuple (source_idx, scale)")


def _default_cfg() -> TransformConfig:
    """Return a new TransformConfig loaded from config module defaults."""
    return TransformConfig()


def transform_position(
    designer_x: float,
    designer_y: float,
    designer_z: float,
    cfg: TransformConfig | None = None,
) -> tuple:
    """Map Designer (x, y, z) in meters to UE (x, y, z) in centimeters.

    Returns:
        (ue_x, ue_y, ue_z) as floats
    """
    if cfg is None:
        cfg = _default_cfg()

    src = (designer_x, designer_y, designer_z)

    def apply(rule: tuple) -> float:
        idx, scale = rule
        return src[idx] * scale

    return (apply(cfg.pos_x), apply(cfg.pos_y), apply(cfg.pos_z))


def transform_rotation(
    designer_rx: float,
    designer_ry: float,
    designer_rz: float,
    cfg: TransformConfig | None = None,
) -> tuple:
    """Map Designer rotation (rx, ry, rz) in degrees to UE (pitch, yaw, roll).

    Returns:
        (pitch, yaw, roll) as floats
    """
    if cfg is None:
        cfg = _default_cfg()

    src = (designer_rx, designer_ry, designer_rz)

    def apply(rule: tuple) -> float:
        idx, scale = rule
        return src[idx] * scale

    return (apply(cfg.rot_pitch), apply(cfg.rot_yaw), apply(cfg.rot_roll))


def transform_focus_distance(designer_meters: float) -> float:
    """Convert focus distance from meters (Designer) to centimeters (UE).

    Args:
        designer_meters: Focus distance in meters.

    Returns:
        Focus distance in centimeters.
    """
    return designer_meters * 100.0
