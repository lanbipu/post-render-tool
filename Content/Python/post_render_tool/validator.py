"""FOV validation and anomalous frame detection for VP Post-Render Tool."""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import config
from .csv_parser import CsvDenseResult, FrameData


# ---------------------------------------------------------------------------
# FOV computation
# ---------------------------------------------------------------------------

def compute_fov_h(focal_length_mm: float, sensor_width_mm: float) -> float:
    """Horizontal FOV in degrees.

    FOV = 2 * atan(sensor_width / (2 * focal_length))
    """
    return math.degrees(2.0 * math.atan(sensor_width_mm / (2.0 * focal_length_mm)))


# ---------------------------------------------------------------------------
# FOV validation
# ---------------------------------------------------------------------------

@dataclass
class FovCheckResult:
    """Result of per-frame FOV consistency check."""
    max_fov_error_deg: float
    max_fov_error_frame_index: int
    has_fov_warning: bool


def validate_fov(
    frames: List[FrameData],
    threshold_deg: Optional[float] = None,
) -> FovCheckResult:
    """Compare computed FOV vs CSV fov_h for every frame.

    Parameters
    ----------
    frames:
        List of FrameData objects.
    threshold_deg:
        Error threshold in degrees. Defaults to config.FOV_ERROR_THRESHOLD_DEG.

    Returns
    -------
    FovCheckResult
    """
    if threshold_deg is None:
        threshold_deg = config.FOV_ERROR_THRESHOLD_DEG

    max_error = 0.0
    max_error_idx = 0

    for i, frame in enumerate(frames):
        computed = compute_fov_h(frame.focal_length_mm, frame.sensor_width_mm)
        error = abs(computed - frame.fov_h)
        if error > max_error:
            max_error = error
            max_error_idx = i

    return FovCheckResult(
        max_fov_error_deg=max_error,
        max_fov_error_frame_index=max_error_idx,
        has_fov_warning=(max_error > threshold_deg),
    )


# ---------------------------------------------------------------------------
# Anomalous frame detection
# ---------------------------------------------------------------------------

