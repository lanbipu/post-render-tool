# Figma Design Prompt — VP Post-Render Tool

> Copy everything below into a new Claude session with Figma MCP access.

---

## Task

Use the Figma MCP (`use_figma` tool) to design a **single-page UE Editor tool panel** called "VP Post-Render Tool". This is an **Unreal Engine 5.7 Editor Utility Widget (EUW)** — a docked tool panel, not a standalone app.

**Goal**: produce one definitive Figma design baseline. All future adjustments will happen directly in UE's Widget Designer, not back in Figma. This is a one-shot design handoff.

---

## Design Specs

### Visual Style
- **Theme**: Dark — match UE5 Editor aesthetic (charcoal background, subtle borders, light text)
- **Background**: `#1A1A1A` (panel body), `#242424` (section cards)
- **Text**: `#E0E0E0` (primary), `#808080` (secondary/hints)
- **Accent color**: Teal/Cyan `#00BFA5` for primary action buttons and active states
- **Warning**: `#FF9800`, **Error**: `#F44336`, **Success**: `#4CAF50`
- **Borders**: `#333333`, 1px, rounded 4px on section cards
- **Font**: Roboto or system sans-serif, since UE uses Roboto internally

### Information Density: Standard
- Section internal padding: 12px
- Gap between sections: 8px
- Row height: 28px (for single-line controls)
- Font sizes: Title 16px, Section header 13px bold, Body 12px, Hint 11px

### Panel Dimensions
- Width: **400px** fixed (typical UE docked panel width)
- Height: scrollable (content exceeds one screen)

---

## UI Sections (top to bottom)

The panel has **6 sections**, each visually grouped as a card with a section header. Here is every control with its type, name, and purpose:

### Section 1: Prerequisites (collapsible, default collapsed)

Status checks — shows whether required UE plugins are loaded.

| # | Control | Type | Variable Name | Purpose |
|---|---------|------|---------------|---------|
| 1-6 | Status row ×6 | TextBlock | `prereq_label_0` ~ `prereq_label_5` | Shows "OK: Plugin Name" (green) or "MISSING: Plugin Name → fix hint" (red) |
| 7 | Recheck button | Button | `btn_recheck` | Re-runs all prerequisite checks |

Show placeholder content:
```
 OK: Python Editor Script Plugin
 OK: Editor Scripting Utilities
 OK: Camera Calibration
 OK: CineCameraActor
 OK: LevelSequence
 OK: EditorUtilitySubsystem
```
Use green `#4CAF50` circle indicator for OK, red `#F44336` for MISSING.

### Section 2: CSV File

File selection — user picks a Disguise Designer CSV Dense export.

| # | Control | Type | Variable Name | Purpose |
|---|---------|------|---------------|---------|
| 1 | Browse button | Button | `btn_browse` | Opens native file dialog |
| 2 | File path | TextBlock | `txt_file_path` | Displays selected file path (truncated with ellipsis if long) |

Layout: `[ Browse... ]  E:/d3 Projects/.../shot 1_take_5_dense.csv`
The Browse button is compact, file path fills remaining width.

### Section 3: CSV Preview

Parsed CSV metadata — read-only display + FPS input.

| # | Control | Type | Variable Name | Purpose |
|---|---------|------|---------------|---------|
| 1 | Frames | TextBlock | `txt_frame_count` | "Frames: 974" |
| 2 | Focal Length | TextBlock | `txt_focal_range` | "Focal Length: 30.30 - 30.30 mm" |
| 3 | Timecode | TextBlock | `txt_timecode` | "Timecode: 00:00:30.00 → 00:00:30.00" |
| 4 | Sensor Width | TextBlock | `txt_sensor_width` | "Sensor Width: 35.00 mm" |
| 5 | FPS SpinBox | SpinBox | `spn_fps` | User-editable FPS override (0 = auto-detect), range 0-120 |
| 6 | Detected FPS hint | TextBlock | `txt_detected_fps` | "Auto: 23.976 fps" or "Auto: N/A" |

Layout for FPS row: `FPS: [ 24.0 ▲▼ ]  Auto: 23.976 fps` — label, spinbox, hint on one horizontal line.

### Section 4: Coordinate Verification

Interactive frame inspector — lets user check coordinate transform before importing.

