# Path C centerShift NDC-Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **User preference (memory `feedback_explicit_commit_only`):** **Do NOT auto-commit at the end of any task.** Each Stage ends with a Checkpoint that reports status only; wait for the user to explicitly say "commit" before running `git commit`. Do not pre-stage commit commands.
>
> **User preference (memory `feedback_commit_language`):** When the user does ask for a commit, the message MUST be in Chinese. Technical identifiers stay English.
>
> **User preference (memory `feedback_no_temporary_runtime_switches`):** Avoid feature-flag enums / runtime mode switches. Sweep scripts iterate via function parameters; production code commits to one chosen route. After Stage 5, X_SIGN / Y_SIGN / Y_NORMALIZER must collapse to a single hardcoded route.

**Goal:** Replace the broken `Filmback.SensorOffset = ±centerShiftMM` mapping with the official RenderStream NDC-normalized mapping (`cx_ndc = centerShiftMM / focalLengthMM`, `pixel_shift = cx_ndc × image_dim / 2`), validate it with offline simulation + UE sweep on existing D3 data, and only fall back to fresh D3 K=0 frames if simulation cannot account for the Y-axis 21 px residual.

**Architecture:** Three-tier validation. Stage 1 changes the production formula in `distortion_math.py` and updates all callsites. Stage 2 runs an offline numpy simulation that warps the existing D3 zero-anchor frame with the predicted UE displacement field and phase-correlates the result — this is the cheapest gate that decides whether the 2.36× Y-axis residual is K1 distortion coupling (acceptable) or a deeper formula gap (need fresh D3 data). Stage 3 burns 40 UE renders against existing D3 frames to confirm the formula in real UE; Stage 4 only triggers if Stage 2 or Stage 3 fails. Stage 5 toggles production projection tracks on and cleans up the sweep config knobs.

**Tech Stack:** Python 3 (`unittest`, `numpy`, `opencv-python` via `scripts/distortion_calibration/.venv`), UE 5.7 Python (`unreal`, MRQ), existing PostRenderTool plugin pipeline.

---

## File Map

| Path | Role | Status |
|---|---|---|
| `Content/Python/post_render_tool/distortion_math.py` | NDC-mapping formula + offline simulation helpers | modify |
| `Content/Python/post_render_tool/config.py` | sweep knobs (`X_SIGN` / `Y_SIGN` / `Y_NORMALIZER`) | modify |
| `Content/Python/post_render_tool/sequence_builder.py` | sequencer track writer; pass `focal_length_mm` to mapping | modify |
| `Content/Python/post_render_tool/pipeline.py` | top-level orchestrator; no signature change required (verify) | inspect |
| `Content/Python/post_render_tool/tests/test_custom_postprocess_distortion_math.py` | unit tests for new mapping | modify |
| `scripts/distortion_calibration/ue_path_c_validation/center_shift_offline_simulation.py` | offline numpy simulation + report writer | **create** |
| `scripts/distortion_calibration/ue_path_c_validation/ue_center_shift_projection_sweep.py` | UE-side sweep dispatcher; iterate sign × Y-normalizer | modify |
| `scripts/distortion_calibration/ue_path_c_validation/compare_center_shift_projection_sweep.py` | Mac-side sweep comparator; recognize v2 sweep layout | modify |
| `validation_results/path_c_d3_exports/canonical/center_shift_offline_simulation.md` | Stage 2 output report | **create** |
| `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_v2_compare.md` | Stage 3 output report | **create** |
| `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.md` | Stage 0 status rename (historical archive) | modify |
| `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.json` | Stage 0 status rename | modify |
| `validation_results/path_c_validation/path_c_validation_summary.md` | Stage 0 status row update | modify |
| `docs/distortion-investigation.md` | Stage 0 append discovery section; Stage 5 close-out | modify |
| `docs/d3-centershift-control-request.md` | Stage 4 fallback D3 render request | **create** (conditional) |

---

## Stage 0 — Status corrections (doc-only)

### Task 0.1: Rename old sweep status to historical archive

**Files:**
- Modify: `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.json`
- Modify: `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.md`

The previous sweep wrote `Filmback.SensorOffset = ±centerShiftMM` (raw mm). The RenderStream-UE source code (`RenderStreamProjectionPolicy.cpp:122-155`) shows the SDK actually expects `cx_ndc = centerShiftMM / focalLengthMM` post-multiplied into the projection matrix. The `±mm` sweep is therefore not evidence about formula failure — only about wrong input units. Rename the status so future readers don't misinterpret the artifact.

- [ ] **Step 1: Edit the JSON status field**

In `center_shift_projection_sweep_compare.json`, change the top-level `"status"` value from `"BLOCKED_FORMULA"` to `"RAW_MM_FILMBACK_SWEEP_INVALID"`. Also append to the `"reason"` field: ` (superseded by RenderStream NDC mapping discovery 2026-05-06; see docs/distortion-investigation.md).`

- [ ] **Step 2: Edit the Markdown header to match**

In `center_shift_projection_sweep_compare.md`, change the line:

```text
- Status: `BLOCKED_FORMULA`
```

to:

```text
- Status: `RAW_MM_FILMBACK_SWEEP_INVALID`
- Note: This sweep wrote `Filmback.SensorOffset = ±centerShiftMM` (raw mm). RenderStream-UE source (`RenderStreamProjectionPolicy.cpp:122-155`) shows the correct mapping is `cx_ndc = centerShiftMM / focalLengthMM`; this sweep's residuals do not represent formula failure, only wrong input units. Superseded by `center_shift_projection_sweep_v2_compare.md`.
```

- [ ] **Step 3: Verify both files still parse**

Run:

```bash
python -c "import json; json.load(open('validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.json'))"
```

Expected: no exception, no output.

### Task 0.2: Append discovery section to investigation doc

**Files:**
- Modify: `docs/distortion-investigation.md` (append a new section at the end)

- [ ] **Step 1: Append the section**

Append the following block to `docs/distortion-investigation.md`:

```markdown
## 2026-05-06 — RenderStream NDC mapping discovery

Tier 0' web research on `disguise-one/RenderStream` and `disguise-one/RenderStream-UE`
public repositories yielded the official `centerShiftMM` semantics. The CSV column is
labelled "MM" but D3's RenderStream layer transmits it pre-divided by focal length:

- SDK header (`d3renderstream.h:78-87`): `CameraData` declares `float cx, cy;` with no unit doc.
- Reference projection sample (`Textures.cpp:455-489`): the projection matrix is built with
  `XMMatrixPerspectiveOffCenterLH(...)`, then post-multiplied by
  `XMMatrixTranslation(cx, cy, 0.f)`. `cx` and `cy` are NDC clip-space translations —
  one NDC half-width equals one unit, mapping to `image_dim / 2` pixels.
- UE consumer (`RenderStreamProjectionPolicy.cpp:122-155`): same NDC translation, with
  `clippingScale.Y = -1.f / (T - B)` flipping Y to match UE screen-down convention.

Resulting mapping (verified against existing D3 X-axis data: `cx = 0.5/30.302 = 0.0165`,
predicted shift `0.0165 × 1920/2 = 15.84 px`, measured `16.05 px`, < 1% residual):

```
cx_ndc = centerShiftMM.x / focalLengthMM
cy_ndc = centerShiftMM.y / focalLengthMM
pixel_shift_x = cx_ndc * image_width  / 2
pixel_shift_y = cy_ndc * image_height / 2 * (-1)   # NDC +Y up vs UE screen +Y down
```

UE Filmback equivalent (since UE's `Filmback.SensorOffset` is internally scaled by
`image_dim / sensor_dim`):

```
sensor_horizontal_offset_mm = cx_ndc * sensor_width_mm  / 2
sensor_vertical_offset_mm   = cy_ndc * sensor_height_mm / 2 * (-1)
```

Y-axis 2.36× residual (D3 measures 21.21 px vs prediction 8.91 px) is unresolved.
Two candidate explanations:

1. K1=0.5 distortion coupling: the radial distortion field is anisotropic
   (`r = (d.x, d.y/aspect)`), and shifting the radial centre amplifies Y phase shift
   beyond the pure NDC-projection translation. Stage 2 offline numpy simulation tests this.
2. D3 uses `sensor_width_mm/2` as the Y normalizer instead of `sensor_height_mm/2`.
   This gives 15.84 px (closer but still off). Stage 3 sweep tests both candidates.

If neither explains 21 px, Stage 4 fallback requests fresh K=0 control frames from D3.

Implementation plan: `docs/superpowers/plans/2026-05-06-centershift-ndc-mapping.md`.
```

### Task 0.3: Update validation summary status row

**Files:**
- Modify: `validation_results/path_c_validation/path_c_validation_summary.md`

- [ ] **Step 1: Update the gate row**

Find the row:

```text
| centerShift projection sign sweep | BLOCKED_FORMULA | ... |
```

Replace with:

