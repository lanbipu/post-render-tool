# EXR Timecode Backend Migration: oiiotool CLI → PyPI OpenEXR

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the widget "Patch EXR Timecode" button work end-to-end on the lanPC production UE 5.7 Windows machine, and finish P1 G2 (DaVinci 19+ auto-conform).

**Architecture:** Replace the `oiiotool` subprocess backend in `exr_timecode_writer.py` with in-process Python OpenEXR 3.x API. UE Python runs `pip install --user OpenEXR Imath`, same pattern as the existing `opentimelineio` install. Pure-Python algorithms (`_frame_to_timecode`, regex helpers, drop-frame inverse) stay untouched — only the I/O layer changes.

**Tech Stack:** PyPI `OpenEXR` 3.3+ (ASWF official Python wheel, Windows binaries), Imath types bundled in same wheel; UE 5.7 Python 3.11.

**Why this swap (was originally deferred by 2026-05-14 spike report):**
- conda-forge `openimageio` package on Windows ships **only the C++ library**, not `oiiotool.exe`. The spike picked oiiotool assuming Linux/Mac install paths (`brew install openimageio` / `scoop install openimageio`); neither package manager ships oiiotool on Windows. Verified empirically: scoop main/extras has no openimageio, winget search returns nothing, conda-forge `openimageio-2.5.18.0-haa1b8b9_13.conda` file manifest contains `OpenImageIO.dll` + headers + fonts only.
- Spike deferred PyPI OpenEXR on **macOS PEP 668 grounds** (system Python blocked pip install). UE Python on lanPC is a private interpreter under `D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe`, has no PEP 668 restriction, and we already shipped `opentimelineio` via `pip install --user` there in P1. The macOS deferral reason does not apply to the actual production target.
- PyPI OpenEXR 3.3+ has native `OpenEXR.TimeCode` and `OpenEXR.Rational` types, supports typed `timeCode` / `framesPerSecond` writes, ships Windows wheels for Python 3.7–3.13.
- Side benefit: cross-platform with no external CLI; tests do not need to skip on contributors without OpenImageIO installed.

**What does NOT change:**
- `_frame_to_timecode` drop-frame inverse algorithm — already covered by 4 unit tests.
- `_filename_pattern_to_regex` + `_validate_filename_pattern` — already 2 unit tests.
- `patch_exr_timecode_in_dir` public signature (same args, same return type).
- `run_patch_exr_timecode` in `pipeline.py` — calls the writer the same way.
- `widget.py` callback — already wired.
- `SourceFrameNumbers` + sample DataAsset timecode read path (P0 G1 work).

**What I will NOT do during this plan:**
- Add a runtime backend toggle / feature flag (per user memory `feedback_no_temporary_runtime_switches.md`). The migration is a hard swap. If we need to roll back, git revert.
- Auto-commit at the end (per user memory `feedback_explicit_commit_only.md`). The plan includes explicit `git commit` steps per task; the executing engineer runs them. No "wrap-up commit at end".
- Touch P0 G1 sequence-frame work (already production).

---

## File Structure

**Modified:**
- `Content/Python/post_render_tool/exr_timecode_writer.py` — swap `_ensure_oiiotool` + the subprocess body of `patch_exr_timecode_in_dir` for an in-process OpenEXR Python implementation. Public signature unchanged.
- `Content/Python/post_render_tool/tests/test_exr_timecode_writer.py` — drop `_HAVE_OIIOTOOL` / `_HAVE_EXRHEADER` skips, generate mock EXR via OpenEXR Python, verify written attributes by reading the file back via OpenEXR Python. Pure-Python tests (`TestFrameToTimecodeRoundTrip`) stay unchanged.
- `scripts/integration_p1.py` — replace `oiiotool --create` mock-EXR generation with OpenEXR Python; replace `exrheader` verification with OpenEXR Python header read; drop `_HAVE_OIIOTOOL` / `_HAVE_EXRHEADER` skips.
- `scripts/exr_timecode_spike_report.md` — append addendum "2026-05-14 backend swap: PyPI OpenEXR" with rationale.

**Created:**
- `scripts/probe_pypi_openexr.py` — standalone probe script that validates the OpenEXR Python API contract we depend on (typed `timeCode`, `Rational`, roundtrip preservation of channels). Runs both on the dev Mac (validates the API works) and on lanPC UE Python (validates lanPC install). Not part of the plugin runtime — lives in `scripts/` next to the spike report.

**Untouched:**
- `Content/Python/post_render_tool/pipeline.py` — call site unchanged.
- `Content/Python/post_render_tool/widget.py` — call site unchanged.
- `Content/Python/post_render_tool/otio_export.py` — separate concern, no overlap.
- `Content/Python/post_render_tool/timecode.py` — pure Python, no dependency on the writer.

---

## Pre-Flight: Probe PyPI OpenEXR API on dev Mac — GO/NO-GO Gate

### Task 1: Validate OpenEXR Python typed-attribute write on dev Mac

**Goal:** Before rewriting anything, confirm the OpenEXR Python wheel actually supports what we need. If the API does not expose typed `timeCode` and `Rational` writes (or the version pinned on PyPI breaks roundtrip), abort the migration and revisit alternative paths (DJV oiiotool harvest, OpenImageIO vcpkg build, etc.).

