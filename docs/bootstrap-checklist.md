# Manual Bootstrap Checklist — BP_PostRenderToolWidget

For when `build_widget_blueprint.py` is unavailable (freshly cloned repo without rebuilt C++ module, or the helper asset is broken). Follows `bindwidget-contract.md` §5 in condensed form.

**Prefer automation when possible.** The script at `Content/Python/post_render_tool/build_widget_blueprint.py` handles everything this checklist covers, plus property application. Only fall back to this doc if the plugin hasn't been rebuilt yet.

---

## Prerequisites

- [ ] UE Editor launched, host project loaded with PostRenderTool plugin enabled
- [ ] `Content Browser → VP Post-Render Tool Content → Blueprints/` visible
- [ ] `docs/bindwidget-contract.md` open alongside (reference for 41 names)
- [ ] `docs/codebase-walkthrough.html` open at `#ui` for visual reference

---

## Phase A — Blueprint shell (2 min)

- [ ] Right-click in `Blueprints/` → Blueprint Class
- [ ] Bottom "ALL CLASSES" → search `PostRenderToolWidget`
- [ ] Select `UPostRenderToolWidget` → Select
- [ ] Name: `BP_PostRenderToolWidget` (exact)
- [ ] Double-click to open

---

## Phase B — Root panel (1 min)

- [ ] Hierarchy panel → delete default `CanvasPanel_0`
- [ ] Palette → drag `Vertical Box` to Hierarchy as new root → rename `RootPanel`

---

## Phase C — 33 required widgets (flat, fast pass; ~8 min)

Drag each widget into `RootPanel`. Names must match exactly (copy-paste from `bindwidget-contract.md` §3.1).

- [ ] `btn_recheck` — Button
- [ ] `btn_browse` — Button
- [ ] `txt_file_path` — Text Block
- [ ] `txt_frame_count` — Text Block
- [ ] `txt_focal_range` — Text Block
- [ ] `txt_timecode` — Text Block
- [ ] `txt_sensor_width` — Text Block
- [ ] `spn_fps` — Spin Box
- [ ] `txt_detected_fps` — Text Block
- [ ] `spn_frame` — Spin Box
- [ ] `txt_designer_pos` — Text Block
- [ ] `txt_designer_rot` — Text Block
- [ ] `txt_ue_pos` — Text Block
- [ ] `txt_ue_rot` — Text Block
- [ ] `btn_spawn_cam` — Button
- [ ] `cmb_pos_x_src` — Combo Box (String)
- [ ] `spn_pos_x_scale` — Spin Box
- [ ] `cmb_pos_y_src` — Combo Box (String)
- [ ] `spn_pos_y_scale` — Spin Box
- [ ] `cmb_pos_z_src` — Combo Box (String)
- [ ] `spn_pos_z_scale` — Spin Box
- [ ] `cmb_rot_pitch_src` — Combo Box (String)
- [ ] `spn_rot_pitch_scale` — Spin Box
- [ ] `cmb_rot_yaw_src` — Combo Box (String)
- [ ] `spn_rot_yaw_scale` — Spin Box
- [ ] `cmb_rot_roll_src` — Combo Box (String)
- [ ] `spn_rot_roll_scale` — Spin Box
- [ ] `btn_apply_mapping` — Button
- [ ] `btn_save_mapping` — Button
- [ ] `btn_import` — Button
- [ ] `btn_open_seq` — Button
- [ ] `btn_open_mrq` — Button
- [ ] `txt_results` — Editable Text (Multi-Line)

For each: Details panel → confirm **Is Variable** ✓ (default; do NOT uncheck).

- [ ] Compile (Ctrl+B) — must show "Compile Succeeded" with no `A required widget binding "X" of type Y was not found`
- [ ] Save (Ctrl+S)

---

## Phase D — 8 optional widgets (2 min)

All are `Text Block`:

- [ ] `prereq_label_0`
- [ ] `prereq_label_1`
- [ ] `prereq_label_2`
- [ ] `prereq_label_3`
- [ ] `prereq_label_4`
- [ ] `prereq_label_5`
- [ ] `prereq_summary`
- [ ] `txt_frame_hint`

Default Text = empty string (see `bindwidget-contract.md` §5.1 warning).

- [ ] Compile + Save

---

## Phase E — Visual layout (per Figma)

Reference: `docs/codebase-walkthrough.html#ui` (left panel mock) + `bindwidget-contract.md` §5.3–5.9 (trees).

For each Section, create this nesting in Hierarchy:

```
Border [Section card]
├─ VerticalBox
│  ├─ HorizontalBox [Header: accent + title]
│  │  ├─ SizeBox 3×13 → Image (Tint = #E8704D)
│  │  └─ TextBlock "Section title"
│  └─ <body widgets from contract>
```

**Default values** (copy into Details panel):

| Border | BrushColor = `(0.141, 0.141, 0.141, 1.0)`, Padding = `12,10,12,10` |
|---|---|
| SizeBox (accent) | W=3, H=13, Slot Padding=`0,0,8,0`, VAlign=Center |
| Image (accent) | Brush → Tint `(0.909, 0.439, 0.302, 1.0)`, Image Size `(3, 13)`, Draw As = Box |
| Section title TextBlock | Text = literal (e.g. `"CSV File"`), Slot VAlign=Center |
| Button | Slot Padding around child TextBlock = `14,6,14,6` |

- [ ] All 6 Sections have their accent stripe + title
- [ ] All contract widgets are inside their correct Section
- [ ] No widget was renamed during layout (names must match §3.1)
- [ ] Compile + Save

---

## Phase F — Submit

- [ ] Content Browser → right-click `BP_PostRenderToolWidget` → Submit (or `git add` + commit)
- [ ] Verify the `.uasset` appears in the staged files
- [ ] Commit message: `feat(bp): 手动 bootstrap BP_PostRenderToolWidget`

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `A required widget binding "X" of type Y was not found` | Missing widget / typo'd Name | Add missing widget, verify Name matches exactly |
| Widget exists but Python returns None | Unchecked `Is Variable` | Check the box, recompile |
| Tool opens blank | Root panel not compatible or BP not compiled | Phase B + Ctrl+B |
| Color looks wrong | Linear vs sRGB confusion in RGBA value | Use Linear values listed above (already converted) |

For deep debugging, see `docs/bindwidget-contract.md` §9 Failure modes.