```text
| centerShift projection sign sweep (raw-mm v1) | RAW_MM_FILMBACK_SWEEP_INVALID | `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_dispatch.json`, `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.json`, `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_compare.md` |
| centerShift projection sign sweep (NDC v2) | PENDING | `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_v2_compare.md` (TBD via Stage 3) |
```

### Stage 0 Checkpoint

Files changed: 4. No code, no tests. Report status: "Stage 0 complete. Old sweep marked invalid, discovery doc appended, summary row split into v1 (archived) + v2 (pending)." Wait for user instruction before committing.

---

## Stage 1 — Implement NDC-mapping formula

### Task 1.1: Add failing test for new mapping signature

**Files:**
- Modify: `Content/Python/post_render_tool/tests/test_custom_postprocess_distortion_math.py`

The current `test_center_shift_projection_mapping_35mm_16x9` test asserts `sensor_horizontal_offset_mm = ±0.5` (raw mm pass-through). This is the wrong formula. Replace with NDC-derived expectations using the SDK formula at focal=30.302mm.

- [ ] **Step 1: Replace the existing centerShift mapping tests**

Replace lines 144-178 of `Content/Python/post_render_tool/tests/test_custom_postprocess_distortion_math.py` with:

```python
    def test_center_shift_projection_mapping_ndc_focal30p302(self):
        """NDC-mapping per RenderStream SDK: cx_ndc = mm/focal, then × sensor_dim/2.

        For focal=30.302mm, sensor=35mm × 19.687mm, ±0.5mm shift:
            cx_ndc = 0.5 / 30.302 = 0.016501... (NDC half-width units)
            sensor_h_offset = cx_ndc × 35 / 2 = 0.288767... mm
            sensor_v_offset = cy_ndc × 19.687 / 2 × (-1) = -0.162456... mm
                              (Y flip: NDC +Y up vs UE screen +Y down)

        UE internally maps SensorOffset by image_dim / sensor_dim →
            X pixel shift = 0.288767 × 1920 / 35 = 15.844 px (matches D3's 16.05 px ✓)
            Y pixel shift = -0.162456 × 1080 / 19.687 = -8.913 px (D3 21.21; residual analysed in Stage 2)
        """
        mapping = map_center_shift_projection(
            center_shift_x_mm=0.5,
            center_shift_y_mm=0.5,
            sensor_width_mm=35.0,
            aspect=ASPECT_16_9,
            focal_length_mm=30.302,
        )
        self.assertAlmostEqual(mapping.center_u, 0.5142857142857142, places=7)
        self.assertAlmostEqual(mapping.center_v, 0.5253968253968254, places=7)
        self.assertAlmostEqual(
            mapping.sensor_horizontal_offset_mm,
            config.CENTER_SHIFT_PROJECTION_X_SIGN * 0.28876641145,
            places=7,
        )
        self.assertAlmostEqual(
            mapping.sensor_vertical_offset_mm,
            config.CENTER_SHIFT_PROJECTION_Y_SIGN * 0.16245628095,
            places=7,
        )

    def test_center_shift_projection_mapping_ndc_isotropic_y(self):
        """Sweep candidate: Y normalizer = sensor_width_mm/2 (isotropic in NDC half-width).

        Stage 3 sweep iterates both this and the default sensor_height_mm/2.
        For focal=30.302mm, sensor=35mm × 19.687mm, ±0.5mm shift:
            sensor_v_offset_isotropic = cy_ndc × 35 / 2 × (-1) = -0.288767... mm
            Y pixel shift = -0.288767 × 1080 / 19.687 = -15.84 px
        """
        mapping = map_center_shift_projection(
            center_shift_x_mm=0.5,
            center_shift_y_mm=0.5,
            sensor_width_mm=35.0,
            aspect=ASPECT_16_9,
            focal_length_mm=30.302,
            y_normalizer="sensor_width",
        )
        self.assertAlmostEqual(
            mapping.sensor_vertical_offset_mm,
            config.CENTER_SHIFT_PROJECTION_Y_SIGN * 0.28876641145,
            places=7,
        )

    def test_center_shift_projection_mapping_zero_shift_returns_zero_offsets(self):
        """centerShift = (0, 0) must produce zero sensor offsets and centered UV."""
        mapping = map_center_shift_projection(
            center_shift_x_mm=0.0,
            center_shift_y_mm=0.0,
            sensor_width_mm=35.0,
            aspect=ASPECT_16_9,
            focal_length_mm=30.302,
        )
        self.assertAlmostEqual(mapping.center_u, 0.5, places=10)
        self.assertAlmostEqual(mapping.center_v, 0.5, places=10)
        self.assertAlmostEqual(mapping.sensor_horizontal_offset_mm, 0.0, places=10)
        self.assertAlmostEqual(mapping.sensor_vertical_offset_mm, 0.0, places=10)

    def test_center_shift_projection_mapping_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            map_center_shift_projection(
                center_shift_x_mm=0.0,
                center_shift_y_mm=0.0,
                sensor_width_mm=0.0,
                aspect=ASPECT_16_9,
                focal_length_mm=30.302,
            )
        with self.assertRaises(ValueError):
            map_center_shift_projection(
                center_shift_x_mm=0.0,
                center_shift_y_mm=0.0,
                sensor_width_mm=35.0,
                aspect=0.0,
                focal_length_mm=30.302,
            )
        with self.assertRaises(ValueError):
            map_center_shift_projection(
                center_shift_x_mm=0.0,
                center_shift_y_mm=0.0,
                sensor_width_mm=35.0,
                aspect=ASPECT_16_9,
                focal_length_mm=0.0,
            )
        with self.assertRaises(ValueError):
            map_center_shift_projection(
                center_shift_x_mm=0.0,
                center_shift_y_mm=0.0,
                sensor_width_mm=35.0,
                aspect=ASPECT_16_9,
                focal_length_mm=30.302,
                y_normalizer="garbage",
            )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd Content/Python && python -m unittest post_render_tool.tests.test_custom_postprocess_distortion_math.TestK1RadialDisplacement -v
```