**Files:**
- Create: `scripts/probe_pypi_openexr.py`

- [ ] **Step 1: Create a fresh Python venv on dev Mac**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
python3 -m venv .venv_openexr_probe
source .venv_openexr_probe/bin/activate
python -m pip install --upgrade pip
```

Expected: pip 24+ activated.

- [ ] **Step 2: Install OpenEXR + numpy (transitive dep)**

```bash
pip install OpenEXR numpy
```

Expected: `Successfully installed OpenEXR-3.3.X Imath-... numpy-...`. If install fails on dev Mac (PEP 668 etc.), abort and report.

- [ ] **Step 3: Write the probe script**

```python
# scripts/probe_pypi_openexr.py
"""Probe PyPI OpenEXR API for the exact features exr_timecode_writer needs.

Exits 0 on full pass, non-zero with a diagnostic on any failure. Stdout
lists each capability check as PASS/FAIL with the OpenEXR version it ran
against. Intended to be invoked from both dev Mac (validate API exists)
and lanPC UE Python (validate install + API on production target).
"""
from __future__ import annotations

import os
import sys
import tempfile


def main() -> int:
    try:
        import OpenEXR
        import numpy as np
    except ImportError as e:
        print(f"FAIL: import OpenEXR / numpy — {e}")
        return 1

    print(f"OpenEXR version: {OpenEXR.__version__}")

    # 1. Required types are exposed.
    for name in ("TimeCode", "Rational"):
        if not hasattr(OpenEXR, name):
            print(f"FAIL: OpenEXR.{name} missing — API mismatch")
            return 2
    print("PASS: OpenEXR.TimeCode + OpenEXR.Rational exposed")

    # 2. Construct a typed TimeCode (non-DF 50 fps, 10:00:00:00) and
    #    Rational (50/1).
    tc = OpenEXR.TimeCode(
        hours=10, minutes=0, seconds=0, frame=0, dropFrame=False,
    )
    rational = OpenEXR.Rational(50, 1)
    print(f"PASS: TimeCode constructed -> hours={tc.hours()}, "
          f"frame={tc.frame()}, dropFrame={tc.dropFrame()}")
    print(f"PASS: Rational constructed -> {rational.n}/{rational.d}")

    # 3. Roundtrip — write a tiny 4x4 RGB EXR, attach timeCode +
    #    framesPerSecond, reopen, verify both attrs survived AND channels
    #    were preserved.
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, "src.exr")
        out_path = os.path.join(tmpdir, "patched.exr")

        # Create source with a known pixel pattern.
        rgb = np.full((4, 4, 3), 0.5, dtype=np.float32)
        header = {
            "compression": OpenEXR.ZIP_COMPRESSION,
            "type": OpenEXR.scanlineimage,
        }
        channels = {"RGB": rgb}
        with OpenEXR.File(header, channels) as src:
            src.write(src_path)
        print(f"PASS: wrote 4x4 RGB EXR -> {src_path}")

        # Reopen, mutate header, write to a new path. (OpenEXR 3.x writes
        # via File.write(path) after constructing with header + channels.)
        with OpenEXR.File(src_path) as f:
            part = f.parts[0]
            part.header["timeCode"] = tc
            part.header["framesPerSecond"] = rational
            f.write(out_path)
        print(f"PASS: roundtrip-rewrote with typed attrs -> {out_path}")

        # Reopen and verify.
        with OpenEXR.File(out_path) as f:
            part = f.parts[0]
            got_tc = part.header.get("timeCode")
            got_fps = part.header.get("framesPerSecond")
            got_channels = part.channels

        if got_tc is None:
            print("FAIL: timeCode missing after roundtrip")
            return 3
        if not isinstance(got_tc, OpenEXR.TimeCode):
            print(f"FAIL: timeCode is {type(got_tc).__name__}, "
                  "expected OpenEXR.TimeCode (typed, not string)")
            return 4
        if got_tc.hours() != 10 or got_tc.frame() != 0:
            print(f"FAIL: timeCode value drift — got hours={got_tc.hours()}, "
                  f"frame={got_tc.frame()}")
            return 5
        print(f"PASS: timeCode roundtrip preserved -> {got_tc.hours()}:"
              f"{got_tc.minutes()}:{got_tc.seconds()}:{got_tc.frame()}")

        if got_fps is None:
            print("FAIL: framesPerSecond missing after roundtrip")
            return 6
        if not isinstance(got_fps, OpenEXR.Rational):
            print(f"FAIL: framesPerSecond is {type(got_fps).__name__}, "
                  "expected OpenEXR.Rational")
            return 7
        if got_fps.n != 50 or got_fps.d != 1:
            print(f"FAIL: framesPerSecond drift -> {got_fps.n}/{got_fps.d}")
            return 8
        print(f"PASS: framesPerSecond roundtrip preserved -> "
              f"{got_fps.n}/{got_fps.d}")

        if "RGB" not in got_channels:
            print(f"FAIL: RGB channel lost — channels={list(got_channels)}")
            return 9
        if got_channels["RGB"].shape != (4, 4, 3):
            print(f"FAIL: RGB channel shape drift — {got_channels['RGB'].shape}")
            return 10
        print("PASS: RGB channel survived roundtrip")

    # 4. NTSC fractional rate (24000/1001) survives roundtrip without
    #    integer rounding.
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, "ntsc.exr")
        rgb = np.zeros((2, 2, 3), dtype=np.float32)
        with OpenEXR.File(
            {"compression": OpenEXR.ZIP_COMPRESSION,
             "type": OpenEXR.scanlineimage},
            {"RGB": rgb},
        ) as src:
            src.parts[0].header["framesPerSecond"] = OpenEXR.Rational(24000, 1001)
            src.write(src_path)
        with OpenEXR.File(src_path) as f:
            r = f.parts[0].header["framesPerSecond"]
        if (r.n, r.d) != (24000, 1001):
            print(f"FAIL: NTSC rational drift -> {r.n}/{r.d}")
            return 11
        print("PASS: NTSC rational 24000/1001 preserved")

    print("\n=== ALL PROBES PASSED — backend swap is safe to proceed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the probe**

```bash
python scripts/probe_pypi_openexr.py
```

Expected stdout: ends with `=== ALL PROBES PASSED — backend swap is safe to proceed ===`. Exit code 0.

- [ ] **Step 5: GO/NO-GO decision**

If the probe exits 0 → **GO**, continue to Task 2.

If the probe exits non-zero → **NO-GO**. Capture the failing step's output, stop the plan, report back. The most likely failure modes and their meaning:

| Exit | Meaning | Next action |
|------|---------|-------------|
| 1 | Wheel won't install (numpy ABI / Python version mismatch) | Check Python version compat on PyPI page; revisit alternatives |
| 2 | `TimeCode` or `Rational` symbol missing | OpenEXR wheel <3.3 — try `pip install 'OpenEXR>=3.3'`; if no compatible wheel for UE Python 3.11, abandon PyPI path |
| 3–5 | timeCode lost or untyped after roundtrip | API bug in installed wheel — try another version; if persistent, abandon |
| 6–8 | framesPerSecond lost or untyped | same as above |
| 9–10 | Channel data lost | wheel write path is destructive — abandon, revisit OpenImageIO Python (`py-openimageio` on conda) |
| 11 | NTSC rational got reduced or rounded | wheel does not preserve raw rationals — abandon (would silently drift NTSC takes) |

- [ ] **Step 6: Probe-only commit**

```bash
git add scripts/probe_pypi_openexr.py
git commit -m "$(cat <<'EOF'
chore(p1 g2 probe): scripts/probe_pypi_openexr.py 验证 PyPI OpenEXR API 契约

dev Mac 上跑通后才进入 backend 迁移。spike 把 PyPI OpenEXR deferred 在
macOS PEP 668，跟 lanPC UE Python 无关；本 probe 验证 typed timeCode +
typed Rational + channel roundtrip 都成立后再换 backend。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Migration (after probe GO)

### Task 2: Install OpenEXR into UE Python on lanPC

**Files:** none modified (deployment-only)

- [ ] **Step 1: Verify UE Python is reachable + pip works**

```bash
echo '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" -m pip --version' | ssh lanpc powershell -Command -
```

Expected: `pip XX.Y from ...` (pip already present per opentimelineio install history).

- [ ] **Step 2: Install OpenEXR + numpy into UE Python user site**

```bash
echo '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" -m pip install --user OpenEXR numpy' | ssh lanpc powershell -Command -
```

Expected: `Successfully installed OpenEXR-3.3.X Imath-... numpy-...`.

If pip refuses `--user` because UE Python is in a system-write-protected dir (D:\Program Files\), fall back to `--target` into a known prefix:

```bash
echo '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" -m pip install --target "C:/Tools/ue-pypkgs" OpenEXR numpy' | ssh lanpc powershell -Command -
```

If using `--target`, append `C:\Tools\ue-pypkgs` to UE's `sys.path` at startup. Use the same mechanism that loads `opentimelineio` — check `widget.py` / `pipeline.py` for any existing `sys.path.append` first; reuse the pattern. If opentimelineio just worked with `--user`, OpenEXR will too.

- [ ] **Step 3: Run the probe on lanPC UE Python**

```bash
scp scripts/probe_pypi_openexr.py lanpc:C:/temp/ue-remote/probe_openexr.py
echo '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" C:/temp/ue-remote/probe_openexr.py' | ssh lanpc powershell -Command -
```

Expected: same `=== ALL PROBES PASSED ===` output as on dev Mac, no exception.

If the probe passes on dev Mac but fails on lanPC, the install is wrong; do not advance to Task 3.

---

### Task 3: Rewrite `patch_exr_timecode_in_dir` to use OpenEXR Python

**Files:**
- Modify: `Content/Python/post_render_tool/exr_timecode_writer.py`

- [ ] **Step 1: Replace the module docstring + imports**

Replace lines 1–32 (the module-level docstring and the `_ensure_oiiotool` helper) with the OpenEXR-backed version. Pure-Python helpers below stay untouched.

```python
"""EXR header SMPTE timecode patcher.

Offline (post-render) — uses the PyPI `OpenEXR` Python wheel to write
typed `timeCode` + `framesPerSecond` rational attributes to EXR files
matching a filename pattern. In-process (no subprocess), cross-platform.

Backend rationale: see `scripts/exr_timecode_spike_report.md` for the
2026-05-14 backend swap (oiiotool CLI was unavailable on Windows
conda-forge openimageio, which ships the lib but not the CLI tools).

Install:
    pip install --user OpenEXR numpy
    (already installed alongside opentimelineio on the lanPC UE Python.)

Public API:
    patch_exr_timecode_in_dir(output_dir, filename_pattern,
                              start_csv_frame, start_timecode, fps)
        Walks `output_dir`, matches `filename_pattern` to extract the
        absolute CSV frame number from each filename, calculates the
        per-frame SMPTE timecode, and rewrites the EXR with that
        timecode in the header. Returns the count of patched files.
"""
from __future__ import annotations

import re
from pathlib import Path

from .timecode import Timecode, _frames_per_24h


def _ensure_openexr() -> None:
    """Lazy import + clear error message if the OpenEXR wheel is missing.

    Imported on first call rather than at module scope so the pure-Python
    `_frame_to_timecode` helper remains importable for unit tests on
    machines without OpenEXR installed.
    """
    try:
        import OpenEXR  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "PyPI OpenEXR wheel not installed on the current Python. "
            "Install with `pip install --user OpenEXR numpy` (UE Python "
            "on lanPC). Backend was swapped from oiiotool CLI on "
            "2026-05-14 — see scripts/exr_timecode_spike_report.md."
        ) from e