| # | Control | Type | Variable Name | Purpose |
|---|---------|------|---------------|---------|
| 1 | Frame selector | SpinBox | `spn_frame` | Pick frame index (0 ~ frame_count-1) |
| 2 | Designer Position | TextBlock | `txt_designer_pos` | "Designer Pos: (1.2345, -0.5678, 2.3456) m" |
| 3 | Designer Rotation | TextBlock | `txt_designer_rot` | "Designer Rot: (12.34, -56.78, 90.12) deg" |
| 4 | UE Position | TextBlock | `txt_ue_pos` | "UE Pos: (234.6, 123.5, -56.8) cm" |
| 5 | UE Rotation | TextBlock | `txt_ue_rot` | "UE Rot: P=-12.34  Y=56.78  R=90.12 deg" |
| 6 | Spawn Camera | Button | `btn_spawn_cam` | Spawns a test CineCameraActor at selected frame's position |

Layout for frame row: `Frame: [ 0 ▲▼ ]` — label + spinbox.
The Designer and UE coordinates should be visually paired (e.g. left/right columns or a subtle separator between "source → result").

### Section 5: Axis Mapping

6-axis remapping editor — maps Disguise (Y-up, meters) to UE (Z-up, centimeters).

**Position group** (label: "Position (m → cm)"):

| Row | Label | ComboBox Variable | SpinBox Variable | Default |
|-----|-------|-------------------|------------------|---------|
| UE.X ← | Source axis | `cmb_pos_x_src` | `spn_pos_x_scale` | Z, -100.0 |
| UE.Y ← | Source axis | `cmb_pos_y_src` | `spn_pos_y_scale` | X, 100.0 |
| UE.Z ← | Source axis | `cmb_pos_z_src` | `spn_pos_z_scale` | Y, 100.0 |

**Rotation group** (label: "Rotation (deg)"):

| Row | Label | ComboBox Variable | SpinBox Variable | Default |
|-----|-------|-------------------|------------------|---------|
| Pitch ← | Source axis | `cmb_rot_pitch_src` | `spn_rot_pitch_scale` | X, -1.0 |
| Yaw ← | Source axis | `cmb_rot_yaw_src` | `spn_rot_yaw_scale` | Y, -1.0 |
| Roll ← | Source axis | `cmb_rot_roll_src` | `spn_rot_roll_scale` | Z, 1.0 |

Each row layout: `  UE.X ←  [ Z ▾ ]  ×  [ -100.0 ▲▼ ]`
ComboBox options: "X (0)", "Y (1)", "Z (2)".

Action buttons at bottom of this section:
| # | Control | Type | Variable Name | Purpose |
|---|---------|------|---------------|---------|
| 1 | Apply Mapping | Button (secondary) | `btn_apply_mapping` | Apply to memory, refresh coordinate preview |
| 2 | Save to config.py | Button (secondary) | `btn_save_mapping` | Persist mapping to disk |

### Section 6: Actions + Results

Main pipeline actions and output log.

**Action buttons** (horizontal row):
| # | Control | Type | Variable Name | Purpose |
|---|---------|------|---------------|---------|
| 1 | Import | Button (primary, accent color) | `btn_import` | Run full pipeline: LensFile + CineCameraActor + LevelSequence |
| 2 | Open Sequencer | Button (secondary) | `btn_open_seq` | Open Sequencer editor with imported LevelSequence |
| 3 | Open MRQ | Button (secondary) | `btn_open_mrq` | Open Movie Render Queue for final render |

**Results area**:
| # | Control | Type | Variable Name | Purpose |
|---|---------|------|---------------|---------|
| 1 | Results log | MultiLineEditableText (read-only) | `txt_results` | Shows import report, errors, or status messages |

The results area should be ~120px tall with a subtle inset border, monospace or small text.

---

## Design Notes

1. **"Import" is the primary action** — make it visually prominent (accent-colored, larger than secondary buttons)
2. **Section headers** should have a thin left accent border or a subtle top-left icon to distinguish from body text
3. **SpinBox** in Figma: represent as a text input with small up/down arrows on the right side
4. **ComboBox** in Figma: represent as a dropdown with a down-arrow icon
5. **Scrollable panel**: the full content will exceed typical viewport height (~800px). Show a scrollbar indicator on the right edge
6. **No title bar**: the EUW tab already shows "EUW Post-Render Tool" in the UE tab strip, so do NOT include a redundant title at the top of the panel. Start directly with Section 1
7. **Collapsed Prerequisites**: show Section 1 in collapsed state by default (just the header with a ▶ expand arrow), since it's a one-time check

---

## Deliverable

A single Figma frame at **400 × auto-height** containing the complete panel design with all 6 sections populated with realistic sample data as described above. Use Auto Layout for all rows and sections.
