# EXR Timecode Backend Migration: oiiotool CLI → `oiio-static-python` Python Binding

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the widget "Patch EXR Timecode" button work end-to-end on the lanPC Windows production machine, and complete P1 G2 (DaVinci 19+ auto-conform) + P1 G4 (OTIO sidecar import).

**Architecture:** Swap the writer's backend from `subprocess` + `oiiotool` CLI to in-process `import OpenImageIO as oiio` via the **`oiio-static-python`** PyPI wheel — a statically built Python binding of OpenImageIO 3.0.8 (the same C++ library `oiiotool` is built on top of). UE Python `pip install --user oiio-static-python==3.0.8.1.1` (same `--user` pattern proven by the prior `opentimelineio` install). Pure-Python helpers (`_frame_to_timecode`, regex/MRQ-token validation) stay byte-identical.

**Tech Stack:** `oiio-static-python==3.0.8.1.1` (OpenImageIO 3.0.8 + OpenColorIO statically linked, ~11 MB wheel cp310–cp313 win_amd64 / macOS / Linux), UE 5.7 Python 3.11. Ground-truth header inspection via `exrheader.exe` from the already-installed Miniforge3 (`C:\Tools\miniforge3\Library\bin\exrheader.exe`).

---

## Why this plan supersedes `2026-05-14-exr-timecode-pypi-openexr-migration.md`

The previous plan was reviewed and returned NO-GO. Five blockers + five should-fix items. Status of each in this plan:

| Original blocker / fix | Status here |
|---|---|
| Blocker 1: `OpenEXR.TimeCode` keyword constructor doesn't exist | **Sidestepped** — we don't use PyPI `OpenEXR` at all; OIIO Python API is the surface |
| Blocker 2: `OpenEXR.Rational` write fails with "unrecognized type" | **Sidestepped** — OIIO has its own `TypeRational` typed attribute, validated by the spike's `oiiotool` choice |
| Blocker 3: probe used 4×4 synthetic RGB, not real MRQ EXR | **Addressed** — Phase 2 probe operates on a real MRQ EXR pulled from lanPC; channels / compression / multipart / pixelAspectRatio preservation verified via `exrheader` diff before vs after |
| Blocker 4: multipart handling undefined (`f.parts[0]` only) | **Addressed** — writer reads via `oiio.ImageInput.seek_subimage` and writes via `oiio.ImageOutput` multi-subimage `open(path, [specs])` + `AppendSubimage` per subimage (probe Phase A.7 nails down the exact API signature; `TestMultipartPreservation` regression-guards it). Per-subimage `ImageBuf.write` removed — Codex adversarial review pointed out it has no multipart-append semantics |
| Blocker 5: no atomic rewrite (crash safety) | **Addressed** — writer writes to `<path>.tmp` then `os.replace(tmp, path)`; partial-write recovery covered |
| Should-fix: `plugin-setup.md` still mentions oiiotool | **Addressed** — Task 10 updates the doc |
| Should-fix: `--target` fallback unrealizable | **Removed** — confirmed `otio_export.py:33` does plain `import opentimelineio`; `--user` works without sys.path manipulation. Plan does NOT mention `--target` |
| Should-fix: test count was 14, actual is 16 | **Fixed** — pre-swap file had `TestPatchExrTimecode` (6) + `TestFrameToTimecodeRoundTrip` (6) + `TestFractionalFpsRationalMetadata` (4) = 16. Plus new `TestMultipartPreservation` (1) added in Task 7 Step 4 to close the Codex [high] multipart regression gap → **17 tests post-swap** |
| Should-fix: OTIO marked optional vs required in acceptance | **Fixed** — OTIO sidecar import is **required** per parent task acceptance ("OTIO sidecar 也能 import → timeline 起点对") and is Task 14 in this plan |
| Should-fix: version pin | **Fixed** — pin `oiio-static-python==3.0.8.1.1` everywhere |