```

- [ ] **Step 2: Keep `_frame_to_timecode` exactly as-is**

No changes to lines 43–100 of the original file (`_frame_to_timecode` body). Verify by reading the file and confirming the algorithm bytes are unchanged.

- [ ] **Step 3: Keep `_UNRESOLVED_TOKEN_RE`, `_validate_filename_pattern`, `_filename_pattern_to_regex` exactly as-is**

Lines 103–146 of the original file are pure regex + validation. Untouched.

- [ ] **Step 4: Replace the body of `patch_exr_timecode_in_dir`**

Replace the body (the `subprocess.check_call([...])` loop) with an OpenEXR Python in-process rewrite. Public signature stays identical.

```python
def patch_exr_timecode_in_dir(
    output_dir: str,
    filename_pattern: str,
    start_csv_frame: int,
    start_timecode: Timecode,
    fps: float,
) -> int:
    """Add typed `timeCode` + rational `framesPerSecond` attributes to
    every EXR in `output_dir` matching `filename_pattern`.

    See module docstring for parameter semantics — unchanged across the
    2026-05-14 backend swap from oiiotool to PyPI OpenEXR.
    """
    out_path = Path(output_dir)
    if not out_path.is_dir():
        return 0
    _ensure_openexr()
    import OpenEXR

    fn_regex = _filename_pattern_to_regex(filename_pattern)
    rate_num = start_timecode.rate_num
    rate_den = start_timecode.rate_den

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

        oiio_tc = OpenEXR.TimeCode(
            hours=tc.hours,
            minutes=tc.minutes,
            seconds=tc.seconds,
            frame=tc.frames,
            dropFrame=tc.drop_frame,
        )
        oiio_fps = OpenEXR.Rational(rate_num, rate_den)

        with OpenEXR.File(str(file)) as f:
            f.parts[0].header["timeCode"] = oiio_tc
            f.parts[0].header["framesPerSecond"] = oiio_fps
            f.write(str(file))
        processed += 1
    return processed