def detect_anomalous_frames(
    frames: List[FrameData],
    pos_threshold_m: Optional[float] = None,
    rot_threshold_deg: Optional[float] = None,
) -> List[dict]:
    """Detect frames with large position or rotation jumps relative to previous frame.

    Position fields (offset_x/y/z) are assumed to be in **meters** as exported
    by Disguise Designer. The config threshold is stored in centimeters and
    converted here (÷ 100).

    Parameters
    ----------
    frames:
        Ordered list of FrameData.
    pos_threshold_m:
        Position jump threshold in meters. Defaults to
        config.POSITION_JUMP_THRESHOLD_CM / 100.
    rot_threshold_deg:
        Rotation jump threshold in degrees. Defaults to
        config.ROTATION_JUMP_THRESHOLD_DEG.

    Returns
    -------
    list[dict]
        Each dict has keys: frame_index, frame_number, reason, value.
        May contain multiple entries per frame (one per axis / axis type).
    """
    if pos_threshold_m is None:
        pos_threshold_m = config.POSITION_JUMP_THRESHOLD_CM / 100.0
    if rot_threshold_deg is None:
        rot_threshold_deg = config.ROTATION_JUMP_THRESHOLD_DEG

    anomalies: List[dict] = []

    for i in range(1, len(frames)):
        prev = frames[i - 1]
        curr = frames[i]

        # --- Position check (per-axis, then Euclidean distance) ---
        dx = curr.offset_x - prev.offset_x
        dy = curr.offset_y - prev.offset_y
        dz = curr.offset_z - prev.offset_z
        pos_dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        if pos_dist > pos_threshold_m:
            anomalies.append({
                "frame_index": i,
                "frame_number": curr.frame_number,
                "reason": "position_jump",
                "value": pos_dist,
            })

        # --- Rotation check (per-axis max) ---
        drx = abs(curr.rotation_x - prev.rotation_x)
        dry = abs(curr.rotation_y - prev.rotation_y)
        drz = abs(curr.rotation_z - prev.rotation_z)
        max_rot_delta = max(drx, dry, drz)

        if max_rot_delta > rot_threshold_deg:
            anomalies.append({
                "frame_index": i,
                "frame_number": curr.frame_number,
                "reason": "rotation_jump",
                "value": max_rot_delta,
            })

    return anomalies


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    """Full validation report for a parsed CSV Dense file."""
    frame_count: int
    timecode_start: str
    timecode_end: str
    focal_length_range: Tuple[float, float]
    sensor_width_mm: float
    fps: Optional[float]
    fov_check: FovCheckResult
    anomalous_frames: List[dict] = field(default_factory=list)

    def format_report(self) -> str:
        """Return a Chinese-formatted text report with ✓/⚠ symbols."""
        lines = []
        lines.append("=" * 50)
        lines.append("【VP Post-Render 验证报告】")
        lines.append("=" * 50)

        lines.append(f"  帧数        : {self.frame_count}")
        lines.append(f"  时间码范围  : {self.timecode_start} → {self.timecode_end}")
        fl_min, fl_max = self.focal_length_range
        if fl_min == fl_max:
            lines.append(f"  焦距        : {fl_min:.3f} mm")
        else:
            lines.append(f"  焦距范围    : {fl_min:.3f} – {fl_max:.3f} mm")
        lines.append(f"  传感器宽度  : {self.sensor_width_mm:.3f} mm")
        fps_str = f"{self.fps:.3f}" if self.fps else "未知"
        lines.append(f"  帧率        : {fps_str} fps")

        lines.append("")
        lines.append("【FOV 一致性检查】")
        fov = self.fov_check
        symbol = "⚠" if fov.has_fov_warning else "✓"
        lines.append(
            f"  {symbol} 最大 FOV 误差: {fov.max_fov_error_deg:.4f}° "
            f"(帧索引 {fov.max_fov_error_frame_index})"
        )
        threshold = config.FOV_ERROR_THRESHOLD_DEG
        lines.append(f"  阈值        : {threshold}°")

        lines.append("")
        lines.append("【异常帧检测】")
        if not self.anomalous_frames:
            lines.append("  ✓ 未发现位置/旋转跳变")
        else:
            lines.append(f"  ⚠ 发现 {len(self.anomalous_frames)} 处异常:")
            for a in self.anomalous_frames:
                reason_cn = "位置跳变" if a["reason"] == "position_jump" else "旋转跳变"
                lines.append(
                    f"    - 帧索引 {a['frame_index']} (#{a['frame_number']}) "
                    f"| {reason_cn} | 幅度: {a['value']:.4f}"
                )

        lines.append("=" * 50)
        return "\n".join(lines)


def generate_report(csv_result: CsvDenseResult, fps: Optional[float] = None) -> ValidationReport:
    """Generate a ValidationReport from a parsed CsvDenseResult.

    Parameters
    ----------
    csv_result:
        Populated CsvDenseResult from csv_parser.parse_csv_dense().
    fps:
        Frame rate to record in the report. Falls back to
        csv_result.detected_fps if not provided.

    Returns
    -------
    ValidationReport
    """
    effective_fps = fps if fps is not None else csv_result.detected_fps

    fov_check = validate_fov(csv_result.frames)
    anomalies = detect_anomalous_frames(csv_result.frames)

    return ValidationReport(
        frame_count=csv_result.frame_count,
        timecode_start=csv_result.timecode_start,
        timecode_end=csv_result.timecode_end,
        focal_length_range=csv_result.focal_length_range,
        sensor_width_mm=csv_result.sensor_width_mm,
        fps=effective_fps,
        fov_check=fov_check,
        anomalous_frames=anomalies,
    )
