"""Centralized configuration for VP Post-Render Tool."""

# --- Coordinate Transform (Designer Y-up meters → UE Z-up centimeters) ---
# Each tuple: (source_axis_index, scale_factor)
# source_axis_index: 0=Designer.x, 1=Designer.y, 2=Designer.z
# Regression-guarded by tests/test_coordinate_transform.py::TestKnownPoses.

POSITION_MAPPING = {
    "x": (2, 100.0),
    "y": (0, 100.0),
    "z": (1, 100.0),
}

# Identity per-axis (pitch=rx, yaw=ry, roll=rz). Disguise's CSV rotation already
# matches UE's Rotator semantics directly — kept as a configurable map only so
# Operators can override via the UI for non-standard exports.
ROTATION_MAPPING = {
    "pitch": (0, 1.0),
    "yaw":   (1, 1.0),
    "roll":  (2, 1.0),
}

# Per-axis rotation offset (degrees), applied AFTER the mapping above.
# Use case: 整体相机姿态与实拍片场约定不对齐时（例如需要整体偏航 -90°）。
# 注意：offset 叠加在本地 pitch/yaw/roll 上；当相机 pitch/roll ≈ 0 时
# 等价于绕 world Z 旋转 yaw 偏移量，否则会与真正的"世界 Z 旋转"不同。
ROTATION_OFFSET_DEG = {
    "pitch": 0.0,
    "yaw": 0.0,
    "roll": 0.0,
}

# --- Distortion Mode ---
# 切换 distortion 渲染管线: 老路 (LensFile + UE BrownConradyUD) vs 新路 (自定义
# post-process material). 默认 LEGACY_LENS_FILE 保护生产数据; 改成
# CUSTOM_POST_PROCESS 后 pipeline 在 build 阶段会跳过 LensFile 写入并改挂
# PostRenderDistortionControllerComponent + M_PRT_OfficialSensorInverse material.
# 详见 docs/custom-postprocess-distortion-final-plan.md.

class DistortionMode:
    LEGACY_LENS_FILE = "legacy_lens_file"
    CUSTOM_POST_PROCESS = "custom_post_process"
    NONE = "none"


DISTORTION_MODE: str = DistortionMode.LEGACY_LENS_FILE


# --- Asset Paths ---
ASSET_BASE_PATH = "/Game/PostRender"  # Base path in Content Browser

# --- Lens File ---
# Focal length sampling: group distortion data by focal length
# Tolerance for grouping: focal lengths within this range (mm) are same group
FOCAL_LENGTH_GROUP_TOLERANCE_MM = 0.1

# --- Validation ---
FOV_ERROR_THRESHOLD_DEG = 0.05  # Warn if FOV error exceeds this
POSITION_JUMP_THRESHOLD_CM = 50.0  # Flag frames with position jumps > this
ROTATION_JUMP_THRESHOLD_DEG = 10.0  # Flag frames with rotation jumps > this

# --- CSV Field Names ---
REQUIRED_SUFFIXES = [
    "offset.x", "offset.y", "offset.z",
    "rotation.x", "rotation.y", "rotation.z",
    "focalLengthMM", "paWidthMM", "aspectRatio",
    "k1k2k3.x", "k1k2k3.y", "k1k2k3.z",
    "centerShiftMM.x", "centerShiftMM.y",
    "aperture", "focusDistance",
    "fieldOfViewH",
]

OPTIONAL_SUFFIXES = [
    "fieldOfViewV",
    "resolution.x", "resolution.y",
    "overscan.x", "overscan.y",
    "overscanResolution.x", "overscanResolution.y",
]