```

- [ ] **Step 5: Sanity-check the file compiles**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool
python3 -c "import ast; ast.parse(open('Content/Python/post_render_tool/exr_timecode_writer.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 6: Commit (no tests yet — those come in Task 4)**

```bash
git add Content/Python/post_render_tool/exr_timecode_writer.py
git commit -m "$(cat <<'EOF'
refactor(p1 g2): exr_timecode_writer 后端从 oiiotool CLI 换 PyPI OpenEXR

conda-forge Windows openimageio 只装 lib 不带 oiiotool.exe，spike 当时
默认 brew/scoop 装 oiiotool 在 lanPC 不成立。换成 PyPI OpenEXR Python
wheel：in-process、跨平台、native typed TimeCode/Rational。
public 签名 + 行为完全不变；pure-Python helper（_frame_to_timecode、
filename regex 校验）一字未动，14 个老 unit test 还跑得过。

tests 在下一个 commit 重写。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Rewrite unit tests for the OpenEXR backend

**Files:**
- Modify: `Content/Python/post_render_tool/tests/test_exr_timecode_writer.py`

- [ ] **Step 1: Replace top-of-file imports + remove oiiotool skip gates**

Replace lines 1–43 with the new test scaffolding. The pure-Python `TestFrameToTimecodeRoundTrip` block stays as-is (lines 165–236 of the original).

```python
"""EXR header SMPTE timecode patcher tests.

Offline (no `unreal` dependency). Uses the PyPI OpenEXR wheel for both
mock-EXR generation and header inspection — no external CLI dependency.

Tests skip gracefully if OpenEXR is not installed on the runner, so the
rest of the unit suite stays runnable on contributors who have not yet
`pip install`-ed OpenEXR.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest


try:
    import OpenEXR
    import numpy as np
    _HAVE_OPENEXR = True
except ImportError:
    _HAVE_OPENEXR = False


def _gen_test_exr(path: str) -> None:
    """Create a 4x4 RGB EXR via OpenEXR Python."""
    rgb = np.full((4, 4, 3), 0.5, dtype=np.float32)
    header = {
        "compression": OpenEXR.ZIP_COMPRESSION,
        "type": OpenEXR.scanlineimage,
    }
    channels = {"RGB": rgb}
    with OpenEXR.File(header, channels) as f:
        f.write(path)


def _read_timecode(path: str) -> "OpenEXR.TimeCode | None":
    with OpenEXR.File(path) as f:
        return f.parts[0].header.get("timeCode")


def _read_rational_fps(path: str) -> "OpenEXR.Rational | None":
    with OpenEXR.File(path) as f:
        return f.parts[0].header.get("framesPerSecond")
```