Expected: `TypeError: map_center_shift_projection() got an unexpected keyword argument 'focal_length_mm'` on every new test (because the implementation hasn't grown the new parameter yet).

### Task 1.2: Implement new `map_center_shift_projection` signature + formula

**Files:**
- Modify: `Content/Python/post_render_tool/distortion_math.py:175-211`

- [ ] **Step 1: Replace the function body**

Replace the existing `map_center_shift_projection` (lines 175-211 of `distortion_math.py`) with:

```python
def map_center_shift_projection(
    *,
    center_shift_x_mm: float,
    center_shift_y_mm: float,
    sensor_width_mm: float,
    aspect: float,
    focal_length_mm: float,
    x_sign: float | None = None,
    y_sign: float | None = None,
    y_normalizer: str = "sensor_height",
) -> CenterShiftProjectionMapping:
    """Map D3 ``centerShiftMM`` to UE projection offset plus material center.

    Per RenderStream SDK (``Textures.cpp:455-489``), the CSV ``centerShiftMM``
    column is converted to NDC clip-space units before being post-multiplied
    into the projection matrix:

        cx_ndc = centerShiftMM.x / focalLengthMM
        cy_ndc = centerShiftMM.y / focalLengthMM

    UE's ``Filmback.SensorHorizontalOffset`` is in mm and internally scaled by
    ``image_width / sensor_width`` to produce a pixel shift, so we convert the
    NDC value to an equivalent mm value via:

        sensor_h_offset_mm = cx_ndc * sensor_width_mm  / 2
        sensor_v_offset_mm = cy_ndc * y_norm_mm        / 2 * (Y_SIGN: NDC↑ → screen↓)

    ``y_normalizer`` selects between two unresolved candidates (Stage 3 sweep):

    - ``"sensor_height"``: ``y_norm_mm = sensor_width_mm / aspect`` (anisotropic
      in image space, follows X axis convention scaled by aspect).
    - ``"sensor_width"``: ``y_norm_mm = sensor_width_mm`` (isotropic in NDC
      half-width units).

    ``CenterUV`` continues to track the radial distortion centre using the
    physical sensor dimensions, since the post-process material's ``CenterUV``
    parameter lives in normalized output UV space, not NDC.
    """
    if sensor_width_mm == 0:
        raise ValueError("sensor_width_mm must be non-zero")
    if aspect == 0:
        raise ValueError("aspect must be non-zero")
    if focal_length_mm == 0:
        raise ValueError("focal_length_mm must be non-zero")
    if y_normalizer not in ("sensor_height", "sensor_width"):
        raise ValueError(
            f"y_normalizer must be 'sensor_height' or 'sensor_width', got {y_normalizer!r}"
        )

    sensor_height_mm = sensor_width_mm / aspect
    resolved_x_sign = (
        config.CENTER_SHIFT_PROJECTION_X_SIGN if x_sign is None else x_sign
    )
    resolved_y_sign = (
        config.CENTER_SHIFT_PROJECTION_Y_SIGN if y_sign is None else y_sign
    )

    cx_ndc = center_shift_x_mm / focal_length_mm
    cy_ndc = center_shift_y_mm / focal_length_mm
    y_norm_mm = sensor_height_mm if y_normalizer == "sensor_height" else sensor_width_mm

    return CenterShiftProjectionMapping(
        center_u=0.5 + center_shift_x_mm / sensor_width_mm,
        center_v=0.5 + center_shift_y_mm / sensor_height_mm,
        sensor_horizontal_offset_mm=resolved_x_sign * cx_ndc * (sensor_width_mm / 2.0),
        sensor_vertical_offset_mm=resolved_y_sign * cy_ndc * (y_norm_mm / 2.0),
        sensor_height_mm=sensor_height_mm,
    )
```

- [ ] **Step 2: Run the tests to verify they pass**

Run:

```bash
cd Content/Python && python -m unittest post_render_tool.tests.test_custom_postprocess_distortion_math.TestK1RadialDisplacement -v
```

Expected: all 4 new tests pass; the existing K1/K2/K3/identity tests continue to pass.

- [ ] **Step 3: Run the full test module to catch regressions**

Run:

```bash
cd Content/Python && python -m unittest post_render_tool.tests.test_custom_postprocess_distortion_math -v
```

Expected: every test passes. If any earlier test fails, do NOT proceed — re-read the failure and fix it before continuing.

### Task 1.3: Update `sequence_builder` callsite

**Files:**
- Modify: `Content/Python/post_render_tool/sequence_builder.py:342-347`

- [ ] **Step 1: Update the callsite to pass `focal_length_mm`**

Replace lines 342-347 of `sequence_builder.py`:

```python
        center_shift = map_center_shift_projection(
            center_shift_x_mm=frame.center_shift_x_mm,
            center_shift_y_mm=frame.center_shift_y_mm,
            sensor_width_mm=frame.sensor_width_mm,
            aspect=frame.aspect_ratio,
            focal_length_mm=frame.focal_length_mm,
        )
```

- [ ] **Step 2: AST-parse to confirm syntax**

Run:

```bash
python3 -c "import ast; ast.parse(open('Content/Python/post_render_tool/sequence_builder.py').read()); print('OK')"
```

Expected: `OK`.

### Task 1.4: Inspect `pipeline.py` for indirect callsites

**Files:**
- Inspect: `Content/Python/post_render_tool/pipeline.py`

- [ ] **Step 1: Confirm `pipeline.py` does not call `map_center_shift_projection` directly**

Run:

```bash
grep -n "map_center_shift_projection" Content/Python/post_render_tool/pipeline.py || echo "no direct callsite"
```

Expected: `no direct callsite`. If a callsite is found, update it the same way as `sequence_builder.py` (Task 1.3) before proceeding.

### Task 1.5: Update sweep dispatcher to pass `focal_length_mm` and `y_normalizer`

**Files:**
- Modify: `scripts/distortion_calibration/ue_path_c_validation/ue_center_shift_projection_sweep.py:43-48` (sweep config), `:264-310` (loop body)

The sweep currently iterates 4 sign pairs (xp_yp / xp_yn / xn_yp / xn_yn). Add a Y_NORMALIZER dimension so it iterates 4 signs × 2 normalizers = 8 configs. Each config still imports the same 5 centerShift CSVs and dispatches one MRQ render per case = 40 frames total.

- [ ] **Step 1: Replace `SIGN_SWEEPS` with the expanded matrix**

Replace lines 43-48 of `ue_center_shift_projection_sweep.py`:

```python
SIGN_SWEEPS = (
    # (sweep_id, x_sign, y_sign, y_normalizer)
    ("xp_yp_height",  1.0,  1.0, "sensor_height"),
    ("xp_yn_height",  1.0, -1.0, "sensor_height"),
    ("xn_yp_height", -1.0,  1.0, "sensor_height"),
    ("xn_yn_height", -1.0, -1.0, "sensor_height"),
    ("xp_yp_width",   1.0,  1.0, "sensor_width"),
    ("xp_yn_width",   1.0, -1.0, "sensor_width"),
    ("xn_yp_width",  -1.0,  1.0, "sensor_width"),
    ("xn_yn_width",  -1.0, -1.0, "sensor_width"),
)
```

- [ ] **Step 2: Update the loop unpacking**

Find the sweep loop body (around line 272 in the current file: `for sign_id, x_sign, y_sign in SIGN_SWEEPS:`). Replace with:

```python
            for sign_id, x_sign, y_sign, y_norm in SIGN_SWEEPS:
                prt_config.ASSET_BASE_PATH = f"{IMPORT_ROOT}/{sign_id}"
                prt_config.CENTER_SHIFT_ENABLE_PROJECTION_TRACKS = True
                prt_config.CENTER_SHIFT_PROJECTION_X_SIGN = x_sign
                prt_config.CENTER_SHIFT_PROJECTION_Y_SIGN = y_sign
                prt_config.CENTER_SHIFT_PROJECTION_Y_NORMALIZER = y_norm
```

- [ ] **Step 3: Update the report `sign_sweeps` field shape**

In `report["sign_sweeps"]` initialization (around line 242), change to:

```python
        "sign_sweeps": [
            {"id": sid, "x_sign": xs, "y_sign": ys, "y_normalizer": yn}
            for sid, xs, ys, yn in SIGN_SWEEPS
        ],
```

Update the `report["imports"]` `item` dict (around line 282) to include `"y_normalizer": y_norm,` and update `report["jobs"]` similarly.

- [ ] **Step 4: AST-parse to confirm syntax**

Run:

```bash
python3 -c "import ast; ast.parse(open('scripts/distortion_calibration/ue_path_c_validation/ue_center_shift_projection_sweep.py').read()); print('OK')"
```

Expected: `OK`.

### Task 1.6: Add `Y_NORMALIZER` to config

**Files:**
- Modify: `Content/Python/post_render_tool/config.py:46-50`

The sweep dispatcher (Task 1.5) reads `config.CENTER_SHIFT_PROJECTION_Y_NORMALIZER` — declare it.

- [ ] **Step 1: Append the config knob**

After the existing `CENTER_SHIFT_PROJECTION_Y_SIGN = -1.0` line in `config.py`, add:

```python
# Stage 3 sweep dimension. Fixed to "sensor_height" in production until the
# Stage 3 gate picks a winner (memory: feedback_no_temporary_runtime_switches —
# this knob must collapse to a hardcoded value at Stage 5 close-out).
CENTER_SHIFT_PROJECTION_Y_NORMALIZER = "sensor_height"
```

- [ ] **Step 2: Update `map_center_shift_projection` to read from config when arg is `None`**

Modify the resolution block in `distortion_math.py` (the body inserted in Task 1.2) so `y_normalizer` defaults via config when the caller passes the sentinel:

Replace this section in the new function body:

```python
    if y_normalizer not in ("sensor_height", "sensor_width"):
        raise ValueError(
            f"y_normalizer must be 'sensor_height' or 'sensor_width', got {y_normalizer!r}"
        )
```

with:

```python
    resolved_y_normalizer = (
        config.CENTER_SHIFT_PROJECTION_Y_NORMALIZER
        if y_normalizer is None
        else y_normalizer
    )
    if resolved_y_normalizer not in ("sensor_height", "sensor_width"):
        raise ValueError(
            "y_normalizer must be 'sensor_height' or 'sensor_width', "
            f"got {resolved_y_normalizer!r}"
        )
```

And change the function signature line:

```python
    y_normalizer: str = "sensor_height",
```

to:

```python
    y_normalizer: str | None = None,
```

And replace the line:

```python
    y_norm_mm = sensor_height_mm if y_normalizer == "sensor_height" else sensor_width_mm
```

with:

```python
    y_norm_mm = sensor_height_mm if resolved_y_normalizer == "sensor_height" else sensor_width_mm
```

- [ ] **Step 3: Run all tests**

Run:

```bash
cd Content/Python && python -m unittest post_render_tool.tests.test_custom_postprocess_distortion_math -v
```

Expected: all tests pass (the explicit `y_normalizer="sensor_width"` test still works because explicit values bypass the `None`-default path).

### Stage 1 Checkpoint

Files changed: `distortion_math.py`, `config.py`, `sequence_builder.py`, `tests/test_custom_postprocess_distortion_math.py`, `ue_path_c_validation/ue_center_shift_projection_sweep.py`. Tests pass. Report status: "Stage 1 complete. NDC-mapping formula in place. Sweep dispatcher ready for 8 configs. Awaiting Stage 2 simulation result before running UE renders." Wait for user instruction before committing.

---

## Stage 2 — Offline numpy phase-shift simulation

### Task 2.1: Create offline simulation script skeleton

**Files:**
- Create: `scripts/distortion_calibration/ue_path_c_validation/center_shift_offline_simulation.py`

Decision gate: is the 21 px Y-axis residual produced by K1=0.5 distortion coupling (acceptable), or by something else (need fresh D3 frames)? Build a numpy simulation that warps the existing D3 zero-anchor PNG with the predicted UE displacement field, phase-correlates against the original, and reports (predicted_x_px, predicted_y_px) for 8 cases (K1=0 vs K1=0.5) × (centerShiftMM = ±0.5 X / Y).

- [ ] **Step 1: Create the skeleton + CLI args**

Create `scripts/distortion_calibration/ue_path_c_validation/center_shift_offline_simulation.py`:

```python
"""Offline numpy simulation of UE Path C centerShift behavior.

Warps the existing D3 zero-anchor frame with the predicted UE displacement
field for 8 cases (K1=0 vs K1=0.5) × (centerShiftMM ∈ ±0.5 X/Y), then
phase-correlates each warped image against the zero-anchor to predict the
global pixel shift UE will produce.

Decision rule: if predicted Y phase shift at K1=0.5 ≈ 21 px (matches D3
measurement), the residual is K1 distortion coupling and Stage 3 UE sweep
is the next step. Otherwise Stage 4 fresh D3 K=0 frames are required.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# Allow running from repo root: scripts/distortion_calibration/ue_path_c_validation/...
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Content" / "Python"))

from post_render_tool.distortion_math import (  # noqa: E402
    map_center_shift_projection,
    official_sensor_inverse_uv,
)


# Camera params for centerShift Group B (matches existing D3 frames):
SENSOR_WIDTH_MM = 35.0
ASPECT = 1.77779
FOCAL_LENGTH_MM = 30.302
IMAGE_W = 1920
IMAGE_H = 1080

ANCHOR_PATH = Path(
    "validation_results/path_c_d3_exports/canonical/center_shift/"
    "path_c_center_k1_p0p5_shift_zero.png"
)

CASES = (
    # (case_id, K1, center_shift_x_mm, center_shift_y_mm)
    ("k_zero_shiftx_n0p5", 0.0, -0.5,  0.0),
    ("k_zero_shiftx_p0p5", 0.0,  0.5,  0.0),
    ("k_zero_shifty_n0p5", 0.0,  0.0, -0.5),
    ("k_zero_shifty_p0p5", 0.0,  0.0,  0.5),
    ("k1_p0p5_shiftx_n0p5", 0.5, -0.5,  0.0),
    ("k1_p0p5_shiftx_p0p5", 0.5,  0.5,  0.0),
    ("k1_p0p5_shifty_n0p5", 0.5,  0.0, -0.5),
    ("k1_p0p5_shifty_p0p5", 0.5,  0.0,  0.5),
)


def _load_anchor(anchor_path: Path) -> np.ndarray:
    import cv2
    image = cv2.imread(str(anchor_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FileNotFoundError(f"missing anchor: {anchor_path}")
    if image.ndim == 3:
        if image.shape[2] == 4:
            image = image[:, :, :3]
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if np.issubdtype(image.dtype, np.integer):
        image = image.astype(np.float32) / float(np.iinfo(image.dtype).max)
    else:
        image = image.astype(np.float32)
    return image


def _phase_correlate(anchor: np.ndarray, warped: np.ndarray) -> tuple[float, float, float]:
    import cv2
    (shift_x, shift_y), response = cv2.phaseCorrelate(anchor, warped)
    return float(shift_x), float(shift_y), float(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", type=Path, default=ANCHOR_PATH)
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path(
            "validation_results/path_c_d3_exports/canonical/"
            "center_shift_offline_simulation.md"
        ),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(
            "validation_results/path_c_d3_exports/canonical/"
            "center_shift_offline_simulation.json"
        ),
    )
    parser.add_argument(
        "--y-normalizer",
        choices=("sensor_height", "sensor_width"),
        default="sensor_height",
    )
    args = parser.parse_args()

    anchor = _load_anchor(args.anchor)
    if anchor.shape != (IMAGE_H, IMAGE_W):
        raise SystemExit(
            f"anchor shape {anchor.shape} != expected ({IMAGE_H}, {IMAGE_W})"
        )

    results = []
    for case_id, k1, shift_x_mm, shift_y_mm in CASES:
        warped = _warp_anchor(
            anchor, k1=k1, shift_x_mm=shift_x_mm, shift_y_mm=shift_y_mm,
            y_normalizer=args.y_normalizer,
        )
        px_x, px_y, response = _phase_correlate(anchor, warped)
        results.append({
            "case_id": case_id,
            "k1": k1,
            "shift_x_mm": shift_x_mm,
            "shift_y_mm": shift_y_mm,
            "predicted_shift_x_px": px_x,
            "predicted_shift_y_px": px_y,
            "phase_response": response,
        })

    _write_reports(results, args.output_md, args.output_json, args.y_normalizer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify the skeleton parses**

Run:

```bash
python3 -c "import ast; ast.parse(open('scripts/distortion_calibration/ue_path_c_validation/center_shift_offline_simulation.py').read()); print('OK')"
```

Expected: `OK`. (The script is not yet executable because `_warp_anchor` and `_write_reports` are missing — Task 2.2 fills them in.)

### Task 2.2: Implement displacement-field warping

**Files:**
- Modify: `scripts/distortion_calibration/ue_path_c_validation/center_shift_offline_simulation.py`

- [ ] **Step 1: Insert `_warp_anchor` above `main`**

Insert before `def main()`:

```python
def _warp_anchor(
    anchor: np.ndarray,
    *,
    k1: float,
    shift_x_mm: float,
    shift_y_mm: float,
    y_normalizer: str,
) -> np.ndarray:
    """Warp the anchor frame with the predicted UE Path C displacement field.

    UE pipeline being simulated:
      1. CineCamera projects with shifted principal point (NDC translation
         post-projection). For an output pixel (u, v), the corresponding
         input world point lands at (u - cx_ndc * image_w/2, v - cy_ndc * image_h/2 * y_sign)
         in the unshifted projection's pixel space.
      2. Post-process material `official_sensor_inverse_uv` re-samples around
         CenterUV = (0.5 + shift_x/sensor_w, 0.5 + shift_y/sensor_h).

    The combined displacement is the sample-source UV. This function builds
    a (h, w, 2) source-pixel map and uses cv2.remap to produce the warped image.
    """
    import cv2

    mapping = map_center_shift_projection(
        center_shift_x_mm=shift_x_mm,
        center_shift_y_mm=shift_y_mm,
        sensor_width_mm=SENSOR_WIDTH_MM,
        aspect=ASPECT,
        focal_length_mm=FOCAL_LENGTH_MM,
        x_sign=1.0,   # offline sim assumes UE +X = D3 +X (verified Stage 3)
        y_sign=-1.0,  # NDC +Y up vs UE screen +Y down
        y_normalizer=y_normalizer,
    )

    h, w = anchor.shape
    # Output pixel grid → output UV in [0, 1]
    out_u = (np.arange(w, dtype=np.float64) + 0.5) / w
    out_v = (np.arange(h, dtype=np.float64) + 0.5) / h
    grid_u, grid_v = np.meshgrid(out_u, out_v)

    # Step A: NDC projection translation. UE Filmback offset (mm) → pixel
    # offset = (offset_mm * image_dim / sensor_dim). Convert that pixel
    # offset to UV by dividing by image dim.
    sensor_h_mm = SENSOR_WIDTH_MM / ASPECT
    pixel_dx = mapping.sensor_horizontal_offset_mm * (w / SENSOR_WIDTH_MM)
    pixel_dy = mapping.sensor_vertical_offset_mm   * (h / sensor_h_mm)
    uv_dx = pixel_dx / w
    uv_dy = pixel_dy / h

    # The output pixel that *would* have been (u, v) in the unshifted
    # projection now corresponds to source UV (u - uv_dx, v - uv_dy) in the
    # pre-shift projection — pull that back through the radial distortion.
    pre_shift_u = grid_u - uv_dx
    pre_shift_v = grid_v - uv_dy

    # Step B: post-process material radial distortion around CenterUV.
    # official_sensor_inverse_uv is scalar; vectorize manually.
    cu, cv = mapping.center_u, mapping.center_v
    dx = pre_shift_u - cu
    dy = pre_shift_v - cv
    rx = dx
    ry = dy / ASPECT
    r2 = rx * rx + ry * ry
    factor = k1 * r2  # K2 = K3 = 0 for all simulation cases
    src_u = pre_shift_u + factor * dx
    src_v = pre_shift_v + factor * dy

    # Convert back to pixel coordinates for cv2.remap.
    src_x = (src_u * w - 0.5).astype(np.float32)
    src_y = (src_v * h - 0.5).astype(np.float32)
    warped = cv2.remap(
        anchor,
        src_x,
        src_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return warped
```

- [ ] **Step 2: Insert `_write_reports` above `main`**

Insert before `def main()` (after `_warp_anchor`):

```python
def _write_reports(
    results: list[dict],
    output_md: Path,
    output_json: Path,
    y_normalizer: str,
) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(
            {"y_normalizer": y_normalizer, "cases": results},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    lines = [
        "# Path C centerShift Offline Numpy Simulation",
        "",
        f"- y_normalizer: `{y_normalizer}`",
        f"- anchor: `{ANCHOR_PATH}`",
        f"- focal_length_mm: `{FOCAL_LENGTH_MM}`",
        f"- sensor_width_mm: `{SENSOR_WIDTH_MM}`",
        f"- image: `{IMAGE_W} x {IMAGE_H}`",
        "",
        "## Predicted UE Phase Shift vs D3 Measurement",
        "",
        "| case | K1 | shift_mm | predicted_x_px | predicted_y_px | response |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for r in results:
        shift = f"({r['shift_x_mm']:+.1f}, {r['shift_y_mm']:+.1f})"
        lines.append(
            "| `{cid}` | {k1:.1f} | {shift} | {x:+.3f} | {y:+.3f} | {resp:.3f} |".format(
                cid=r["case_id"],
                k1=r["k1"],
                shift=shift,
                x=r["predicted_shift_x_px"],
                y=r["predicted_shift_y_px"],
                resp=r["phase_response"],
            )
        )
    lines.extend([
        "",
        "## Decision Rule",
        "",
        "- If `k1_p0p5_shifty_n0p5` predicted_y_px ≈ +21 px (and `..._shifty_p0p5` ≈ -21 px):",
        "  21 px residual is K1 distortion coupling. Proceed to Stage 3 UE sweep.",
        "- If `k1_p0p5_shifty_*` predicted_y_px stays near ±9 px (sensor_height)",
        "  or ±16 px (sensor_width): formula has an unmodeled gap.",
        "  Skip Stage 3, proceed directly to Stage 4 D3 K=0 control frames.",
    ])
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines), encoding="utf-8")
```

- [ ] **Step 3: Verify the script parses**

Run:

```bash
python3 -c "import ast; ast.parse(open('scripts/distortion_calibration/ue_path_c_validation/center_shift_offline_simulation.py').read()); print('OK')"
```

Expected: `OK`.

### Task 2.3: Run the simulation

**Files:**
- Output: `validation_results/path_c_d3_exports/canonical/center_shift_offline_simulation.md`
- Output: `validation_results/path_c_d3_exports/canonical/center_shift_offline_simulation.json`

- [ ] **Step 1: Run with default `y_normalizer=sensor_height`**

Run from repo root:

```bash
scripts/distortion_calibration/.venv/bin/python \
  scripts/distortion_calibration/ue_path_c_validation/center_shift_offline_simulation.py
```

Expected: exit 0, two output files created.

- [ ] **Step 2: Run again with `y_normalizer=sensor_width` to populate both candidates**

Run:

```bash
scripts/distortion_calibration/.venv/bin/python \
  scripts/distortion_calibration/ue_path_c_validation/center_shift_offline_simulation.py \
  --y-normalizer sensor_width \
  --output-md validation_results/path_c_d3_exports/canonical/center_shift_offline_simulation_isotropic.md \
  --output-json validation_results/path_c_d3_exports/canonical/center_shift_offline_simulation_isotropic.json
```

Expected: exit 0.

- [ ] **Step 3: Inspect both reports and apply the decision rule**

Read both `center_shift_offline_simulation.md` and `center_shift_offline_simulation_isotropic.md`. Apply the rule documented at the bottom of each report:

- **If either normalizer's `k1_p0p5_shifty_*` rows produce |predicted_y_px| ≥ 18 px** → proceed to Stage 3.
- **If both normalizers cap out near 9 px or 16 px** → skip Stage 3, proceed directly to Stage 4.

Record the decision in a new section appended to `docs/distortion-investigation.md`:

```markdown
### 2026-05-06 Stage 2 simulation result

- y_normalizer=sensor_height: predicted_y_px @ K1=0.5 = ±X.XXX (replace with actual)
- y_normalizer=sensor_width:  predicted_y_px @ K1=0.5 = ±Y.YYY (replace with actual)
- Decision: <Stage 3 | Stage 4>
- Reason: <one-sentence justification>
```

### Stage 2 Checkpoint

Files changed: 1 created (`center_shift_offline_simulation.py`), 4 generated (`*.md` × 2, `*.json` × 2), 1 modified (`distortion-investigation.md` decision section). Report status: "Stage 2 complete. Decision: <Stage 3 | Stage 4>." Wait for user instruction before committing or proceeding.

---

## Stage 3 — UE sweep with NDC mapping (8 configs × 5 frames)

**Precondition:** Stage 2 decision = "Stage 3". Skip this stage if decision = "Stage 4".

### Task 3.1: Update sweep comparator to recognize 8-config layout

**Files:**
- Modify: `scripts/distortion_calibration/ue_path_c_validation/compare_center_shift_projection_sweep.py:26-31` (SIGN_SWEEPS dict)

- [ ] **Step 1: Replace the SIGN_SWEEPS dict**

Replace the existing block:

```python
SIGN_SWEEPS = {
    "xp_yp": {"x_sign": 1.0, "y_sign": 1.0},
    "xp_yn": {"x_sign": 1.0, "y_sign": -1.0},
    "xn_yp": {"x_sign": -1.0, "y_sign": 1.0},
    "xn_yn": {"x_sign": -1.0, "y_sign": -1.0},
}
```

with:

```python
SIGN_SWEEPS = {
    "xp_yp_height":  {"x_sign":  1.0, "y_sign":  1.0, "y_normalizer": "sensor_height"},
    "xp_yn_height":  {"x_sign":  1.0, "y_sign": -1.0, "y_normalizer": "sensor_height"},
    "xn_yp_height":  {"x_sign": -1.0, "y_sign":  1.0, "y_normalizer": "sensor_height"},
    "xn_yn_height":  {"x_sign": -1.0, "y_sign": -1.0, "y_normalizer": "sensor_height"},
    "xp_yp_width":   {"x_sign":  1.0, "y_sign":  1.0, "y_normalizer": "sensor_width"},
    "xp_yn_width":   {"x_sign":  1.0, "y_sign": -1.0, "y_normalizer": "sensor_width"},
    "xn_yp_width":   {"x_sign": -1.0, "y_sign":  1.0, "y_normalizer": "sensor_width"},
    "xn_yn_width":   {"x_sign": -1.0, "y_sign": -1.0, "y_normalizer": "sensor_width"},
}
```

- [ ] **Step 2: Update report-writer keys**

In `compare_center_shift_projection_sweep.py`, find every `sign_info["x_sign"]` / `sign_info["y_sign"]` reference and add a parallel `sign_info["y_normalizer"]` field write into:
- `payload["sign_results"][i]` (around line 246: append `"y_normalizer": sign_info["y_normalizer"]`)
- `_write_reports` Sign Matrix table header and rows (replace `| x_sign | y_sign |` columns with `| x_sign | y_sign | y_norm |`).

Show the new table header:

```python
        lines.append(
            "| `{sign_id}` | x `{x_sign}` | y `{y_sign}` | norm `{y_norm}` | "
            "rms `{rms:.6f}` | p95 `{p95:.6f}` | max `{max_abs:.6f}` | `{direction}` |".format(
                sign_id=item["sign_id"],
                x_sign=item["x_sign"],
                y_sign=item["y_sign"],
                y_norm=item["y_normalizer"],
                rms=stats.get("rms", 0.0),
                p95=stats.get("p95_abs", 0.0),
                max_abs=stats.get("max_abs", 0.0),
                direction=item.get("direction_status", "n/a"),
            )
        )
```

- [ ] **Step 3: Update default output paths to v2**

Change the argparse defaults in `main()`:

```python
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_v2_compare.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_v2_compare.md"),
    )
```

- [ ] **Step 4: AST-parse to confirm syntax**

Run:

```bash
python3 -c "import ast; ast.parse(open('scripts/distortion_calibration/ue_path_c_validation/compare_center_shift_projection_sweep.py').read()); print('OK')"
```

Expected: `OK`.

### Task 3.2: Run the UE sweep dispatcher remotely

**Files:**
- Output: `C:/temp/ue-remote/path_c_center_shift_projection_sweep/{sign_id}/{case_id}/{case_id}.0000.png` × 40

- [ ] **Step 1: Sync the updated plugin code to lanPC**

Push the modified plugin via P4 (the post-commit hook handles this on commit; until then, manually rsync if needed). Confirm with the user that lanPC has the updated code before dispatching.

If user asks to skip P4 / confirm sync: run

```bash
ssh lanpc "ls -la 'E:/RenderStream Projects/test_0311/Plugins/post-render-tool/Content/Python/post_render_tool/distortion_math.py'"
```

and confirm the modification timestamp matches the local one.

- [ ] **Step 2: Dispatch the sweep**

Run from repo root:

```bash
scp scripts/distortion_calibration/ue_path_c_validation/ue_center_shift_projection_sweep.py \
  lanpc:C:/temp/ue-remote/ue_center_shift_projection_sweep.py
ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/ue_center_shift_projection_sweep.py'
```

Expected: status `DISPATCHED`, 40 jobs queued, MRQ runs to completion (~10-20 min). If `FAIL`, read the error and fix before continuing.

- [ ] **Step 3: Pull the rendered PNGs back to the Mac**

Run:

```bash
mkdir -p validation_results/path_c_d3_exports/center_shift_projection_sweep/ue_renders
rsync -av --progress lanpc:C:/temp/ue-remote/path_c_center_shift_projection_sweep/ \
  validation_results/path_c_d3_exports/center_shift_projection_sweep/ue_renders/
```

Expected: 40 PNG files transferred under 8 sub-directories.

### Task 3.3: Run comparator and apply gate

**Files:**
- Output: `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_v2_compare.md`

- [ ] **Step 1: Run the comparator**

Run:

```bash
scripts/distortion_calibration/.venv/bin/python \
  scripts/distortion_calibration/ue_path_c_validation/compare_center_shift_projection_sweep.py \
  --acceptance-threshold-px 3.0
```

Expected: exit code 0 (PASS) or 2 (BLOCKED_FORMULA).

- [ ] **Step 2: Read the report and confirm winner**

Read `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_v2_compare.md`. The report selects the lowest-RMS direction-correct config. Verify:

- X-axis primary p95 ≤ 1 px (the strict gate — Stage 1 prediction was 0.21 px residual on X)
- Y-axis primary p95 ≤ 3 px (relaxed gate; if Stage 2 predicted 21 px from K1 coupling and the simulation matched D3, UE is expected to reproduce the same magnitude)
- Selected `sign_id` looks geometrically sensible (X same direction as input, Y flipped — i.e., `xp_y*_*`)

- [ ] **Step 3: Decide based on gate result**

- **PASS (status=PASS in JSON)**: proceed to Stage 5.
- **FAIL (X residual > 1 px)**: implementation bug in Stage 1 or sweep dispatcher. Re-read the failed case in the report, isolate, and fix in `distortion_math.py` or `ue_center_shift_projection_sweep.py`. Do NOT proceed.
- **FAIL (Y residual > 3 px on all 8 configs)**: the formula is genuinely insufficient. Proceed to Stage 4.

### Stage 3 Checkpoint

Files changed: 1 modified (`compare_center_shift_projection_sweep.py`), 40 PNGs generated, 2 reports written. Report status: "Stage 3 complete. Gate: <PASS|FAIL_X|FAIL_Y>. Selected config: `{sign_id}`. Next stage: <5|debug|4>." Wait for user instruction before committing or proceeding.

---

## Stage 4 — D3 K=0 control frames (fallback)

**Precondition:** Stage 2 or Stage 3 failed the gate. Skip if Stage 3 PASS.

### Task 4.1: Draft D3 render request document

**Files:**
- Create: `docs/d3-centershift-control-request.md`

- [ ] **Step 1: Write the request doc**

Create `docs/d3-centershift-control-request.md`:

```markdown
# D3 centerShift K=0 Control Render Request

## Purpose

Stage 2 offline simulation and/or Stage 3 UE sweep on existing K1=0.5 D3 frames
could not reconcile the Y-axis 21 px residual with any candidate NDC formula
or distortion coupling. This request gathers 4 fresh D3 frames at K1=K2=K3=0
to isolate the projection-translation component of `centerShiftMM` from any
distortion-coupled effects. With K=0, the post-process radial term is identically
zero and the only remaining mechanism is the projection principal-point shift —
this lets us read the raw `cx_ndc → pixel` mapping directly off the D3 output.

## Global Settings

Use the same MR Set / RenderStream-to-MR-Set workflow as the existing
`d3-path-c-csv-export-request.md` Group B. Resolution `1920×1080`, overscan `1.3`,
sensor `35×19.687mm` (paWidthMM=35, aspectRatio=1.77779), focal `30.302mm`,
camera pose identical to Group B (`offset.y=2.25`, `offset.z=-11.6`,
`rotation=(0, 0, -0)`). Aperture / focus distance / colour pipeline match Group B.

## Required Cases (4)

For all 4 frames:

| Field | Value |
|---|---:|
| `focalLengthMM` | `30.302` |
| `k1k2k3.x` | `0.0` |
| `k1k2k3.y` | `0.0` |
| `k1k2k3.z` | `0.0` |

Vary only `centerShiftMM`:

| Case ID | `centerShiftMM.x` | `centerShiftMM.y` |
|---|---:|---:|
| `path_c_center_k_zero_shiftx_n0p5` | `-0.5` | `0.0` |
| `path_c_center_k_zero_shiftx_p0p5` | `0.5` | `0.0` |
| `path_c_center_k_zero_shifty_n0p5` | `0.0` | `-0.5` |
| `path_c_center_k_zero_shifty_p0p5` | `0.0` | `0.5` |

Plus the existing `path_c_center_k1_p0p5_shift_zero` frame is the K=0/shift=0 anchor
(zero-anchor frame can be reused — K1=0.5 with shift=0 is geometrically equivalent
to K1=0 with shift=0 because the radial centre is the image centre and the K factor
multiplies a zero-radius vector for phase-correlation purposes; **but** to be safe,
also export `path_c_center_k_zero_shift_zero` (5th frame) as an explicit anchor.

## Return Layout

```text
validation_results/path_c_d3_exports/canonical/center_shift_k_zero/
├── path_c_center_k_zero_shift_zero.csv
├── path_c_center_k_zero_shift_zero.png
├── path_c_center_k_zero_shiftx_n0p5.csv
├── path_c_center_k_zero_shiftx_n0p5.png
├── path_c_center_k_zero_shiftx_p0p5.csv
├── path_c_center_k_zero_shiftx_p0p5.png
├── path_c_center_k_zero_shifty_n0p5.csv
├── path_c_center_k_zero_shifty_n0p5.png
├── path_c_center_k_zero_shifty_p0p5.csv
└── path_c_center_k_zero_shifty_p0p5.png
```

## Sanity Check

After rendering, the 4 non-zero frames should each show approximately a 16 px
shift from the zero-anchor on their primary axis (per the SDK NDC formula
`mm/focal × image_dim/2` with sensor_width-based normalization). If the Y-axis
frames show 21 px, the formula has an extra factor we have not yet identified.
If they show 9 px or 16 px, the previous K1=0.5 measurement of 21 px was K1
coupling and Stage 3 will land cleanly with the matching normalizer choice.

## Completion Checks

- D3 project folder cleaned of prior takes before recording.
- All 5 cases recorded individually.
- CSV (Dense) export enabled for each take.
- Matched Disguise Frame exported for each take.
- No crop, no resize, no tone-mapping / LUT / colour transforms.
```

### Task 4.2: Wait for user to deliver the 5 frames

- [ ] **Step 1: Pause execution**

The user runs the recordings in D3 Designer and uploads the 5 frames + 5 CSVs to:

```text
validation_results/path_c_d3_exports/canonical/center_shift_k_zero/
```

This is a manual step — confirm completion with the user before proceeding.

### Task 4.3: Phase-correlate the K=0 frames

**Files:**
- Create: `scripts/distortion_calibration/ue_path_c_validation/center_shift_k_zero_analysis.py`

- [ ] **Step 1: Create the analysis script**

Create `scripts/distortion_calibration/ue_path_c_validation/center_shift_k_zero_analysis.py`:

```python
"""Phase-correlate the K=0 centerShift control frames against the K=0 anchor.

Output: a markdown report comparing measured pixel shift against three
candidate formulas (sensor_height/2, sensor_width/2, raw mm).
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


ANCHOR = "path_c_center_k_zero_shift_zero"
CASES = (
    ("path_c_center_k_zero_shiftx_n0p5", -0.5, 0.0),
    ("path_c_center_k_zero_shiftx_p0p5",  0.5, 0.0),
    ("path_c_center_k_zero_shifty_n0p5",  0.0, -0.5),
    ("path_c_center_k_zero_shifty_p0p5",  0.0,  0.5),
)
ROOT = Path("validation_results/path_c_d3_exports/canonical/center_shift_k_zero")
FOCAL_MM = 30.302
SENSOR_W_MM = 35.0
ASPECT = 1.77779
IMAGE_W = 1920
IMAGE_H = 1080


def _load_gray(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.ndim == 3:
        img = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
    if np.issubdtype(img.dtype, np.integer):
        img = img.astype(np.float32) / float(np.iinfo(img.dtype).max)
    return img.astype(np.float32)


def main() -> int:
    anchor = _load_gray(ROOT / f"{ANCHOR}.png")
    sensor_h_mm = SENSOR_W_MM / ASPECT
    rows = []
    for case_id, mm_x, mm_y in CASES:
        case_img = _load_gray(ROOT / f"{case_id}.png")
        (sx, sy), resp = cv2.phaseCorrelate(anchor, case_img)
        cx_ndc = mm_x / FOCAL_MM
        cy_ndc = mm_y / FOCAL_MM
        pred_height = (
            cx_ndc * IMAGE_W / 2,
            cy_ndc * IMAGE_H / 2 * (-1) if mm_y else 0.0,
        )
        pred_width = (
            cx_ndc * IMAGE_W / 2,
            cy_ndc * IMAGE_W / 2 * (-1) if mm_y else 0.0,
        )
        pred_raw = (
            mm_x * IMAGE_W / SENSOR_W_MM,
            -mm_y * IMAGE_H / sensor_h_mm if mm_y else 0.0,
        )
        rows.append({
            "case_id": case_id,
            "shift_x_mm": mm_x,
            "shift_y_mm": mm_y,
            "measured_x_px": sx,
            "measured_y_px": sy,
            "phase_response": resp,
            "predicted_height_x_px": pred_height[0],
            "predicted_height_y_px": pred_height[1],
            "predicted_width_x_px":  pred_width[0],
            "predicted_width_y_px":  pred_width[1],
            "predicted_raw_x_px":    pred_raw[0],
            "predicted_raw_y_px":    pred_raw[1],
        })
    out_dir = Path("validation_results/path_c_d3_exports/canonical")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "center_shift_k_zero_analysis.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8"
    )
    md = ["# K=0 centerShift Direct Measurement", "",
          "| case | mm | meas_x | meas_y | pred_h_x | pred_h_y | pred_w_x | pred_w_y | resp |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        md.append(
            "| `{c}` | ({mx:+.1f},{my:+.1f}) | {sx:+.3f} | {sy:+.3f} | {hx:+.3f} | {hy:+.3f} | {wx:+.3f} | {wy:+.3f} | {resp:.3f} |".format(
                c=r["case_id"],
                mx=r["shift_x_mm"], my=r["shift_y_mm"],
                sx=r["measured_x_px"], sy=r["measured_y_px"],
                hx=r["predicted_height_x_px"], hy=r["predicted_height_y_px"],
                wx=r["predicted_width_x_px"],  wy=r["predicted_width_y_px"],
                resp=r["phase_response"],
            )
        )
    (out_dir / "center_shift_k_zero_analysis.md").write_text("\n".join(md), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the analysis**

Run:

```bash
scripts/distortion_calibration/.venv/bin/python \
  scripts/distortion_calibration/ue_path_c_validation/center_shift_k_zero_analysis.py
```

Expected: exit 0, two output files.

- [ ] **Step 3: Read and decide**

Open `validation_results/path_c_d3_exports/canonical/center_shift_k_zero_analysis.md`.

- **If measured X/Y both match a single candidate (height OR width OR raw) within ≤1 px**: that's the production formula. Update `distortion_math.py` to hardcode the winning normalizer choice (and `Y_NORMALIZER` config option becomes a sweep-only artefact to delete in Stage 5). Re-run Stage 3.
- **If measured X matches NDC but Y matches none of the three predictions**: the Filmback path is fundamentally insufficient. Plan upgrade: replace `Filmback.SensorVerticalOffset` with a `CineCameraComponent::CustomProjectionMatrix` direct NDC translation (mirrors `RenderStreamProjectionPolicy.cpp:122-155` exactly). Document this as a new sub-stage 4b in `distortion-investigation.md` and stop — the user must approve the architecture change before continuing.

### Stage 4 Checkpoint

Files changed: 1 created (`d3-centershift-control-request.md`), 5 frames received from user, 1 created (`center_shift_k_zero_analysis.py`), 2 generated reports. Report status: "Stage 4 complete. Decision: <Stage 3 retry | Stage 4b custom projection matrix | abandon Filmback path>." Wait for user instruction.

---

## Stage 5 — Production smoke + cleanup

**Precondition:** Stage 3 PASS gate. Skip otherwise.

### Task 5.1: Toggle production projection tracks on

**Files:**
- Modify: `Content/Python/post_render_tool/config.py:48` (`CENTER_SHIFT_ENABLE_PROJECTION_TRACKS`)
- Modify: `Content/Python/post_render_tool/config.py:49-51` (collapse sweep knobs)

- [ ] **Step 1: Replace the Path C centerShift config block**

Replace lines 41-50 (the Path C centerShift block) of `config.py` with the chosen final values from Stage 3 winner. Suppose Stage 3 picked `xp_yn_height` (X +1, Y −1, Y normalizer = sensor_height); the block becomes:

```python
# --- Path C centerShift projection mapping ---
# Disguise centerShiftMM is converted to UE CineCamera Filmback offset using the
# RenderStream NDC formula (RenderStream-UE RenderStreamProjectionPolicy.cpp:122-155):
#     sensor_h_offset_mm = (centerShiftMM.x / focalLengthMM) * sensor_width_mm  / 2
#     sensor_v_offset_mm = (centerShiftMM.y / focalLengthMM) * sensor_height_mm / 2 * (-1)
# X sign: +1 (D3 X same direction as UE X). Y sign: -1 (NDC +Y up vs UE +Y down).
# Y normalizer: sensor_height (selected by Stage 3 sweep, gate <= 3 px residual).
CENTER_SHIFT_ENABLE_PROJECTION_TRACKS = True
CENTER_SHIFT_PROJECTION_X_SIGN = 1.0
CENTER_SHIFT_PROJECTION_Y_SIGN = -1.0
CENTER_SHIFT_PROJECTION_Y_NORMALIZER = "sensor_height"
```

(Substitute the actual winning sign / normalizer from Stage 3 output before applying.)

- [ ] **Step 2: Run the production CSV pipeline end-to-end**

Drop the most recent production CSV into the pipeline via remote execution:

```bash
scp scripts/distortion_calibration/ue_path_c_validation/ue_path_c_d3_mrq_render.py \
  lanpc:C:/temp/ue-remote/ue_path_c_d3_mrq_render.py
ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/ue_path_c_d3_mrq_render.py'
```

Expected: render completes, output PNG lands at `C:/temp/ue-remote/path_c_d3_exports/...`.

- [ ] **Step 3: Pull and compare against `path_c_production_match` D3 frame**

```bash
rsync -av lanpc:C:/temp/ue-remote/path_c_d3_exports/production_match/ \
  validation_results/path_c_d3_exports/production_match_v2/

scripts/distortion_calibration/.venv/bin/python -c "
import cv2, sys
ue   = cv2.imread('validation_results/path_c_d3_exports/production_match_v2/<frame>.png', cv2.IMREAD_UNCHANGED)
d3   = cv2.imread('validation_results/path_c_d3_exports/canonical/production_match/<frame>.png', cv2.IMREAD_UNCHANGED)
diff = cv2.absdiff(ue[..., :3], d3[..., :3])
print('max:', diff.max(), 'mean:', diff.mean())
"
```

(Replace `<frame>` with the actual production frame number.)

Expected: max ≤ 8/255, mean ≤ 2/255 (within the 8-bit PNG quantization floor).

### Task 5.2: Cleanup — collapse sweep knobs (memory: no temp switches)

**Files:**
- Modify: `Content/Python/post_render_tool/distortion_math.py` (remove `y_normalizer` parameter)
- Modify: `Content/Python/post_render_tool/config.py` (remove `CENTER_SHIFT_PROJECTION_Y_NORMALIZER`)
- Modify: `scripts/distortion_calibration/ue_path_c_validation/ue_center_shift_projection_sweep.py` (delete sweep dimension)
- Modify: `scripts/distortion_calibration/ue_path_c_validation/compare_center_shift_projection_sweep.py` (delete y_normalizer table column)
- Modify: `Content/Python/post_render_tool/tests/test_custom_postprocess_distortion_math.py` (drop the `y_normalizer="sensor_width"` test)

The user's `feedback_no_temporary_runtime_switches` memory requires that once Stage 3 picks a winner, the alternate route is deleted from production code. Sweep config knobs (`X_SIGN`, `Y_SIGN`, `Y_NORMALIZER`) collapse to hardcoded values inside `map_center_shift_projection`.

- [ ] **Step 1: Hardcode the winning formula in `distortion_math.py`**

Replace the `map_center_shift_projection` body (introduced in Task 1.2 / 1.6) with the hardcoded final form. Drop the `x_sign`, `y_sign`, `y_normalizer` parameters entirely:

```python
def map_center_shift_projection(
    *,
    center_shift_x_mm: float,
    center_shift_y_mm: float,
    sensor_width_mm: float,
    aspect: float,
    focal_length_mm: float,
) -> CenterShiftProjectionMapping:
    """Map D3 centerShiftMM to UE Filmback offset + post-process material CenterUV.

    Formula per RenderStream SDK + Stage 3 sweep gate:
        cx_ndc = centerShiftMM.x / focalLengthMM
        cy_ndc = centerShiftMM.y / focalLengthMM
        sensor_h_offset_mm = +cx_ndc * sensor_width_mm  / 2
        sensor_v_offset_mm = -cy_ndc * sensor_height_mm / 2     # NDC +Y up vs UE +Y down
    """
    if sensor_width_mm == 0:
        raise ValueError("sensor_width_mm must be non-zero")
    if aspect == 0:
        raise ValueError("aspect must be non-zero")
    if focal_length_mm == 0:
        raise ValueError("focal_length_mm must be non-zero")

    sensor_height_mm = sensor_width_mm / aspect
    cx_ndc = center_shift_x_mm / focal_length_mm
    cy_ndc = center_shift_y_mm / focal_length_mm

    return CenterShiftProjectionMapping(
        center_u=0.5 + center_shift_x_mm / sensor_width_mm,
        center_v=0.5 + center_shift_y_mm / sensor_height_mm,
        sensor_horizontal_offset_mm= cx_ndc * (sensor_width_mm  / 2.0),
        sensor_vertical_offset_mm= -cy_ndc * (sensor_height_mm / 2.0),
        sensor_height_mm=sensor_height_mm,
    )
```

(If the Stage 3 winner is NOT `xp_yn_height`, substitute the corresponding signs and Y normalizer.)

- [ ] **Step 2: Delete sweep config knobs**

In `config.py`, replace the entire centerShift config block with the trimmed final form:

```python
# --- Path C centerShift projection mapping ---
# Hardcoded per Stage 3 sweep gate. Formula details: distortion_math.map_center_shift_projection.
CENTER_SHIFT_ENABLE_PROJECTION_TRACKS = True
```

- [ ] **Step 3: Delete sweep dispatcher dimensions**

The sweep scripts (`ue_center_shift_projection_sweep.py`, `compare_center_shift_projection_sweep.py`) become historical evidence after Stage 3 passes. Per the `feedback_no_temporary_runtime_switches` rule, these test harnesses can stay in the tree as historical artefacts, but their `SIGN_SWEEPS` matrix must collapse to the single winning row (e.g., `("xp_yn_height", 1.0, -1.0, "sensor_height")`) and the `_configure_job` loop should iterate only that one row. This way someone re-running them will get a single regression check, not a 40-frame sweep.

In `ue_center_shift_projection_sweep.py`, replace `SIGN_SWEEPS` with:

```python
SIGN_SWEEPS = (
    # Frozen Stage 3 winner. Re-running this script regression-tests the production formula.
    ("xp_yn_height", 1.0, -1.0, "sensor_height"),
)
```

In `compare_center_shift_projection_sweep.py` `SIGN_SWEEPS`:

```python
SIGN_SWEEPS = {
    "xp_yn_height": {"x_sign": 1.0, "y_sign": -1.0, "y_normalizer": "sensor_height"},
}
```

- [ ] **Step 4: Delete the dead `y_normalizer="sensor_width"` test**

Remove `test_center_shift_projection_mapping_ndc_isotropic_y` from `tests/test_custom_postprocess_distortion_math.py`. Update `test_center_shift_projection_mapping_ndc_focal30p302` to drop the `focal_length_mm=30.302, y_normalizer=...` kwargs that Task 1.1 added (since the production signature no longer accepts them):

```python
    def test_center_shift_projection_mapping_ndc_focal30p302(self):
        mapping = map_center_shift_projection(
            center_shift_x_mm=0.5,
            center_shift_y_mm=0.5,
            sensor_width_mm=35.0,
            aspect=ASPECT_16_9,
            focal_length_mm=30.302,
        )
        self.assertAlmostEqual(mapping.center_u, 0.5142857142857142, places=7)
        self.assertAlmostEqual(mapping.center_v, 0.5253968253968254, places=7)
        self.assertAlmostEqual(mapping.sensor_horizontal_offset_mm, +0.28876641145, places=7)
        self.assertAlmostEqual(mapping.sensor_vertical_offset_mm,  -0.16245628095, places=7)
```

Drop the `y_normalizer="garbage"` assertion from `test_center_shift_projection_mapping_rejects_bad_inputs` (the parameter no longer exists).

- [ ] **Step 5: Run all tests to confirm cleanup passes**

Run:

```bash
cd Content/Python && python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -v
```

Expected: every test passes.

### Task 5.3: Update docs and memory

**Files:**
- Modify: `docs/distortion-investigation.md` (add Stage 5 close-out section)
- Modify: `validation_results/path_c_validation/path_c_validation_summary.md` (status row)
- Modify: `/Users/bip.lan/.claude/projects/-Users-bip-lan-AIWorkspace-vp-post-render-tool/memory/project_distortion_pixel_perfect.md` (close-out)

- [ ] **Step 1: Append Stage 5 close-out section**

Append to `docs/distortion-investigation.md`:

```markdown
## 2026-05-06 — centerShift Path C close-out

Stage 3 sweep gate passed with `xp_yn_height` (X +1, Y −1, Y normalizer = sensor_height).
Production formula now hardcoded in `distortion_math.map_center_shift_projection`.
Sweep knobs (`X_SIGN` / `Y_SIGN` / `Y_NORMALIZER`) collapsed per
`feedback_no_temporary_runtime_switches`.

Production smoke against `path_c_production_match_frame_<NNNN>` clears 8-bit
quantization floor. Path C K1/K2/K3 + centerShift gate reports moved from
`PENDING` to `PASS`.

(Substitute the actual winning sign / normalizer if different from the example
above before committing.)
```

- [ ] **Step 2: Update validation summary**

In `path_c_validation_summary.md`, replace the v2 row added in Stage 0:

```text
| centerShift projection sign sweep (NDC v2) | PENDING | ... |
```

with:

```text
| centerShift projection sign sweep (NDC v2) | PASS | `validation_results/path_c_d3_exports/canonical/center_shift_projection_sweep_v2_compare.md` |
| centerShift production smoke | PASS | `validation_results/path_c_d3_exports/production_match_v2/` |
```

- [ ] **Step 3: Update memory**

Replace the `Distortion pixel-perfect 调试中` memory body with the close-out form. Edit `project_distortion_pixel_perfect.md`:

```markdown
---
name: 已 close-out — Path C centerShift NDC mapping 落地
description: Path C K1/K2/K3 + centerShift 全部过 gate；centerShiftMM = NDC clip-space 平移量 / focalLengthMM，UE Filmback offset = cx_ndc × sensor_w/2、cy_ndc × sensor_h/2 × (-1)；x_sign/y_sign/y_normalizer 已 collapse
type: project
---

Path C centerShift 已 close-out (2026-05-06)。

公式（已 hardcode 进 `distortion_math.map_center_shift_projection`）：
- `cx_ndc = centerShiftMM.x / focalLengthMM`
- `sensor_h_offset_mm = +cx_ndc × sensor_width_mm / 2`
- `sensor_v_offset_mm = -cx_ndc × sensor_height_mm / 2` (NDC +Y up vs UE +Y down)
- material `CenterUV = 0.5 + centerShiftMM / sensor_dim` (radial 中心)

来源：disguise-one/RenderStream SDK 公开仓库 (`Textures.cpp:455-489` 官方 sample),
disguise-one/RenderStream-UE 官方 ProjectionPolicy (`RenderStreamProjectionPolicy.cpp:122-155`).

Stage 3 sweep 选定 `xp_yn_height` (substitute actual winner)，X p95 < 1 px / Y p95 < 3 px。
Production smoke 跟 `path_c_production_match` 对比通过 8-bit 量化 floor。

`feedback_no_temporary_runtime_switches` 已遵守：sweep config 全部 collapse 进
hardcoded route。

详细计划：`docs/superpowers/plans/2026-05-06-centershift-ndc-mapping.md`。
```

Update `MEMORY.md` line for this entry to reference the new title.

### Stage 5 Checkpoint

Files changed: `distortion_math.py`, `config.py`, `sequence_builder.py` (no change needed if signature unchanged), 2 sweep scripts, tests, 2 docs, 1 memory. All tests pass. Production smoke passes. Report status: "Stage 5 complete. Path C centerShift mapping is production-ready. Sweep knobs cleaned up." Wait for user instruction before committing.

---

## Self-Review Notes

**Spec coverage:**
- Stage 0 covers status renaming ✓
- Stage 1 covers public-formula adoption ✓
- Stage 2 covers offline simulation as decision gate ✓
- Stage 3 covers Y normalizer sweep ✓
- Stage 4 covers K=0 control fallback (incl. custom projection matrix escape) ✓
- Stage 5 covers production toggle + sweep-knob collapse per memory ✓

**Type / signature consistency:**
- `map_center_shift_projection` adds `focal_length_mm` (Task 1.2) and `y_normalizer` (Task 1.6); Stage 5 Task 5.2 removes `y_normalizer` and `*_sign` parameters when collapsing.
- All 4 caller updates (sequence_builder, sweep dispatcher, simulator, k_zero_analysis) pass the same kwarg name `focal_length_mm`.
- `CenterShiftProjectionMapping` dataclass field names unchanged across the plan.

**Placeholder scan:** all "PENDING" / "TBD" tokens are intentional status values in reports, not skipped work. The Stage 4 / 5 docs include literal `<frame>`, `<NNNN>`, "Substitute the actual..." markers — these MUST be filled in at execution time before the file is saved; flagged inline in the relevant tasks.

**Known fragile points:** Stage 3 Step 2 assumes `lanPC` has the latest plugin code via P4 sync; if the post-commit hook didn't fire (`--no-ff` merge gotcha from CLAUDE.md), the user must manually `git push p4 main` before dispatching. Stage 4 is a manual data wait — the agent must stop and confirm completion before continuing Task 4.3.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-06-centershift-ndc-mapping.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Good for staying focused and catching regressions early.
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review. Slightly faster wall-clock but heavier on the main context.

Which approach?