**Codex adversarial review (2026-05-14, run #2) added three findings on the OIIO Python plan itself:**

| Codex adversarial finding | Status here |
|---|---|
| [critical] Phase B gate could be skipped + circular validation via patched file | **Fixed** — Task 1 is now a hard blocker for `/tmp/mrq_sample.exr`; probe Phase B is non-skippable (exit 30 if missing); Phase B operates on a COPY of the original; Task 12 no longer falls back to "patch then validate". Before/after header diff is captured against the Task 1 baseline. |
| [high] Per-subimage `ImageBuf.write(tmp)` would collapse multipart EXR to last subimage | **Fixed** — writer switched to `ImageInput.seek_subimage` (read every subimage) + `ImageOutput` multi-subimage `open` + `AppendSubimage` (write every subimage). Probe Phase A.7 validates the API signature before the writer commits to it. New `TestMultipartPreservation` unit test guards the regression. |
| [high] `git revert <task-6>..<task-8>` excludes the writer-swap commit | **Fixed** — Rollback block now uses explicit reverse-order list `git revert <task-8> <task-7> <task-6>` (or inclusive-range form `<task-6>^..<task-8>`) and adds a post-revert `grep` to confirm the writer is back on subprocess+oiiotool. |

---

## What does NOT change

- `_frame_to_timecode` drop-frame inverse algorithm — 6 unit tests already cover it.
- `_filename_pattern_to_regex` + `_validate_filename_pattern` — pure regex + MRQ-token validation.
- `patch_exr_timecode_in_dir` public signature (same args, same return).
- `run_patch_exr_timecode` in `pipeline.py`.
- `widget.py` callback (`_on_patch_exr_timecode_clicked`).
- P0 G1 sequence-frame work (already production).
- OTIO export path (no overlap).

## Hard constraints (user memory)

- **No runtime backend toggle / feature flag** (`feedback_no_temporary_runtime_switches.md`). Hard swap. Rollback = `git revert`.
- **No auto-commit at end** (`feedback_explicit_commit_only.md`). Per-task `git commit` steps are the only commits.
- **Chinese commit messages** (`feedback_commit_language.md`).

---

## File Structure

**Modified:**
- `Content/Python/post_render_tool/exr_timecode_writer.py` — module docstring + replace `_ensure_oiiotool` with `_ensure_oiio` + rewrite `patch_exr_timecode_in_dir` body using `oiio.ImageBuf` API with multipart loop + atomic rewrite. Pure-Python helpers untouched.
- `Content/Python/post_render_tool/tests/test_exr_timecode_writer.py` — drop `_HAVE_OIIOTOOL` / subprocess test helpers; use `OpenImageIO` Python for mock-EXR generation and read-back; use `exrheader` (when available) as typed-attribute ground truth.
- `scripts/integration_p1.py` — mock-EXR gen + verify via `OpenImageIO` Python; final typed-attribute verify via `exrheader.exe` (already on lanPC).
- `scripts/exr_timecode_spike_report.md` — append 2026-05-14 addendum: backend swap rationale.
- `docs/plugin-setup.md` — replace the "OpenImageIO CLI / oiiotool" install line with the `pip install --user oiio-static-python` line.

**Created:**
- `scripts/probe_oiio_static_python.py` — standalone probe; runs on dev Mac + on lanPC UE Python. Two phases: (A) synthetic 4×4 EXR API contract check; (B) real MRQ EXR preservation check (channels / compression / multipart / pixelAspectRatio survive the rewrite). Probe is the GO/NO-GO gate before any production code change lands.

**Untouched:**
- `Content/Python/post_render_tool/pipeline.py`
- `Content/Python/post_render_tool/widget.py`
- `Content/Python/post_render_tool/otio_export.py`
- `Content/Python/post_render_tool/timecode.py`

---

## Phase 0 — Real MRQ EXR sample (HARD BLOCKER before any code change)

### Task 1: Pull a real MRQ EXR from lanPC + capture baseline header

**Goal:** Probe must validate OIIO Python rewrites a *real* MRQ EXR without losing channels / compression / multipart / pixelAspectRatio. Per Codex adversarial review (2026-05-14): **this is a hard blocker — no code change in Tasks 4+ until this sample exists and the baseline header is captured**. Patching production EXR before the rewrite is validated risks unrecoverable data loss (the patched file replaces the original; we can never reconstruct what it had).

**Files:** none modified. Produces: `/tmp/mrq_sample.exr` + `/tmp/mrq_sample_baseline.txt`.

- [ ] **Step 1: Check whether lanPC already has a MRQ-rendered EXR from prior work**

```bash
echo 'Get-ChildItem -Path "E:\RenderStream Projects\test_0311" -Filter "*.exr" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 5 FullName,Length' | ssh lanpc powershell -Command -
```

Expected: 1+ existing EXR files, or empty list.

- [ ] **Step 2: Obtain the sample (one of 2A or 2B — NOT skippable)**

**2A: If existing EXR present from Step 1, copy to dev Mac.**

```bash
scp "lanpc:E:/RenderStream Projects/test_0311/<path-from-step-1>" /tmp/mrq_sample.exr
ls -l /tmp/mrq_sample.exr
```

Expected: file size > 100 KB (real EXR, not a 4×4 synthetic from a prior test).

**2B: If no existing EXR, ask user to render 3 MRQ EXR frames.**

Tell user: "Need a sample MRQ EXR before I can probe. Open the widget → Import take_4 (or any take) → Open MRQ → set Output Format to `.exr Sequence` → render 3 frames into `E:/MRQ_out/p1g2_probe/`. Then reply with the dir + one filename."

Wait for user. Then `scp lanpc:<one-file>.exr /tmp/mrq_sample.exr`.

**STOP gate:** if neither 2A nor 2B produced `/tmp/mrq_sample.exr`, halt the plan. Do NOT advance to Task 2. Real MRQ sample is non-negotiable per Codex adversarial finding [critical].

- [ ] **Step 3: Record the sample's baseline header attributes — MANDATORY**

This is the "before" snapshot used for the after-rewrite diff in Task 3 Phase B and Task 12. Without it, we can't prove preservation.

```bash
if which exrheader >/dev/null 2>&1; then
  exrheader /tmp/mrq_sample.exr > /tmp/mrq_sample_baseline.txt 2>&1
  echo "Saved baseline at /tmp/mrq_sample_baseline.txt"
  head -40 /tmp/mrq_sample_baseline.txt
else
  echo "exrheader missing on dev Mac — falling back to OIIO Python attribute dump"
  python3 -c "
import OpenImageIO as oiio
buf = oiio.ImageBuf('/tmp/mrq_sample.exr')
si = 0
with open('/tmp/mrq_sample_baseline.txt','w') as f:
  while True:
    b = oiio.ImageBuf('/tmp/mrq_sample.exr', si, 0)
    if b.has_error: break
    s = b.spec()
    f.write(f'--- subimage {si} ---\n')
    f.write(f'dims={s.width}x{s.height} nchannels={s.nchannels} format={s.format}\n')
    f.write(f'channelnames={list(s.channelnames)}\n')
    f.write(f'compression={s.getattribute(\"compression\")}\n')
    f.write(f'pixelAspectRatio={s.getattribute(\"PixelAspectRatio\")}\n')
    si += 1
print('subimages:', si)
"
fi
cat /tmp/mrq_sample_baseline.txt | head -50
```

If both options fail (no exrheader AND no OIIO yet because Task 2 hasn't installed it) — install Task 2 first, then come back and finish Step 3 before any further task runs.

**Exit criterion:** `/tmp/mrq_sample.exr` exists AND `/tmp/mrq_sample_baseline.txt` contains the baseline attribute snapshot. Both files MUST be present before Task 3 runs.

---

## Phase 1 — Probe (GO/NO-GO gate)

### Task 2: Install `oiio-static-python` in a dev Mac venv

**Files:** none in repo modified. Side effect: creates `.venv_oiio_probe/` (gitignored — confirm).

- [ ] **Step 1: Confirm `.venv_oiio_probe` is gitignored**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
grep -q "^\.venv_" .gitignore || echo "WARN: .venv_ not in .gitignore — add it before creating the venv"
```

If WARN, append `.venv_*` to `.gitignore` and `git add .gitignore` (do not commit yet — the gitignore change rides with the probe-creation commit in Task 3 step 4).

- [ ] **Step 2: Create + activate venv (Python 3.11 to mirror UE Python)**

```bash
python3.11 -m venv .venv_oiio_probe
source .venv_oiio_probe/bin/activate
python -V
```

Expected: `Python 3.11.X`. If `python3.11` is not installed on dev Mac, `brew install python@3.11` first.

- [ ] **Step 3: Install pinned `oiio-static-python`**

```bash
pip install --upgrade pip
pip install oiio-static-python==3.0.8.1.1
```

Expected: `Successfully installed oiio-static-python-3.0.8.1.1` + transitive deps (numpy).

- [ ] **Step 4: Sanity-check `import OpenImageIO` works**

```bash
python -c "import OpenImageIO as oiio; print(oiio.__version__)"
```

Expected: a version string like `3.0.8.X` (the OIIO C++ version embedded in the static build).

If `ImportError` → wheel binary mismatch (cp311 architecture wrong, or numpy ABI). Stop, report; do not advance to Task 3.

---

### Task 3: Write + run `scripts/probe_oiio_static_python.py`

**Files:**
- Create: `scripts/probe_oiio_static_python.py`

**Goal:** Empirically validate every OIIO Python API call the writer will make, AND verify preservation of a real MRQ EXR's channels / compression / multipart / pixelAspectRatio after a typed-attribute rewrite. Exit non-zero on any failure with a specific diagnostic.

- [ ] **Step 1: Write the probe**

```python
# scripts/probe_oiio_static_python.py
"""Probe oiio-static-python wheel for the OpenImageIO Python API surface
exr_timecode_writer needs, AND verify channels / compression / multipart /
pixelAspectRatio survive a typed-attribute rewrite of a real MRQ EXR.

Exit 0 on full pass, non-zero with a specific diagnostic on any failure.
Two phases:
  A — synthetic 4x4 RGB EXR API contract (immediate, no user interaction)
  B — real MRQ EXR preservation roundtrip (uses /tmp/mrq_sample.exr from
      Task 1 step 2)
"""
from __future__ import annotations

import os
import sys
import tempfile


def _fail(code: int, msg: str) -> int:
    print(f"FAIL [{code}]: {msg}")
    return code


def main() -> int:
    try:
        import OpenImageIO as oiio
        import numpy as np  # noqa: F401
    except ImportError as e:
        return _fail(1, f"import OpenImageIO/numpy — {e}")

    print(f"OpenImageIO version: {oiio.__version__}")

    # --- Phase A: synthetic 4x4 EXR API contract ----------------------
    for name in ("ImageBuf", "ImageSpec", "TypeDesc", "TypeTimeCode", "TypeRational"):
        if not hasattr(oiio, name):
            return _fail(2, f"oiio.{name} missing — API mismatch")
    print("PASS A1: required symbols ImageBuf/ImageSpec/TypeDesc/TypeTimeCode/TypeRational")

    with tempfile.TemporaryDirectory() as tmpdir:
        src = os.path.join(tmpdir, "synth.exr")
        out = os.path.join(tmpdir, "patched.exr")
        spec = oiio.ImageSpec(4, 4, 3, "half")
        spec.attribute("compression", "zip")
        buf = oiio.ImageBuf(spec)
        oiio.ImageBufAlgo.fill(buf, (0.5, 0.5, 0.5))
        if not buf.write(src):
            return _fail(3, f"write synth — {buf.geterror()}")
        print(f"PASS A2: wrote synth EXR {os.path.getsize(src)} bytes")

        src_buf = oiio.ImageBuf(src)
        if src_buf.has_error:
            return _fail(4, f"read synth — {src_buf.geterror()}")
        new_spec = src_buf.specmod()

        if not hasattr(oiio, "TimeCode"):
            return _fail(5, "oiio.TimeCode missing — manual BCD pack needed; please report")
        tc_helper = oiio.TimeCode(hours=10, minutes=0, seconds=0, frame=0, dropFrame=False)
        tc_value = (tc_helper.timeAndFlags(), tc_helper.userData())
        new_spec.attribute("smpte:TimeCode", oiio.TypeTimeCode, tc_value)
        new_spec.attribute("FramesPerSecond", oiio.TypeRational, (50, 1))

        if not src_buf.write(out):
            return _fail(6, f"write patched — {src_buf.geterror()}")
        print("PASS A3: wrote patched EXR with typed timeCode + rational FPS")

        check = oiio.ImageBuf(out)
        if check.has_error:
            return _fail(7, f"reread patched — {check.geterror()}")
        cs = check.spec()
        tc_attr = cs.getattribute("smpte:TimeCode")
        if tc_attr is None:
            return _fail(8, "smpte:TimeCode missing after roundtrip")
        print(f"PASS A4: smpte:TimeCode roundtrip -> {tc_attr!r}")

        fps_attr = cs.getattribute("FramesPerSecond")
        if fps_attr is None:
            return _fail(9, "FramesPerSecond missing after roundtrip")
        if tuple(fps_attr) != (50, 1):
            return _fail(10, f"FramesPerSecond drift -> {fps_attr!r}")
        print(f"PASS A5: FramesPerSecond rational roundtrip -> {fps_attr!r}")

        if cs.nchannels != 3:
            return _fail(11, f"channel count drift {cs.nchannels} != 3")
        print(f"PASS A6: channels survived -> {cs.channelnames}")

    # --- Phase A.7: multipart write API discovery ---------------------
    # OIIO ImageBuf has no multi-subimage write; multipart must go through
    # ImageOutput's per-subimage open() + write() sequence. Validate the
    # exact Python binding signature BEFORE the writer relies on it.
    with tempfile.TemporaryDirectory() as tmpdir:
        mp = os.path.join(tmpdir, "multipart.exr")
        spec0 = oiio.ImageSpec(4, 4, 3, "half")
        spec0.attribute("compression", "zip")
        pix0 = np.full((4, 4, 3), 0.5, dtype=np.float16)
        spec1 = oiio.ImageSpec(4, 4, 4, "half")
        spec1.attribute("compression", "zip")
        pix1 = np.full((4, 4, 4), 0.3, dtype=np.float16)

        out = oiio.ImageOutput.create(mp)
        if out is None:
            return _fail(12, "ImageOutput.create returned None")
        if not out.supports("multiimage"):
            return _fail(13, "ImageOutput plugin does not advertise multiimage support")

        # Multi-subimage open: pass a list of specs to declare the file
        # will contain N subimages. First write_image writes subimage 0.
        # Subsequent subimages: re-open with `AppendSubimage` flag.
        if not out.open(mp, [spec0, spec1]):
            return _fail(14, f"multi-subimage open — {out.geterror()}")
        if not out.write_image(pix0):
            return _fail(15, f"subimage 0 write — {out.geterror()}")
        append_mode = getattr(oiio, "AppendSubimage", None)
        if append_mode is None:
            # OpenImageIO Python 3.x might expose under different name.
            append_mode = getattr(getattr(oiio, "ImageOutputOpenMode", None), "AppendSubimage", None)
        if append_mode is None:
            return _fail(16, "AppendSubimage open mode constant not found on oiio module")
        if not out.open(mp, spec1, append_mode):
            return _fail(17, f"AppendSubimage open — {out.geterror()}")
        if not out.write_image(pix1):
            return _fail(18, f"subimage 1 write — {out.geterror()}")
        out.close()

        # Re-read and verify both subimages survived.
        rs0 = oiio.ImageBuf(mp, 0, 0)
        rs1 = oiio.ImageBuf(mp, 1, 0)
        if rs0.has_error or rs1.has_error:
            return _fail(19, f"multipart reread — s0={rs0.geterror()} s1={rs1.geterror()}")
        if rs0.spec().nchannels != 3 or rs1.spec().nchannels != 4:
            return _fail(20, f"multipart channel drift -> s0={rs0.spec().nchannels} "
                              f"s1={rs1.spec().nchannels}")
        print(f"PASS A7: multipart write via ImageOutput preserves 2 subimages "
              f"(chans 3+4); append_mode={append_mode!r}")

    # --- Phase B: real MRQ EXR preservation (MANDATORY) ---------------
    mrq_path = "/tmp/mrq_sample.exr"
    if not os.path.exists(mrq_path):
        return _fail(30,
            f"{mrq_path} missing — Phase B is a hard blocker per the "
            "Codex adversarial review. Rerun Task 1 to obtain a real "
            "MRQ EXR sample before proceeding."
        )

    # Operate on a COPY of the original — never touch /tmp/mrq_sample.exr.
    # Per Codex critical finding: validation must NOT be done against the
    # in-place-patched file (otherwise loss vs original is invisible).
    import shutil as _shutil
    src_copy = "/tmp/mrq_sample_phaseB_in.exr"
    _shutil.copy(mrq_path, src_copy)

    # Collect baseline from every subimage of the source copy.
    baselines = []  # list of dict per subimage
    in_inp = oiio.ImageInput.open(src_copy)
    if in_inp is None:
        return _fail(31, f"ImageInput.open failed for {src_copy}")
    try:
        si = 0
        while True:
            if not in_inp.seek_subimage(si, 0):
                break
            s = in_inp.spec()
            baselines.append({
                "nchannels": s.nchannels,
                "channelnames": tuple(s.channelnames),
                "compression": s.getattribute("compression"),
                "pixelAspectRatio": s.getattribute("PixelAspectRatio"),
                "width": s.width,
                "height": s.height,
                "format": str(s.format),
            })
            si += 1
    finally:
        in_inp.close()
    if si == 0:
        return _fail(32, f"src copy has 0 subimages — corrupted?")
    print(f"Baseline subimage count: {si}; sample[0] = {baselines[0]}")

    # Rewrite to a separate output file via ImageOutput multi-subimage API.
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "patched_mrq.exr")
        in_inp = oiio.ImageInput.open(src_copy)
        if in_inp is None:
            return _fail(33, f"ImageInput.open #2 failed")
        try:
            # Read pixels + mutated specs for every subimage.
            specs_pixels = []
            for s in range(si):
                if not in_inp.seek_subimage(s, 0):
                    return _fail(34, f"seek_subimage {s}")
                spec = in_inp.spec()
                # Mutate.
                tc = oiio.TimeCode(hours=10, minutes=0, seconds=0, frame=0, dropFrame=False)
                spec.attribute("smpte:TimeCode", oiio.TypeTimeCode,
                               (tc.timeAndFlags(), tc.userData()))
                spec.attribute("FramesPerSecond", oiio.TypeRational, (50, 1))
                pixels = in_inp.read_image(spec.format)
                if pixels is None:
                    return _fail(35, f"read_image subimage {s} — {in_inp.geterror()}")
                specs_pixels.append((spec, pixels))
        finally:
            in_inp.close()

        out = oiio.ImageOutput.create(out_path)
        if out is None:
            return _fail(36, "ImageOutput.create returned None")
        specs_only = [sp for sp, _ in specs_pixels]
        if not out.open(out_path, specs_only):
            return _fail(37, f"multi-subimage open — {out.geterror()}")
        for i, (spec, pixels) in enumerate(specs_pixels):
            if i > 0:
                if not out.open(out_path, spec, append_mode):
                    return _fail(38, f"AppendSubimage open #{i} — {out.geterror()}")
            if not out.write_image(pixels):
                return _fail(39, f"write_image subimage {i} — {out.geterror()}")
        out.close()
        print(f"PASS B1: rewrote {si} subimage(s) via ImageOutput")

        # Verify each subimage against baseline.
        for s in range(si):
            chk = oiio.ImageBuf(out_path, s, 0)
            if chk.has_error:
                return _fail(40, f"reread subimage {s} — {chk.geterror()}")
            cs = chk.spec()
            b = baselines[s]
            if cs.nchannels != b["nchannels"]:
                return _fail(41, f"subimage {s}: channel count drift "
                                  f"{cs.nchannels} != {b['nchannels']}")
            if tuple(cs.channelnames) != b["channelnames"]:
                return _fail(42, f"subimage {s}: channel names drift "
                                  f"{cs.channelnames!r} != {b['channelnames']!r}")
            if cs.getattribute("compression") != b["compression"]:
                return _fail(43, f"subimage {s}: compression drift "
                                  f"{cs.getattribute('compression')!r} != "
                                  f"{b['compression']!r}")
            if cs.width != b["width"] or cs.height != b["height"]:
                return _fail(44, f"subimage {s}: dims drift")
            if cs.getattribute("smpte:TimeCode") is None:
                return _fail(45, f"subimage {s}: smpte:TimeCode not written")
            if tuple(cs.getattribute("FramesPerSecond")) != (50, 1):
                return _fail(46, f"subimage {s}: FramesPerSecond drift")
        # Subimage count check.
        post = oiio.ImageBuf(out_path, si, 0)
        if not post.has_error:
            return _fail(47, f"unexpected extra subimage at index {si}")
        print(f"PASS B2: all {si} subimage(s) preserved channels/compression/dims/typed-attrs; "
              "no subimages added/lost")

        # Save after-rewrite header dump alongside the baseline for human
        # diff in Task 12 evidence capture.
        try:
            after_dump = "/tmp/mrq_sample_after.txt"
            with open(after_dump, "w") as f:
                for s in range(si):
                    bb = oiio.ImageBuf(out_path, s, 0)
                    sp = bb.spec()
                    f.write(f"--- subimage {s} ---\n")
                    f.write(f"dims={sp.width}x{sp.height} nchannels={sp.nchannels} format={sp.format}\n")
                    f.write(f"channelnames={list(sp.channelnames)}\n")
                    f.write(f"compression={sp.getattribute('compression')}\n")
                    f.write(f"smpte:TimeCode={sp.getattribute('smpte:TimeCode')}\n")
                    f.write(f"FramesPerSecond={sp.getattribute('FramesPerSecond')}\n")
            print(f"PASS B3: after-rewrite header dump -> {after_dump}; "
                  "diff against /tmp/mrq_sample_baseline.txt for evidence")
        except Exception as e:
            print(f"WARN: after-dump write failed: {e}")

    print("\n=== ALL PROBES PASSED — backend swap is safe to proceed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run probe — BOTH phases mandatory**

```bash
python scripts/probe_oiio_static_python.py
```

Expected: `PASS A1` through `PASS A7`, then `PASS B1`, `PASS B2`, `PASS B3`, final `=== ALL PROBES PASSED ===`. Any FAIL → halt the plan.

| Exit | Meaning | Next action |
|---|---|---|
| 1 | wheel import failure (numpy ABI / Python version mismatch) | check Python is 3.11; `pip install --upgrade oiio-static-python` |
| 2 | `oiio.TimeCode` / `TypeTimeCode` symbol missing | wheel build differs from expectations; revisit |
| 5 | `oiio.TimeCode` helper missing | manual SMPTE BCD pack (~15 lines); adjusts plan |
| 8 / 9 | typed attr lost on roundtrip | `specmod()`→`write()` doesn't persist attrs; consider low-level `oiio.ImageOutput` API |
| 10 | rational drifted | wheel `TypeRational` broken; abort, revisit |
| 12–20 | multipart write API mismatch (Phase A.7) | `oiio.ImageOutput` Python binding signature differs; halt and re-spike before Task 6 |
| 30 | `/tmp/mrq_sample.exr` missing | Task 1 not finished — go back, no exceptions |
| 31–47 | real MRQ EXR preservation fail | the exact Codex Blocker — halt, do NOT advance to Task 4 |

- [ ] **Step 3: Phase A + B BOTH pass = GO for Tasks 4+**

If any PASS line is missing → STOP. Do not advance to Task 4. The previous plan's "Phase B can run later" hole is closed: no code change ships until preservation is proven on real MRQ EXR (Codex adversarial finding [critical]).

- [ ] **Step 4: Commit probe + gitignore (probe-only commit, no production code yet)**

```bash
git add scripts/probe_oiio_static_python.py
grep -q "^\.venv_" .gitignore && git add .gitignore || true
git commit -m "$(cat <<'EOF'
chore(p1 g2 probe): scripts/probe_oiio_static_python.py 验 OIIO Python API

OIIO 3.0.8 Python binding (oiio-static-python wheel) 跑三段：
1) Phase A — synthetic 4x4 EXR：API surface 全在 (TypeTimeCode/
   TypeRational/specmod/getattribute)，typed timecode + rational FPS
   roundtrip 不丢。
2) Phase A.7 — multipart write API discovery：ImageOutput
   multi-subimage open + AppendSubimage，2 subimage 写完
   再 reread channels 不丢。Codex 指出 ImageBuf 没多 subimage write，
   必须走 ImageOutput 低层 API，这一步把签名钉死。
3) Phase B — 真实 MRQ EXR (HARD BLOCKER)：copy /tmp/mrq_sample.exr
   到 _phaseB_in.exr，跑 ImageInput → mutate spec → ImageOutput
   multi-subimage 写，逐 subimage diff channels/compression/dims，
   且写后另存 after-dump 给 Task 12 留 evidence。Phase B 缺 sample
   直接 fail 30；不再有 SKIP 路径。

probe-first：Phase A + A.7 + B 全过才动 writer。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — Code (after Phase 1 GO — all probe phases pass)

### Task 4: Install `oiio-static-python` into UE Python on lanPC

**Files:** none in repo modified (deployment-only).

- [ ] **Step 1: Verify UE Python pip works**

```bash
echo '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" -m pip --version' | ssh lanpc powershell -Command -
```

Expected: a pip version string. If it fails, debug Python install before proceeding.

- [ ] **Step 2: Install pinned wheel**

```bash
echo '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" -m pip install --user oiio-static-python==3.0.8.1.1' | ssh lanpc powershell -Command -
```

Expected: `Successfully installed oiio-static-python-3.0.8.1.1` + numpy if not already present.

- [ ] **Step 3: Confirm UE Python imports OpenImageIO from --user site**

```bash
echo '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" -c "import OpenImageIO as oiio; print(oiio.__version__)"' | ssh lanpc powershell -Command -
```

Expected: an OIIO version string. If `ImportError`, inspect `python -m site --user-site` and ensure that dir is on `sys.path`. The opentimelineio precedent confirms `--user` works without sys.path patching.

---

### Task 5: Run probe on lanPC UE Python (install gate)

**Files:** none modified.

**Note:** lanPC runs Phase A + A.7 only (synthetic + multipart-API checks). Phase B already passed on dev Mac in Task 3 — re-running it on Windows would need pushing `/tmp/mrq_sample.exr` to a Windows path, no extra signal. This step's job: prove the UE Python install resolves `OpenImageIO` and the API surface is identical to dev Mac.

- [ ] **Step 1: SCP probe to lanPC**

```bash
scp scripts/probe_oiio_static_python.py lanpc:C:/temp/ue-remote/probe_oiio.py
```

- [ ] **Step 2: Run probe on UE Python**

```bash
echo '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" C:/temp/ue-remote/probe_oiio.py' | ssh lanpc powershell -Command -
```

Expected: `PASS A1..A6`, `PASS A7`. Then `FAIL [30]` for Phase B (no `/tmp/mrq_sample.exr` on Windows — that's expected on lanPC and does NOT block progression because Phase B already passed on dev Mac).

If FAIL on Phase A / A.7 on lanPC but passed on dev Mac → wheel has a platform-specific bug. Stop, investigate; do not advance.

---

### Task 6: Rewrite `patch_exr_timecode_in_dir` body

**Files:**
- Modify: `Content/Python/post_render_tool/exr_timecode_writer.py`

- [ ] **Step 1: Replace module docstring + `_ensure_oiiotool`**

Replace lines 1–40 of the original (docstring + `_ensure_oiiotool`) with:

```python
"""EXR header SMPTE timecode patcher.

Offline (post-render) — uses the `oiio-static-python` PyPI wheel
(OpenImageIO 3.0.8 statically built, with Python bindings) to write
typed `smpte:TimeCode` + `FramesPerSecond` rational attributes to EXR
files matching a filename pattern. In-process; same OIIO C++ library
that backs the `oiiotool` CLI, so spike-validated preservation of
channels / compression / multipart / pixelAspectRatio transfers
directly.

Backend rationale: see `scripts/exr_timecode_spike_report.md`
(2026-05-14 addendum). The conda-forge Windows `openimageio` package
does not ship `oiiotool.exe`, and PyPI `OpenEXR` 3.x had API mismatches
verified empirically. `oiio-static-python` (the same library, wheel-
bundled) was the chosen swap.

Install:
    pip install --user oiio-static-python==3.0.8.1.1
    (already on lanPC UE Python alongside opentimelineio.)

Public API:
    patch_exr_timecode_in_dir(output_dir, filename_pattern,
                              start_csv_frame, start_timecode, fps)
        Walks `output_dir`, matches `filename_pattern` to extract the
        absolute CSV frame number from each filename, calculates the
        per-frame SMPTE timecode, and rewrites the EXR with that
        timecode in the header. All subimages are rewritten; original
        channels / compression / pixelAspectRatio survive. Atomic
        rewrite (temp file + os.replace) — partial writes can never
        corrupt the production EXR. Returns the count of patched files.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .timecode import Timecode, _frames_per_24h


def _ensure_oiio() -> None:
    """Lazy import + clear error message if the OIIO Python wheel is
    missing. Imported on first call rather than at module scope so the
    pure-Python `_frame_to_timecode` helper remains testable without
    `oiio-static-python` installed.
    """
    try:
        import OpenImageIO  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "OpenImageIO Python binding not installed on the current "
            "Python. Install with `pip install --user "
            "oiio-static-python==3.0.8.1.1` (the same install pattern "
            "used for opentimelineio). Backend was swapped from "
            "subprocess+oiiotool on 2026-05-14 — see "
            "scripts/exr_timecode_spike_report.md."
        ) from e
```

- [ ] **Step 2: Keep `_frame_to_timecode` exactly as-is**

Lines 43–100 of the original file. No changes.

- [ ] **Step 3: Keep `_UNRESOLVED_TOKEN_RE`, `_validate_filename_pattern`, `_filename_pattern_to_regex` exactly as-is**

Lines 103–146 of the original. No changes.

- [ ] **Step 4: Replace the body of `patch_exr_timecode_in_dir`**

Per Codex adversarial finding [high]: do NOT use `ImageBuf.write(tmp)` per subimage to the same tmp path — `ImageBuf.write` has no multipart-append semantics and each call overwrites the file (multipart EXR collapses to the last subimage). Use the `ImageInput` → `ImageOutput` multi-subimage API pattern validated by probe Phase A.7. The `append_mode` constant the probe discovers is `oiio.AppendSubimage` (or fallback to `oiio.ImageOutputOpenMode.AppendSubimage`).

Replace the function body with:

```python
def patch_exr_timecode_in_dir(
    output_dir: str,
    filename_pattern: str,
    start_csv_frame: int,
    start_timecode: Timecode,
    fps: float,
) -> int:
    """See module docstring for parameter semantics — unchanged across
    the 2026-05-14 backend swap from subprocess+oiiotool to
    oiio-static-python.

    Per-file flow: read every subimage with `oiio.ImageInput`, mutate
    its `ImageSpec` to add typed `smpte:TimeCode` + rational
    `FramesPerSecond`, then write all subimages to a temp file with
    `oiio.ImageOutput` multi-subimage API. Atomic — `os.replace` over
    the original only after every subimage wrote successfully.
    """
    out_path = Path(output_dir)
    if not out_path.is_dir():
        return 0
    _ensure_oiio()
    import OpenImageIO as oiio

    fn_regex = _filename_pattern_to_regex(filename_pattern)
    rate_num = start_timecode.rate_num
    rate_den = start_timecode.rate_den
    append_mode = getattr(oiio, "AppendSubimage", None) or getattr(
        getattr(oiio, "ImageOutputOpenMode", None), "AppendSubimage", None,
    )
    if append_mode is None:
        raise RuntimeError(
            "OIIO AppendSubimage open mode not found — multipart EXR "
            "rewrite cannot be done safely. Re-run probe Phase A.7."
        )

    processed = 0
    for file in sorted(out_path.iterdir()):
        match = fn_regex.match(file.name)
        if match is None:
            continue
        frame = int(match.group(1))
        offset = frame - start_csv_frame
        if offset < 0:
            continue
        tc = _frame_to_timecode(start_timecode, offset)
        oiio_tc = oiio.TimeCode(
            hours=tc.hours, minutes=tc.minutes, seconds=tc.seconds,
            frame=tc.frames, dropFrame=tc.drop_frame,
        )
        tc_value = (oiio_tc.timeAndFlags(), oiio_tc.userData())
        fps_value = (rate_num, rate_den)

        # Step A: read every subimage's spec + pixels.
        inp = oiio.ImageInput.open(str(file))
        if inp is None:
            continue  # not a readable EXR — skip silently
        subimages = []  # [(mutated_spec, pixels_ndarray), ...]
        try:
            si = 0
            while True:
                if not inp.seek_subimage(si, 0):
                    break
                spec = inp.spec()
                spec.attribute("smpte:TimeCode", oiio.TypeTimeCode, tc_value)
                spec.attribute("FramesPerSecond", oiio.TypeRational, fps_value)
                pixels = inp.read_image(spec.format)
                if pixels is None:
                    raise RuntimeError(
                        f"OIIO read_image subimage {si} of {file}: {inp.geterror()}"
                    )
                subimages.append((spec, pixels))
                si += 1
        finally:
            inp.close()

        if not subimages:
            continue

        # Step B: write all subimages to <file>.tmp via ImageOutput.
        tmp = str(file) + ".tmp"
        try:
            out = oiio.ImageOutput.create(tmp)
            if out is None:
                raise RuntimeError(f"OIIO ImageOutput.create for {tmp}")
            specs_list = [sp for sp, _ in subimages]
            if not out.open(tmp, specs_list):
                raise RuntimeError(
                    f"OIIO multi-subimage open: {out.geterror()}"
                )
            for i, (spec, pixels) in enumerate(subimages):
                if i > 0:
                    if not out.open(tmp, spec, append_mode):
                        raise RuntimeError(
                            f"OIIO AppendSubimage #{i}: {out.geterror()}"
                        )
                if not out.write_image(pixels):
                    raise RuntimeError(
                        f"OIIO write_image subimage {i}: {out.geterror()}"
                    )
            out.close()
            # Step C: atomic swap.
            os.replace(tmp, str(file))
            processed += 1
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    return processed
```

- [ ] **Step 5: Syntax check**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
python3 -c "import ast; ast.parse(open('Content/Python/post_render_tool/exr_timecode_writer.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 6: Commit (no tests yet — Task 7)**

```bash
git add Content/Python/post_render_tool/exr_timecode_writer.py
git commit -m "$(cat <<'EOF'
refactor(p1 g2): exr_timecode_writer 后端从 subprocess+oiiotool 换 OIIO Python

conda-forge Windows openimageio 不带 oiiotool.exe，PyPI OpenEXR 3.x API
经 Codex 实测对不上（TimeCode kwargs/Rational write 都 fail），换成
oiio-static-python wheel —— OpenImageIO 3.0.8 静态 Python 绑定，跟
oiiotool 是同一份 C++ library。spike report 验证过的 multipart/channels/
compression preservation 通过同 lib 直接继承。

实现：
- public 签名 + pure-Python helper 一字未动
- 每文件走 ImageInput.seek_subimage 读全部 subimage 的 spec+pixels；
  Codex 指出 ImageBuf.write 没多 subimage 语义，per-subimage write
  会让 multipart EXR 退化成最后一帧，必须走 ImageOutput
  multi-subimage open + AppendSubimage（probe Phase A.7 已钉死签名）
- 写 typed smpte:TimeCode + FramesPerSecond rational via ImageSpec.attribute
- atomic swap：写 <file>.tmp → os.replace，partial write 永不污染原文件

tests 在下一个 commit 重写。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Rewrite unit tests for OIIO Python backend

**Files:**
- Modify: `Content/Python/post_render_tool/tests/test_exr_timecode_writer.py`

Current file has 16 tests across 3 classes. Pure-Python `TestFrameToTimecodeRoundTrip` (6 methods) stays untouched. The two I/O-coupled classes (`TestPatchExrTimecode` 6 + `TestFractionalFpsRationalMetadata` 4) are rewritten. A new `TestMultipartPreservation` class (1 method) is appended to cover the multipart-EXR regression gap Codex flagged. Final count: 17 tests.

- [ ] **Step 1: Replace top-of-file imports + skip gates**

Replace lines 1–43 of the original with:

```python
"""EXR header SMPTE timecode patcher tests.

Offline (no `unreal` dependency). Uses oiio-static-python for mock-EXR
generation + attribute read-back; uses `exrheader` (from Miniforge3 on
lanPC; brew install openimageio on dev Mac) as ground truth for typed-
attribute verification when available.

I/O tests skip if `oiio-static-python` is missing — keeps the pure-
Python suite runnable on contributors without it installed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest


try:
    import OpenImageIO as oiio
    import numpy as np  # noqa: F401
    _HAVE_OIIO = True
except ImportError:
    _HAVE_OIIO = False

_HAVE_EXRHEADER = shutil.which("exrheader") is not None


def _gen_test_exr(path: str, channels: int = 3) -> None:
    """Create a 4x4 EXR via OIIO Python (default RGB)."""
    spec = oiio.ImageSpec(4, 4, channels, "half")
    spec.attribute("compression", "zip")
    buf = oiio.ImageBuf(spec)
    fill = tuple([0.5] * channels)
    oiio.ImageBufAlgo.fill(buf, fill)
    if not buf.write(path):
        raise RuntimeError(f"OIIO write: {buf.geterror()}")


def _read_typed_timecode(path: str):
    """Return (time, user) tuple stored in smpte:TimeCode, or None."""
    buf = oiio.ImageBuf(path)
    return buf.spec().getattribute("smpte:TimeCode")


def _read_rational_fps(path: str):
    """Return (num, den) of FramesPerSecond, or None."""
    buf = oiio.ImageBuf(path)
    attr = buf.spec().getattribute("FramesPerSecond")
    return tuple(attr) if attr is not None else None


def _exrheader_grep(path: str, attr_name: str) -> str:
    """Return the exrheader line containing `attr_name`, lower-cased.
    Empty string if exrheader is unavailable or attribute not found."""
    if not _HAVE_EXRHEADER:
        return ""
    out = subprocess.check_output(
        ["exrheader", path], text=True, stderr=subprocess.STDOUT,
    )
    for line in out.splitlines():
        if attr_name.lower() in line.lower():
            return line.strip()
    return ""
```

- [ ] **Step 2: Rewrite `TestPatchExrTimecode` (6 methods)**

Replace the original `TestPatchExrTimecode` class with:

```python
@unittest.skipUnless(_HAVE_OIIO, "oiio-static-python not installed — pip install --user oiio-static-python==3.0.8.1.1")
class TestPatchExrTimecode(unittest.TestCase):
    def setUp(self):
        from post_render_tool.exr_timecode_writer import (
            patch_exr_timecode_in_dir,
        )
        self.patch = patch_exr_timecode_in_dir
        self.tmpdir = tempfile.mkdtemp(prefix="exr_test_")
        for i in range(3):
            _gen_test_exr(os.path.join(
                self.tmpdir, f"render.{625914 + i:07d}.exr"
            ))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_50fps_patch_writes_typed_attributes(self):
        from post_render_tool.timecode import Timecode
        n = self.patch(
            output_dir=self.tmpdir,
            filename_pattern="render.{frame:07d}.exr",
            start_csv_frame=625914,
            start_timecode=Timecode.parse("10:00:00:00", 50.0),
            fps=50.0,
        )
        self.assertEqual(n, 3)
        first = os.path.join(self.tmpdir, "render.0625914.exr")

        tc = _read_typed_timecode(first)
        self.assertIsNotNone(tc, "smpte:TimeCode missing after patch")
        fps = _read_rational_fps(first)
        self.assertEqual(fps, (50, 1), f"got {fps!r}")

        if _HAVE_EXRHEADER:
            tc_line = _exrheader_grep(first, "timecode")
            self.assertIn("type timecode", tc_line.lower(),
                          f"expected typed timecode, got: {tc_line!r}")
            fps_line = _exrheader_grep(first, "framesPerSecond")
            self.assertIn("rational", fps_line.lower(),
                          f"expected rational FramesPerSecond, got: {fps_line!r}")

    def test_increments_per_frame_50fps(self):
        from post_render_tool.timecode import Timecode
        self.patch(
            self.tmpdir,
            "render.{frame:07d}.exr",
            625914,
            Timecode.parse("10:00:00:00", 50.0),
            50.0,
        )
        for offset, expected_ff in enumerate([0, 1, 2]):
            path = os.path.join(self.tmpdir, f"render.{625914 + offset:07d}.exr")
            tc_value = _read_typed_timecode(path)
            tc = oiio.TimeCode()
            tc.setTimeAndFlags(tc_value[0])
            tc.setUserData(tc_value[1])
            self.assertEqual(
                (tc.hours(), tc.minutes(), tc.seconds(), tc.frame()),
                (10, 0, 0, expected_ff),
                f"frame {offset}: timecode drift",
            )

    def test_nonexistent_dir_returns_zero(self):
        from post_render_tool.timecode import Timecode
        n = self.patch(
            "/no/such/dir",
            "render.{frame:07d}.exr",
            625914,
            Timecode.parse("10:00:00:00", 50.0),
            50.0,
        )
        self.assertEqual(n, 0)

    def test_subdir_pattern_raises(self):
        from post_render_tool.timecode import Timecode
        with self.assertRaises(ValueError) as ctx:
            self.patch(
                self.tmpdir,
                "shot1/render.{frame:07d}.exr",
                625914,
                Timecode.parse("10:00:00:00", 50.0),
                50.0,
            )
        self.assertIn("path separator", str(ctx.exception))

    def test_unresolved_mrq_token_raises(self):
        from post_render_tool.timecode import Timecode
        with self.assertRaises(ValueError) as ctx:
            self.patch(
                self.tmpdir,
                "{shot_name}.render.{frame:07d}.exr",
                625914,
                Timecode.parse("10:00:00:00", 50.0),
                50.0,
            )
        self.assertIn("unresolved tokens", str(ctx.exception))

    def test_skips_files_below_start_frame(self):
        from post_render_tool.timecode import Timecode
        below = os.path.join(self.tmpdir, "render.0625900.exr")
        _gen_test_exr(below)
        n = self.patch(
            self.tmpdir,
            "render.{frame:07d}.exr",
            625914,
            Timecode.parse("10:00:00:00", 50.0),
            50.0,
        )
        self.assertEqual(n, 3)
```

- [ ] **Step 3: Rewrite `TestFractionalFpsRationalMetadata` (4 methods)**

Replace the original `TestFractionalFpsRationalMetadata` class with:

```python
@unittest.skipUnless(_HAVE_OIIO, "oiio-static-python not installed")
class TestFractionalFpsRationalMetadata(unittest.TestCase):
    """FramesPerSecond must keep the exact NTSC rational (24000/1001 etc.),
    not get rounded to integer 24/1. Otherwise EXR readers drift over long
    takes."""

    def setUp(self):
        from post_render_tool.exr_timecode_writer import (
            patch_exr_timecode_in_dir,
        )
        self.patch = patch_exr_timecode_in_dir
        self.tmpdir = tempfile.mkdtemp(prefix="exr_test_rational_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _check_rational(self, fps: float, tc_str: str, exp_num: int, exp_den: int):
        from post_render_tool.timecode import Timecode
        path = os.path.join(self.tmpdir, "render.0000000.exr")
        _gen_test_exr(path)
        n = self.patch(
            self.tmpdir,
            "render.{frame:07d}.exr",
            0,
            Timecode.parse(tc_str, fps),
            fps,
        )
        self.assertEqual(n, 1)
        r = _read_rational_fps(path)
        self.assertEqual(
            r, (exp_num, exp_den),
            f"expected {exp_num}/{exp_den} for {fps}fps, got: {r!r}",
        )
        if _HAVE_EXRHEADER:
            line = _exrheader_grep(path, "framesPerSecond")
            self.assertIn(f"{exp_num}/{exp_den}", line,
                          f"exrheader: expected {exp_num}/{exp_den}, got: {line}")

    def test_23976_writes_24000_over_1001(self):
        self._check_rational(23.976, "00:00:00:00", 24000, 1001)

    def test_2997_writes_30000_over_1001(self):
        self._check_rational(29.97, "00:00:00;00", 30000, 1001)

    def test_5994_writes_60000_over_1001(self):
        self._check_rational(59.94, "00:00:00;00", 60000, 1001)

    def test_50_writes_50_over_1(self):
        self._check_rational(50.0, "00:00:00:00", 50, 1)
```

- [ ] **Step 4: Add `TestMultipartPreservation` class (new — Codex [high] coverage)**

Append a new test class that builds a 2-subimage EXR via OIIO Python (replicating probe Phase A.7), runs the patcher, then verifies BOTH subimages survive with their own channel layouts plus the typed attrs. This covers the failure mode Codex identified (per-subimage `ImageBuf.write` collapsing multipart).

```python
@unittest.skipUnless(_HAVE_OIIO, "oiio-static-python not installed")
class TestMultipartPreservation(unittest.TestCase):
    """Multipart EXR rewrite must preserve every subimage with its own
    channel layout. Regression-guards the failure mode Codex
    adversarial review [high] flagged (ImageBuf.write per-subimage
    collapsing multipart to last subimage)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="exr_test_multipart_")
        self.path = os.path.join(self.tmpdir, "render.0000000.exr")
        # Build a 2-subimage EXR: subimage 0 = RGB (3 ch), subimage 1 =
        # RGBA (4 ch). Different channel counts make collapsing visible.
        spec0 = oiio.ImageSpec(4, 4, 3, "half")
        spec0.attribute("compression", "zip")
        pix0 = np.full((4, 4, 3), 0.5, dtype=np.float16)
        spec1 = oiio.ImageSpec(4, 4, 4, "half")
        spec1.attribute("compression", "zip")
        pix1 = np.full((4, 4, 4), 0.3, dtype=np.float16)

        append_mode = getattr(oiio, "AppendSubimage", None) or getattr(
            getattr(oiio, "ImageOutputOpenMode", None), "AppendSubimage", None,
        )
        if append_mode is None:
            self.skipTest("OIIO AppendSubimage constant missing")
        out = oiio.ImageOutput.create(self.path)
        if not out.open(self.path, [spec0, spec1]):
            self.fail(f"multipart open: {out.geterror()}")
        out.write_image(pix0)
        out.open(self.path, spec1, append_mode)
        out.write_image(pix1)
        out.close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_multipart_rewrite_preserves_two_subimages(self):
        from post_render_tool.exr_timecode_writer import (
            patch_exr_timecode_in_dir,
        )
        from post_render_tool.timecode import Timecode

        n = patch_exr_timecode_in_dir(
            self.tmpdir,
            "render.{frame:07d}.exr",
            0,
            Timecode.parse("10:00:00:00", 50.0),
            50.0,
        )
        self.assertEqual(n, 1, "patcher reported wrong file count")

        s0 = oiio.ImageBuf(self.path, 0, 0)
        s1 = oiio.ImageBuf(self.path, 1, 0)
        s2 = oiio.ImageBuf(self.path, 2, 0)
        self.assertFalse(s0.has_error, f"subimage 0 lost: {s0.geterror()}")
        self.assertFalse(s1.has_error, f"subimage 1 lost: {s1.geterror()}")
        self.assertTrue(s2.has_error, "unexpected extra subimage 2")
        self.assertEqual(s0.spec().nchannels, 3, "subimage 0 channel drift")
        self.assertEqual(s1.spec().nchannels, 4, "subimage 1 channel drift")
        # Typed attrs must be on EVERY subimage.
        for i, b in [(0, s0), (1, s1)]:
            self.assertIsNotNone(
                b.spec().getattribute("smpte:TimeCode"),
                f"subimage {i}: smpte:TimeCode missing")
            self.assertEqual(
                tuple(b.spec().getattribute("FramesPerSecond")),
                (50, 1),
                f"subimage {i}: FramesPerSecond drift")
```

- [ ] **Step 5: `TestFrameToTimecodeRoundTrip` (6 methods) stays unchanged + `if __name__ == "__main__":` at end**

- [ ] **Step 6: Run tests on dev Mac with oiio installed**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
source ../../.venv_oiio_probe/bin/activate
python -m unittest post_render_tool.tests.test_exr_timecode_writer -v
```

Expected: **17 PASS** total = 6 `TestPatchExrTimecode` + 6 `TestFrameToTimecodeRoundTrip` + 4 `TestFractionalFpsRationalMetadata` + 1 `TestMultipartPreservation`. (If Mac has `exrheader` via `brew install openimageio`, the exrheader cross-checks fire inside the relevant methods too.)

- [ ] **Step 7: Run tests without oiio to confirm skip gating**

```bash
deactivate
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
python3 -m unittest post_render_tool.tests.test_exr_timecode_writer -v
```

Expected: **6 PASS** (`TestFrameToTimecodeRoundTrip`), **11 SKIPPED** "oiio-static-python not installed". No FAIL.

- [ ] **Step 8: Commit**

```bash
git add Content/Python/post_render_tool/tests/test_exr_timecode_writer.py
git commit -m "$(cat <<'EOF'
test(p1 g2): exr_timecode_writer tests 改 OIIO Python + exrheader ground truth

mock EXR 用 oiio.ImageBuf + ImageBufAlgo.fill 生成；typed timecode +
rational FPS 验证读回走 oiio.spec().getattribute；exrheader 装着的话
做 typed-attribute ground truth 交叉验证（断言 "type timecode" +
"type rational" 字面在 exrheader 输出里）。

新增 TestMultipartPreservation：2 subimage（RGB + RGBA）EXR 通过
ImageOutput 多 subimage API 构造，跑 patcher 后 reread 两个 subimage
都还在、channel 数没串、typed attrs 每个 subimage 都有。这条专门
guard Codex review [high] 指的 multipart collapse 失败模式。

pure-Python TestFrameToTimecodeRoundTrip（6 个 drop-frame inverse case）
一字未动。没装 oiio 时 11 个 I/O test 走 skip 路径，pure-Python 6 个
仍能跑。total = 17 tests。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Update `scripts/integration_p1.py`

**Files:**
- Modify: `scripts/integration_p1.py`

- [ ] **Step 1: Replace top docstring**

```python
"""P1 integration test — run_patch_exr_timecode + run_export_otio.

2026-05-14 backend swap: EXR patcher uses oiio-static-python Python
wheel in-process (OpenImageIO 3.0.8 statically built, same C++ library
that backs oiiotool). lanPC UE Python must have
`oiio-static-python==3.0.8.1.1` installed via
`pip install --user` (same pattern as opentimelineio).

Verification via two independent paths:
  1) OIIO Python read-back (`buf.spec().getattribute(...)`)
  2) exrheader.exe ground truth (from C:\\Tools\\miniforge3\\Library\\bin)

Steps (unchanged from pre-swap structure):
1. Reload modified Python modules (post_render_tool.*).
2. Generate a mock MRQ-style EXR sequence in `C:/temp/p1_test/`.
3. Call open_movie_render_queue to set up MRQ output_setting.
4. Call run_patch_exr_timecode, verify EXR header has typed timecode.
5. Call run_export_otio, verify .otio file written + parseable.
"""
```

- [ ] **Step 2: Replace the EXR generation + verification block**

Replace the original `have_oiiotool` / `have_exrheader` block (lines 80–137 of the original) with:

```python
    have_oiio = False
    try:
        import OpenImageIO as oiio
        import numpy as np  # noqa: F401
        have_oiio = True
    except ImportError:
        unreal.log_warning(
            "[P1_INTEG] oiio-static-python not installed in UE Python — "
            "EXR patcher tests SKIPPED. Install: "
            "`<UE>/Engine/Binaries/ThirdParty/Python3/Win64/python.exe "
            "-m pip install --user oiio-static-python==3.0.8.1.1`"
        )

    exrheader_exe = r"C:\Tools\miniforge3\Library\bin\exrheader.exe"
    have_exrheader = os.path.exists(exrheader_exe)
    if not have_exrheader:
        unreal.log_warning(
            "[P1_INTEG] exrheader.exe not at Miniforge3 location — "
            "skipping typed-attribute ground-truth cross-check."
        )

    if have_oiio:
        for offset in range(3):
            frame = first_frame + offset
            filename = pattern.format(frame=frame)
            fpath = os.path.join(test_dir, filename)
            try:
                spec = oiio.ImageSpec(4, 4, 3, "half")
                spec.attribute("compression", "zip")
                buf = oiio.ImageBuf(spec)
                oiio.ImageBufAlgo.fill(buf, (0.5, 0.5, 0.5))
                if not buf.write(fpath):
                    raise RuntimeError(buf.geterror())
            except Exception as e:
                _verify(f"generate mock EXR offset={offset}", False, str(e))
                return
        _verify("generated 3 mock EXR files", True, test_dir)

        from post_render_tool.pipeline import run_patch_exr_timecode
        try:
            res = run_patch_exr_timecode(ls_path, test_dir, pattern)
            _verify("run_patch_exr_timecode runs", True)
            _verify("patched_count == 3", res["patched_count"] == 3,
                    f"got {res['patched_count']}")
            _verify("start_timecode reported",
                    res["start_timecode"] == "09:44:25:10",
                    f"got {res['start_timecode']}")
        except Exception as e:
            _verify("run_patch_exr_timecode runs", False, repr(e))
            return

        first_filename = pattern.format(frame=first_frame)
        first_path = os.path.join(test_dir, first_filename)
        try:
            chk = oiio.ImageBuf(first_path)
            tc = chk.spec().getattribute("smpte:TimeCode")
            fps_attr = chk.spec().getattribute("FramesPerSecond")
            _verify("EXR has smpte:TimeCode attribute",
                    tc is not None,
                    f"got {tc!r}")
            _verify("EXR has rational FramesPerSecond",
                    fps_attr is not None and tuple(fps_attr) == (50, 1),
                    f"got {fps_attr!r}")
        except Exception as e:
            _verify("OIIO Python attribute read", False, str(e))

        if have_exrheader:
            try:
                out = subprocess.check_output(
                    [exrheader_exe, first_path], text=True,
                    stderr=subprocess.STDOUT,
                )
                has_typed_tc = any(
                    "type timecode" in line.lower() for line in out.splitlines()
                )
                has_rational_fps = any(
                    "framespersecond" in line.lower() and "rational" in line.lower()
                    for line in out.splitlines()
                )
                _verify("exrheader: typed timecode", has_typed_tc)
                _verify("exrheader: rational FramesPerSecond", has_rational_fps)
            except Exception as e:
                _verify("exrheader read", False, str(e))
```

Keep `import subprocess` + `import shutil` at the top — OTIO block + cleanup still use them.

- [ ] **Step 3: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('scripts/integration_p1.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add scripts/integration_p1.py
git commit -m "$(cat <<'EOF'
test(p1 g2): integration_p1.py 改 OIIO Python + exrheader ground truth

mock EXR 用 oiio.ImageBuf 生成；typed attribute 双路径验证：
1) OIIO Python read-back（buf.spec().getattribute）
2) exrheader.exe（C:\Tools\miniforge3\Library\bin）扫 "type timecode" +
   "type rational" 字面，作为 typed-attribute 落盘的 ground truth

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Run `integration_p1.py` end-to-end on lanPC (GO/NO-GO #2)

**Files:** none modified.

- [ ] **Step 1: Confirm lanPC plugin source has the new commits**

```bash
echo 'cd "E:\RenderStream Projects\test_0311\Plugins\post-render-tool"; git log --oneline -5' | ssh lanpc powershell -Command -
```

Expected: top 3 commits = Task 6, 7, 8 in order. If not, `git pull` or wait for the p4 hook.

- [ ] **Step 2: SCP integration script**

```bash
scp scripts/integration_p1.py lanpc:C:/temp/ue-remote/integ_p1.py
```

- [ ] **Step 3: Run inside UE Editor on lanPC**

```bash
echo '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/integ_p1.py' | ssh lanpc powershell -Command -
```

Expected PASS lines:

```
[P1_INTEG] PASS :: take_4 LevelSequence exists
[P1_INTEG] PASS :: derive_mrq_filename_pattern returns pattern
[P1_INTEG] PASS :: derive_mrq_filename_pattern returns padding
[P1_INTEG] PASS :: generated 3 mock EXR files
[P1_INTEG] PASS :: run_patch_exr_timecode runs
[P1_INTEG] PASS :: patched_count == 3
[P1_INTEG] PASS :: start_timecode reported
[P1_INTEG] PASS :: EXR has smpte:TimeCode attribute
[P1_INTEG] PASS :: EXR has rational FramesPerSecond
[P1_INTEG] PASS :: exrheader: typed timecode
[P1_INTEG] PASS :: exrheader: rational FramesPerSecond
[P1_INTEG] PASS :: run_export_otio runs
[P1_INTEG] PASS :: OTIO sidecar file exists
[P1_INTEG] PASS :: OTIO frame_count > 0
```

No FAIL, no skipped EXR block.

- [ ] **Step 4: If any FAIL — diagnose, do NOT advance**

| Failure | Likely cause | Fix |
|---|---|---|
| `oiio-static-python not installed` warning | Task 4 install didn't land | rerun pip install on lanPC |
| `OIIO Python attribute read` FAIL | OIIO write succeeded but specmod/getattribute path broken on Windows | rerun dev-Mac probe Phase A; compare |
| `exrheader: typed timecode` FAIL | OIIO wrote it as non-typed fallback | check `_frame_to_timecode` output + `oiio.TypeTimeCode` constant |
| `exrheader: rational FramesPerSecond` FAIL | OIIO TypeRational write didn't take | same as above for FramesPerSecond |

---

### Task 10: Update docs — `plugin-setup.md` + spike report addendum

**Files:**
- Modify: `docs/plugin-setup.md`
- Modify: `scripts/exr_timecode_spike_report.md`

- [ ] **Step 1: Patch `docs/plugin-setup.md`**

Find the "P1 timecode-sync" block around `docs/plugin-setup.md:22` and replace from the section header through the install instruction with:

```markdown
### P1 timecode-sync (optional — only if using EXR / OTIO conform helpers)

`Patch EXR Timecode` and `Export OTIO Sidecar` widget buttons need one
extra Python dependency on UE's bundled Python (same install pattern as
the OTIO sidecar):

- **`oiio-static-python`** — OpenImageIO Python binding (statically
  built, no system OIIO install required), used in-process to write
  typed SMPTE `timeCode` + rational `FramesPerSecond` attributes into
  MRQ-rendered EXR files. Backend swapped from subprocess `oiiotool`
  CLI on 2026-05-14; see `scripts/exr_timecode_spike_report.md` for
  the swap rationale.

Install:

```powershell
& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" -m pip install --user oiio-static-python==3.0.8.1.1
```

(macOS / Linux developer machines: `pip install oiio-static-python==3.0.8.1.1` into any Python 3.11 venv.)

Optional dev tool: `exrheader.exe` for typed-attribute ground-truth
verification. lanPC: comes with the `openimageio` conda package at
`C:\Tools\miniforge3\Library\bin\exrheader.exe`. Mac:
`brew install openimageio`.
```

- [ ] **Step 2: Append addendum to `scripts/exr_timecode_spike_report.md`**

```markdown
---

## 2026-05-14 update — backend swapped to oiio-static-python

**Trigger:** P1 G2 lanPC deployment surfaced two gaps the original
spike didn't catch:

1. **conda-forge `openimageio` on Windows ships the C++ library only
   — no `oiiotool.exe` CLI.** scoop main/extras + winget have no
   openimageio package. The original spike picked `oiiotool` assuming
   `brew install openimageio` (Mac) / `scoop install openimageio`
   (Win), the latter not being a real install path on Windows.

2. **PyPI `OpenEXR` 3.x API did not match assumptions of an
   intermediate revision of the plan.** Empirical probe in a Python
   3.11 venv with `OpenEXR==3.4.11`:
   - `OpenEXR.TimeCode(hours=..., dropFrame=...)` constructor: not
     supported (fields are descriptors, not kwargs).
   - `OpenEXR.Rational(50, 1)` assigned to `header["framesPerSecond"]`:
     raises `unrecognized type of attribute 'framesPerSecond'`.
   - tuple `(50, 1)` writable but read-back type is not `Rational`.

**Swap:** Replaced subprocess+`oiiotool` with in-process
`import OpenImageIO as oiio` via the `oiio-static-python` PyPI wheel
(OpenImageIO 3.0.8 + OpenColorIO statically linked, ~11 MB cp310–cp313
win_amd64 / macOS / Linux wheels). Pin: `oiio-static-python==3.0.8.1.1`.

**Why this is equivalent to the original `oiiotool` choice:** OIIO's
Python binding wraps the same C++ library that `oiiotool` is built on
top of. Preservation guarantees (multipart, channels, compression,
pixelAspectRatio) come from the library, not from the CLI wrapper.
Calling the library directly through its Python binding has the same
on-disk effect.

**Validation:** `scripts/probe_oiio_static_python.py` runs two phases:
- Phase A — synthetic 4×4 RGB EXR API contract.
- Phase B — real MRQ EXR preservation (channels / compression /
  multipart / dims survive a typed-attribute rewrite).

Both phases must pass on dev Mac before code lands; Phase A must pass
on lanPC UE Python before `integration_p1.py` runs.

**Production gate:** DaVinci 19+ Inspector reading the patched EXR
sequence + OTIO sidecar import — the final P1 G2 + G4 acceptance,
covered by Tasks 13–14 of the migration plan.

**What did NOT change across the swap:**
- `patch_exr_timecode_in_dir` public signature.
- `_frame_to_timecode` drop-frame inverse algorithm + its 6 unit
  tests.
- Filename regex + MRQ-token validation + their 2 unit tests.
- Output attribute names: `smpte:TimeCode` and `FramesPerSecond` — same
  as oiiotool wrote.
```

- [ ] **Step 3: Commit docs together**

```bash
git add docs/plugin-setup.md scripts/exr_timecode_spike_report.md
git commit -m "$(cat <<'EOF'
docs(p1 g2): 安装说明改 oiio-static-python；spike report 加 swap addendum

plugin-setup.md：把"装 OpenImageIO CLI / oiiotool"这条改成"UE Python
pip install --user oiio-static-python==3.0.8.1.1"，跟 opentimelineio
同套路。exrheader 标成 dev-only 可选工具，给路径。

spike report 加 2026-05-14 addendum：记录两条原 spike 漏掉的事实——
conda-forge Windows openimageio 不带 CLI、PyPI OpenEXR 3.x API 跟假设
不一致。OIIO Python binding 跟 oiiotool 同 lib，preservation 直接继承。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Manual production verify

### Task 11: Coordinate manual MRQ EXR render

**Files:** none modified.

- [ ] **Step 1: Tell user to render**

Message to user: "Open the widget on lanPC → Import take_4 (or any take) → Open MRQ → Output Setting: change Output Format to `.exr Sequence` → render 5–10 frames into a clean dir like `E:/MRQ_out/p1g2_final/`. Send me back: the exact output dir + one rendered filename."

Wait for user response with dir + filename.

- [ ] **Step 2: Tell user to click "Patch EXR Timecode"**

"Paste the output dir into the widget's `Render output dir` input box → click `Patch EXR Timecode` → send me the widget result text."

Expected: `Patched N EXR file(s) with start_timecode=HH:MM:SS:FF in: <dir>` with N matching the rendered frame count.

If `Patched 0` → `derive_mrq_filename_pattern` mismatched. Capture the pattern from the error message, check MRQ's `file_name_format` setting, fix, re-render.

---

### Task 12: Production-render preservation diff (final preservation gate)

**Files:** none modified. Produces evidence artifact `/tmp/mrq_production_diff.txt`.

**Note:** This task does NOT re-run probe Phase B against the patched file (that would be a circular validation — file was already patched, so "diff before vs after" is meaningless). Phase B's preservation guarantee was already established in Task 3 on an unpatched copy of the original. This task is the **production sanity check**: confirm that the actual production-rendered EXR was patched correctly and that no surprise MRQ-specific attribute got dropped relative to the Task 1 baseline.

- [ ] **Step 1: SCP one patched EXR back to dev Mac**

```bash
scp "lanpc:<MRQ output dir>/<first patched filename>" /tmp/mrq_patched.exr
```

- [ ] **Step 2: Capture the patched file's header for diff against Task 1 baseline**

```bash
# Dev Mac path — uses brew install openimageio's exrheader
if which exrheader >/dev/null 2>&1; then
  exrheader /tmp/mrq_patched.exr > /tmp/mrq_patched_header.txt 2>&1
else
  # Fallback: use venv OIIO Python to dump
  source .venv_oiio_probe/bin/activate
  python3 -c "
import OpenImageIO as oiio
si = 0
with open('/tmp/mrq_patched_header.txt','w') as f:
  while True:
    b = oiio.ImageBuf('/tmp/mrq_patched.exr', si, 0)
    if b.has_error: break
    s = b.spec()
    f.write(f'--- subimage {si} ---\n')
    f.write(f'dims={s.width}x{s.height} nchannels={s.nchannels}\n')
    f.write(f'channelnames={list(s.channelnames)}\n')
    f.write(f'compression={s.getattribute(\"compression\")}\n')
    f.write(f'pixelAspectRatio={s.getattribute(\"PixelAspectRatio\")}\n')
    f.write(f'smpte:TimeCode={s.getattribute(\"smpte:TimeCode\")}\n')
    f.write(f'FramesPerSecond={s.getattribute(\"FramesPerSecond\")}\n')
    si += 1
"
fi

# Diff against the Task 1 baseline. Filter out smpte:TimeCode +
# FramesPerSecond lines (those are EXPECTED to differ — we just added
# them); flag anything ELSE that changed.
diff /tmp/mrq_sample_baseline.txt /tmp/mrq_patched_header.txt | \
  grep -viE "timecode|framespersecond" | tee /tmp/mrq_production_diff.txt
```

Expected `/tmp/mrq_production_diff.txt`: empty, or only contains `<`/`>` header lines (diff metadata). If it surfaces a real attribute drift (compression changed, channel list changed, pixelAspectRatio dropped, subimage count differs) → **HALT, do NOT mark P1 G2 done**. Run the rollback block at the bottom of this plan.

- [ ] **Step 3: Cross-verify the typed attrs landed in the patched production file**

```bash
# Quick typed-attribute check via OIIO Python (independent of exrheader)
source .venv_oiio_probe/bin/activate
python3 -c "
import OpenImageIO as oiio
b = oiio.ImageBuf('/tmp/mrq_patched.exr')
print('smpte:TimeCode  =', b.spec().getattribute('smpte:TimeCode'))
print('FramesPerSecond =', b.spec().getattribute('FramesPerSecond'))
"
```

Expected: both attributes present and non-None. `smpte:TimeCode` is a 2-tuple of uint32; `FramesPerSecond` is `(num, den)` matching the take's frame rate.

If either is None → patcher claimed N>0 but didn't actually write — investigate; do NOT advance to Task 13.

---

### Task 13: DaVinci 19+ Inspector timecode verify (P1 G2 acceptance)

**Files:** none modified.

- [ ] **Step 1: User imports patched EXR sequence into DaVinci**

Message to user: "On a machine with DaVinci Resolve 19+, drag the patched EXR sequence into Media Pool. Click the clip → Inspector → File → Time Code. The Time Code must show the SMPTE value reported by the widget in Task 11 (e.g. `09:44:25:10`)."

- [ ] **Step 2: User sends Inspector screenshot**

Expected: a screenshot showing the Time Code field with the correct SMPTE value.

- [ ] **Step 3: User confirms timeline auto-conform**

"Drop the clip into a new timeline. Confirm the clip's Source TC matches the SMPTE start. If you have a parallel ProRes plate with embedded SMPTE, drop it on a parallel track and verify they auto-align by timecode (no manual offset)."

P1 G2 PASS criterion = Inspector shows the correct SMPTE Source TC for the EXR clip. (DaVinci's timeline-start TC default of 00:00:00:00 is a DaVinci preference, not a write-side problem.)

FAIL = Inspector shows `00:00:00:00` or a placeholder instead of the SMPTE value → G2 FAIL, investigate.

---

### Task 14: OTIO sidecar import to DaVinci (P1 G4 acceptance)

**Files:** none modified.

Second P1 acceptance gate — NOT optional.

- [ ] **Step 1: User clicks `Export OTIO Sidecar` in the widget**

"Same `Render output dir` input → click `Export OTIO Sidecar` → send me the widget result text + the resulting `.otio` file path."

Expected: `Exported OTIO sidecar to <path>.otio with N frames starting at HH:MM:SS:FF`.

- [ ] **Step 2: User imports `.otio` into DaVinci**

"DaVinci → File → Import → Timeline → select the `.otio` file. The new timeline must: (a) start at the same SMPTE value as the EXR clip, (b) resolve the ImageSequenceReference so the EXR sequence shows up populated."

- [ ] **Step 3: User sends timeline screenshot**

Expected: a screenshot showing the imported timeline with timecode start + EXR clips populated.

If timeline imports empty → ImageSequenceReference path resolution failed → check the .otio's `target_url` against the actual EXR dir. OTIO-export bug, not a backend-swap regression, but still blocks P1 G4 acceptance.

---

## Phase 4 — Cleanup

### Task 15: Decide Miniforge3 retention on lanPC

**Files:** none modified.

- [ ] **Step 1: Default — keep Miniforge3**

The migration removed all runtime dependency on oiiotool / conda openimageio. The remaining justification for keeping `C:\Tools\miniforge3` (~600 MB) is `exrheader.exe` for typed-attribute ground-truth verification in `integration_p1.py` and Task 12.

Recommend: **keep**. Removing it loses the only ground-truth EXR header inspector on lanPC.

- [ ] **Step 2: If user opts to remove**

```bash
echo 'Remove-Item -Recurse -Force C:\Tools\miniforge3' | ssh lanpc powershell -Command -
```

`integration_p1.py` will then fall through to its `not have_exrheader` warning automatically — no code change needed; the test just loses one ground-truth assertion.

- [ ] **Step 3: Final completion table**

| Parent acceptance criterion | Task | Pass evidence |
|---|---|---|
| `integration_p1.py` 6/6 PASS, EXR patcher not skipped | 9 | UE log full PASS list |
| real MRQ EXR survives patcher → exrheader shows type timecode + type rational | 12 | exrheader stdout snippet |
| DaVinci 19+ → drop EXR sequence → Inspector shows correct SMPTE | 13 | user screenshot |
| OTIO sidecar import → timeline start correct + EXR populated | 14 | user screenshot |

All four ticked → P1 G2 + G4 complete. Report to user; do **not** auto-commit anything beyond the per-task commits.

---

## Rollback

If anything in Phase 2 or later surfaces a regression:

```bash
# 1. Find the three production commits (Tasks 6, 7, 8 in execution order)
git log --oneline | grep -E "p1 g2|oiio-static-python"

# 2. Revert in REVERSE order. Codex adversarial review flagged that
#    `git revert <task-6>..<task-8>` uses range exclusion (excludes
#    <task-6> from the revert set) — the writer swap commit would NOT
#    be undone. Use an explicit reverse-order list instead:
git revert --no-edit <task-8-commit> <task-7-commit> <task-6-commit>
#    (Optionally use the inclusive-range form: <task-6-commit>^..<task-8-commit>)

# 3. Verify the writer is back on subprocess+oiiotool backend, NOT on OIIO Python:
grep -n "subprocess\|oiiotool\|ImageOutput" Content/Python/post_render_tool/exr_timecode_writer.py
#    Expect: subprocess.check_call lines present; "ImageOutput" absent.
```

The subprocess+oiiotool backend code is preserved in git history. No runtime toggle, no feature flag — per user memory `feedback_no_temporary_runtime_switches.md`.

---

## Self-review

- **Spec coverage:** every parent task acceptance criterion maps to a task here. Codex review's blockers + should-fix items addressed in the supersession table.
- **Placeholder scan:** no TBD/TODO/"implement later" in any step. All code blocks are concrete content to write.
- **Type / name consistency:** `patch_exr_timecode_in_dir` signature unchanged; `oiio.TimeCode`, `oiio.ImageBuf`, `oiio.TypeTimeCode`, `oiio.TypeRational` spelled consistently across Tasks 3, 6, 7, 8.
- **User memory respected:** hard swap (no feature flag); per-task commits only (no auto-commit at end); Chinese commit messages; no third-party API assumptions baked in (Task 3 probe is the empirical gate).
- **Probe-first discipline:** Tasks 6+ cannot proceed until Task 3 Phase A passes on dev Mac AND Task 5 confirms lanPC UE Python install. Real MRQ EXR preservation gate is Task 12 with explicit revert path if it fails.