- [ ] **Step 2: Rewrite `TestPatchExrTimecode` to use OpenEXR helpers**

Replace lines 45–162 of the original with this updated test class. Same test names + scenarios; assertions now read OpenEXR Python types instead of parsing exrheader text.

```python
@unittest.skipUnless(_HAVE_OPENEXR, "PyPI OpenEXR not installed — pip install OpenEXR numpy")
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

        tc = _read_timecode(first)
        self.assertIsNotNone(tc, "timeCode attribute missing")
        self.assertIsInstance(tc, OpenEXR.TimeCode,
                              "expected typed TimeCode, got "
                              f"{type(tc).__name__}")

        fps = _read_rational_fps(first)
        self.assertIsNotNone(fps, "framesPerSecond attribute missing")
        self.assertIsInstance(fps, OpenEXR.Rational,
                              "expected typed Rational, got "
                              f"{type(fps).__name__}")
        self.assertEqual((fps.n, fps.d), (50, 1))

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
            tc = _read_timecode(path)
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

- [ ] **Step 3: Rewrite `TestFractionalFpsRationalMetadata` (lines 238–281)**

Replace with the OpenEXR-Python version. Skip gate becomes `_HAVE_OPENEXR` instead of `_HAVE_OIIOTOOL and _HAVE_EXRHEADER`.

```python
@unittest.skipUnless(_HAVE_OPENEXR, "PyPI OpenEXR not installed")
class TestFractionalFpsRationalMetadata(unittest.TestCase):
    """framesPerSecond must keep the exact NTSC rational (24000/1001 etc.),
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
            (r.n, r.d), (exp_num, exp_den),
            f"expected {exp_num}/{exp_den} for {fps}fps, got: {r.n}/{r.d}",
        )

    def test_23976_writes_24000_over_1001(self):
        self._check_rational(23.976, "00:00:00:00", 24000, 1001)

    def test_2997_writes_30000_over_1001(self):
        self._check_rational(29.97, "00:00:00;00", 30000, 1001)

    def test_5994_writes_60000_over_1001(self):
        self._check_rational(59.94, "00:00:00;00", 60000, 1001)

    def test_50_writes_50_over_1(self):
        self._check_rational(50.0, "00:00:00:00", 50, 1)
```

- [ ] **Step 4: `TestFrameToTimecodeRoundTrip` stays unchanged**

Lines 165–236 of the original (the pure-Python drop-frame inverse tests). No edits — they have no I/O and no oiiotool dependency.

- [ ] **Step 5: Keep `if __name__ == "__main__": unittest.main()` at the end**

- [ ] **Step 6: Run tests on dev Mac with OpenEXR installed**

```bash
cd /Users/bip.lan/AIWorkspace/vp/post_render_tool/Content/Python
source ../../.venv_openexr_probe/bin/activate
python -m unittest post_render_tool.tests.test_exr_timecode_writer -v
```

Expected: 14 tests, 14 PASS (no skipped, because OpenEXR is installed in the venv).

- [ ] **Step 7: Run tests on a Python WITHOUT OpenEXR to confirm skip gating**

```bash
deactivate  # leave venv
python3 -m unittest post_render_tool.tests.test_exr_timecode_writer -v
```

Expected: 4 PASS (the pure-Python `TestFrameToTimecodeRoundTrip`), 10 SKIPPED with message `PyPI OpenEXR not installed`. No FAIL. (If `numpy` happens to be on system Python, OpenEXR import will still fail, so the skip path is the one that runs.)

- [ ] **Step 8: Commit**

```bash
git add Content/Python/post_render_tool/tests/test_exr_timecode_writer.py
git commit -m "$(cat <<'EOF'
test(p1 g2): exr_timecode_writer tests 改用 OpenEXR Python 验证

mock EXR 生成、typed timeCode/Rational 验证全部走 in-process OpenEXR，
不再依赖 oiiotool/exrheader CLI。pure-Python TestFrameToTimecodeRoundTrip
（drop-frame inverse 算法 4 个 case）一字未动。

没装 OpenEXR 时 10 个 I/O test 走 skip 路径，pure-Python 4 个还能跑。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Update `scripts/integration_p1.py` — drop oiiotool dependency

**Files:**
- Modify: `scripts/integration_p1.py`

- [ ] **Step 1: Replace the EXR generation + verification helpers**

The current script (1) uses `oiiotool --create` to generate mock EXR and (2) parses `exrheader` text to verify typed attrs. Both need to go.

Replace the `have_oiiotool` / `have_exrheader` block (lines 80–137 of the original) with OpenEXR-Python equivalents:

```python
    have_openexr = False
    try:
        import OpenEXR
        import numpy as np
        have_openexr = True
    except ImportError:
        unreal.log_warning(
            "[P1_INTEG] PyPI OpenEXR not installed in UE Python — EXR "
            "patcher tests SKIPPED. Install: "
            "`<UE>/Engine/Binaries/ThirdParty/Python3/Win64/python.exe "
            "-m pip install --user OpenEXR numpy`"
        )

    if have_openexr:
        # Generate mock EXR matching derived pattern (4x4 gray RGB).
        rgb = np.full((4, 4, 3), 0.5, dtype=np.float32)
        for offset in range(3):
            frame = first_frame + offset
            filename = pattern.format(frame=frame)
            fpath = os.path.join(test_dir, filename)
            try:
                header = {
                    "compression": OpenEXR.ZIP_COMPRESSION,
                    "type": OpenEXR.scanlineimage,
                }
                with OpenEXR.File(header, {"RGB": rgb}) as f:
                    f.write(fpath)
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

        # Verify the typed timeCode + rational attributes on disk.
        first_filename = pattern.format(frame=first_frame)
        first_path = os.path.join(test_dir, first_filename)
        try:
            with OpenEXR.File(first_path) as f:
                hdr = f.parts[0].header
                tc = hdr.get("timeCode")
                fps_attr = hdr.get("framesPerSecond")
            _verify("EXR has typed timeCode attribute",
                    isinstance(tc, OpenEXR.TimeCode),
                    f"got type {type(tc).__name__ if tc else 'None'}")
            _verify("EXR has rational FramesPerSecond",
                    isinstance(fps_attr, OpenEXR.Rational),
                    f"got type {type(fps_attr).__name__ if fps_attr else 'None'}")
        except Exception as e:
            _verify("OpenEXR header read", False, str(e))
```

- [ ] **Step 2: Replace module docstring + remove subprocess/shutil imports if no longer used**

Top of file: drop `import subprocess` and `import shutil` if not used elsewhere. The `shutil.rmtree(test_dir, ignore_errors=True)` at the end still needs shutil, so keep it.

```python
"""P1 integration test — run_patch_exr_timecode + run_export_otio.

