"""Centralized configuration for VP Post-Render Tool."""

# --- Coordinate Transform (Designer Y-up meters → UE Z-up centimeters) ---
# These are INITIAL GUESSES. Must be validated against real data.
# Each tuple: (source_axis_index, scale_factor)
# source_axis_index: 0=Designer.x, 1=Designer.y, 2=Designer.z
# scale_factor: includes unit conversion (×100 for m→cm) and axis flip

POSITION_MAPPING = {
    # UE axis: (Designer axis index, scale)
    "x": (2, -100.0),  # UE.X (forward) ← -Designer.Z × 100
    "y": (0, 100.0),   # UE.Y (right)   ← Designer.X × 100
    "z": (1, 100.0),   # UE.Z (up)      ← Designer.Y × 100
}

ROTATION_MAPPING = {
    # UE axis: (Designer axis index, scale)
    "pitch": (0, -1.0),  # UE Pitch ← -Designer.rotation.x
    "yaw": (1, -1.0),    # UE Yaw   ← -Designer.rotation.y
    "roll": (2, 1.0),    # UE Roll  ← Designer.rotation.z
}

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