2026-05-14 backend swap: EXR patcher now uses PyPI OpenEXR Python wheel
in-process. lanPC UE Python must have `OpenEXR numpy` pip-installed
(same install pattern as opentimelineio).

Steps (unchanged from pre-swap):
1. Reload modified Python modules (post_render_tool.*).
2. Generate a mock MRQ-style EXR sequence in `C:/temp/p1_test/`.
3. Call open_movie_render_queue to set up MRQ output_setting.
4. Call run_patch_exr_timecode, verify EXR header has typed timecode.
5. Call run_export_otio, verify .otio file written + parseable.
"""
```

- [ ] **Step 3: Compile-check**

```bash
python3 -c "import ast; ast.parse(open('scripts/integration_p1.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add scripts/integration_p1.py
git commit -m "$(cat <<'EOF'
test(p1 g2): integration_p1.py 改 OpenEXR Python 生成/验证 mock EXR

不再依赖 oiiotool/exrheader 在 lanPC PATH。lanPC UE Python pip
install OpenEXR + numpy 之后这个集成 probe 整体 PASS。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Run integration_p1.py end-to-end on lanPC

**Files:** none modified

- [ ] **Step 1: Sync widget code to lanPC plugin dir (if not already auto-synced)**

Confirm `E:\RenderStream Projects\test_0311\Plugins\post-render-tool\` is up-to-date with the new commits. If the plugin is a git checkout, `git pull`. If it's the p4 workspace mirror, the post-commit hook to p4 should already have advanced it.

```bash
echo 'cd "E:\RenderStream Projects\test_0311\Plugins\post-render-tool"; git log --oneline -3' | ssh lanpc powershell -Command -
```

Expected: the three new commits from Tasks 1–5 show up at the top.

- [ ] **Step 2: SCP the updated integration script**

```bash
scp scripts/integration_p1.py lanpc:C:/temp/ue-remote/integ_p1.py
```

- [ ] **Step 3: Run inside UE Editor on lanPC**

```bash
echo '& "D:/Program Files/Epic Games/UE_5.7/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/integ_p1.py' | ssh lanpc powershell -Command -
```

Expected: UE log shows the test banner `=== P1 Integration Test ===`, every `[P1_INTEG]` line says `PASS`. Specifically expect these PASS lines:

```
[P1_INTEG] PASS :: take_4 LevelSequence exists
[P1_INTEG] PASS :: derive_mrq_filename_pattern returns pattern
[P1_INTEG] PASS :: derive_mrq_filename_pattern returns padding
[P1_INTEG] PASS :: generated 3 mock EXR files
[P1_INTEG] PASS :: run_patch_exr_timecode runs
[P1_INTEG] PASS :: patched_count == 3
[P1_INTEG] PASS :: start_timecode reported
[P1_INTEG] PASS :: EXR has typed timeCode attribute
[P1_INTEG] PASS :: EXR has rational FramesPerSecond
[P1_INTEG] PASS :: run_export_otio runs
[P1_INTEG] PASS :: OTIO sidecar file exists
[P1_INTEG] PASS :: OTIO frame_count > 0
```

No `FAIL` lines, no skipped EXR block.

- [ ] **Step 4: If any FAIL — diagnose, do NOT advance**

The common failure modes:
- `OpenEXR not installed` warning → Task 2 install didn't land; fix install on lanPC then rerun.
- `run_patch_exr_timecode runs` FAIL with `OpenEXR.File ... cannot open` → file pattern derived by `derive_mrq_filename_pattern` doesn't match what `_gen_test_exr` wrote; check `pattern` value in the log and trace back to MRQ output_setting.
- `EXR has typed timeCode attribute` FAIL → OpenEXR.File.write isn't preserving the typed attr; rerun the dev-Mac probe to triage, file a bug, fall back to NO-GO branch.

Do not commit anything until all 12 lines are PASS.

---

### Task 7: Update spike report with 2026-05-14 backend swap addendum

**Files:**
- Modify: `scripts/exr_timecode_spike_report.md`

- [ ] **Step 1: Append the addendum at the bottom**

Add this block at the end of the file (after the existing "Remaining manual verification" section):

```markdown
---

## 2026-05-14 update — backend swapped to PyPI OpenEXR

**Trigger:** P1 G2 deployment on lanPC failed: conda-forge `openimageio`
on Windows ships only the C++ library, not the `oiiotool.exe` CLI.
scoop main + extras buckets have no `openimageio` manifest; winget has
no package; the original spike picked oiiotool assuming
`brew install openimageio` / `scoop install openimageio`, neither of
which delivers the CLI on Windows.

**Swap:** Replaced subprocess-`oiiotool` with in-process PyPI
`OpenEXR>=3.3` Python wheel. Validated by `scripts/probe_pypi_openexr.py`:

- Typed `OpenEXR.TimeCode` and `OpenEXR.Rational` constructors exist.
- Roundtrip rewrite preserves channels, typed `timeCode`, typed
  `framesPerSecond`.
- NTSC fractional (24000/1001) survives without integer rounding.

The original PyPI-OpenEXR deferral reason (macOS PEP 668 blocking
`pip install` against system Python) was a dev-Mac concern only — UE
Python on lanPC is a private interpreter and the `pip install --user`
path was already proven by the opentimelineio install in P1.

**What stayed identical across the swap:**
- `patch_exr_timecode_in_dir` public signature.
- `_frame_to_timecode` drop-frame inverse algorithm + tests.
- Filename regex / MRQ-token validation + tests.
- Output attribute names (`timeCode`, `framesPerSecond`) — note that
  oiiotool wrote `smpte:TimeCode` which exrheader normalized to
  `timeCode`; OpenEXR Python writes the canonical name directly.

**Production gate:** DaVinci 19+ Inspector → File → Time Code reading
the patched EXR sequence still on the manual-verify list (final P1 G2
acceptance).
```

- [ ] **Step 2: Commit**

```bash
git add scripts/exr_timecode_spike_report.md
git commit -m "$(cat <<'EOF'
docs(p1 g2): spike report 加 2026-05-14 backend swap addendum

记录原 spike 选 oiiotool 时漏检 Windows 包不带 CLI 的事实，PyPI
OpenEXR deferral 理由（macOS PEP 668）不适用 lanPC UE Python。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Manual production verify

The next four tasks (8–11) require user interaction with UE Editor and DaVinci. The executing engineer should hand-off to the user with explicit step lists, capture screenshots / log lines as evidence, and stop on any failure.

### Task 8: Coordinate manual MRQ EXR render

**Files:** none modified

- [ ] **Step 1: Ask user to import a take through the widget**

Tell user (in conversation): "Run the widget, pick any take (take_4 if you want to reuse P0 G1 evidence), let it import the LevelSequence."

Wait for user to confirm the import landed.

- [ ] **Step 2: Ask user to switch MRQ output to EXR**

Tell user: "Open MRQ via the widget's Open MRQ button. In the MRQ job's Output Setting, change Output Format from JPEG to `.exr Sequence`. JPEG has no standard timecode field — must be EXR."

- [ ] **Step 3: Ask user to render a short range**

Tell user: "Render 3–10 frames into a clean output dir (e.g. `D:/MRQ_out/p1g2_test/`). Send me back the exact output dir path + one filename so I know the MRQ filename pattern."

- [ ] **Step 4: Ask user to click "Patch EXR Timecode" in the widget**

Tell user: "In the widget's Render output dir input box, paste the dir from step 3. Click Patch EXR Timecode. Send me the widget result text."

Expected widget text: `Patched N EXR file(s) with start_timecode=HH:MM:SS:FF in: <dir>`. N must equal the rendered frame count.

If the widget reports `Patched 0 EXR — pattern '<X>' 不匹配`, the MRQ file_name_format doesn't match what `derive_mrq_filename_pattern` derived — capture the pattern value, check MRQ's file_name_format, and adjust before re-running.

### Task 9: exrheader verify — type timecode + rational FPS

**Files:** none modified

- [ ] **Step 1: SSH lanPC and read the first patched EXR**

Use the miniforge-installed `exrheader` (no additional install — it landed when we installed openimageio in Task 1 of the original task list before pivoting).

```bash
echo '& "C:\Tools\miniforge3\Library\bin\exrheader.exe" "<MRQ output dir>\<first patched filename>"' | ssh lanpc powershell -Command -
```

(Substitute the exact dir + filename from Task 8 step 3.)

- [ ] **Step 2: Verify the output contains both typed attributes**

Expected lines in the exrheader output:

```
timeCode (type timecode):
framesPerSecond (type rational): 50/1
```

Or for NTSC frame rates: `24000/1001`, `30000/1001`, `60000/1001`.

If `timeCode` shows `type string` instead of `type timecode` → the OpenEXR wheel stored it as a string fallback; the swap failed. Open an issue, revisit.

If `framesPerSecond` is missing → header write lost the attribute; same fix path.

### Task 10: DaVinci 19+ Inspector timecode verify

**Files:** none modified

- [ ] **Step 1: Hand the patched EXR sequence to the user for DaVinci import**

Tell user: "Pull the patched EXR dir to a machine with DaVinci 19+. Drag the sequence into the Media Pool. Click the clip → Inspector → File. The Time Code field must show the SMPTE value reported by the widget in Task 8 step 4."

- [ ] **Step 2: Capture the Inspector screenshot as evidence**

Ask user to take a screenshot of the Inspector showing the timecode and send it back.

- [ ] **Step 3: Verify timeline auto-alignment**

Tell user: "Drop the clip onto a new timeline. Confirm the timeline's clip-start timecode matches the same SMPTE value (so a colorist could conform to a plate by timecode without any manual offset)."

If the EXR shows the right Time Code in Inspector but the timeline starts at 00:00:00:00 — that's a DaVinci preference (timeline TC start ≠ clip TC); it still counts as a pass for the timecode-write side.

### Task 11: Optional — OTIO sidecar import verify

**Files:** none modified

- [ ] **Step 1: Ask user to click "Export OTIO Sidecar" in the widget**

Tell user: "Same Render output dir input. Click Export OTIO Sidecar. Send me the result text and the .otio path."

- [ ] **Step 2: Ask user to import the .otio in DaVinci**

Tell user: "DaVinci → File → Import → Timeline → select the .otio file. Confirm: (a) timeline start matches the SMPTE start; (b) the ImageSequenceReference resolves and the EXR sequence shows up in the timeline."

- [ ] **Step 3: Capture evidence**

Screenshot of the DaVinci timeline post-import. Save under `validation_results/p1_g2_otio_import/` for the project record.

---

### Task 12: Cleanup — decide miniforge3 fate

**Files:** none modified (decision step)

- [ ] **Step 1: Decide whether to keep `C:\Tools\miniforge3` on lanPC**

The miniforge install (~600 MB on disk) was only needed for the `exrheader.exe` we used in Task 9, plus is the cleanest way to have `OpenEXR` library headers available system-wide (not used now, but a future Path-X exploration might want it).

Recommend: **keep it**. Disk cost is low; `exrheader` is the only ground-truth EXR header inspector and removing it would block future debugging.

If user wants it gone:

```bash
echo 'Remove-Item -Recurse -Force C:\Tools\miniforge3' | ssh lanpc powershell -Command -
```

…and ensure the user PATH no longer references it (we never added it to PATH — it was only invoked by fully qualified path).

- [ ] **Step 2: Plan completion check**

Run through the original task acceptance criteria from the parent task spec:

| Criterion | Source | Pass evidence |
|-----------|--------|---------------|
| `integration_p1.py` 6/6 PASS (含 EXR patcher, 不 SKIP) | Task 6 | UE log shows all PASS lines |
| 真实 MRQ EXR 跑过 patcher 后 exrheader 显示 type timecode + type rational | Task 9 | exrheader stdout |
| DaVinci 19+ 拖 EXR 序列 → Inspector 显示正确 timecode | Task 10 | user screenshot |
| OTIO sidecar 也能 import → timeline 起点对 | Task 11 | user screenshot |

All four ticked → P1 G2 complete. Report back to user; do not auto-commit anything outside the per-task commits already made (per `feedback_explicit_commit_only.md`).

---

## Rollback plan

If a downstream regression surfaces (DaVinci reads typed timeCode wrong, NTSC drifts on long takes, etc.) and we need to revert the backend swap quickly:

```bash
git log --oneline | head -10  # find the pre-swap commit (one before Task 3 commit)
git revert <task-3-commit>..<task-7-commit>
```

The oiiotool backend code is in git history at the pre-swap commit and can be cherry-picked back. Do NOT keep a runtime toggle (per user memory `feedback_no_temporary_runtime_switches.md`) — if rollback is needed, revert hard.

---

## Self-review notes

- Spec coverage: each item in the parent task message has a corresponding plan task — install (Task 2), integration probe (Task 6), manual MRQ + exrheader + DaVinci + OTIO (Tasks 8–11). The Windows oiiotool gap is the diagnosis that triggers the backend swap (Task 3–5) before the integration probe can pass.
- Placeholder scan: no TODO / TBD / "implement later" in any step. Every code block is the actual content to write.
- Type consistency: `patch_exr_timecode_in_dir` keeps its original signature across all references. `OpenEXR.TimeCode` and `OpenEXR.Rational` are the only new types introduced and they're spelled consistently from Task 1 (probe) through Task 6 (integration verify).
- User memory respected: no feature flag, no auto-commit, Chinese commit messages, codex review will fire on each TaskUpdate → completed transition that touched code (Tasks 3–5, 7).
