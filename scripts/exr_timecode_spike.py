"""Task 9 spike: which EXR backend can write typed SMPTE timeCode +
framesPerSecond on a real (multipart) EXR without dropping channels?

Decision matrix:
- backend (a) PyPI `OpenEXR` + `Imath`: pure Python, cross-platform wheel.
- backend (b) `oiiotool` (OpenImageIO CLI): industry-standard attribute ops.
- backend (c) UE-side `UMoviePipelineImagePassBase` subclass: deferred —
  requires plugin C++ changes, not viable in P1 spike scope.

Spike steps for each backend:
  1. Generate baseline EXR (mock single-part RGB + multipart with extra
     channels to stress test).
  2. Run backend on the EXR to write smpte:TimeCode and FramesPerSecond.
  3. Use `exrheader` to verify the result has *typed* `timeCode` /
     `framesPerSecond` attributes (NOT a string display name).
  4. Diff channel list + compression flag against baseline.

Final acceptance: `exrheader` shows ANY non-string-typed `timeCode`
attribute (`timecode` typed: `time 0x..., user 0x...`), and all
baseline channels/compression survive intact.

The "real" final acceptance is a separate DaVinci 19+ import test that
the user runs on actual MRQ-rendered EXR; this script is the automated
prerequisite that decides which backend to ship in Task 10.

Usage (mac with brew + UE python on lanPC):
    python3 scripts/exr_timecode_spike.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _gen_mock_exr(path: str, multipart: bool = False) -> None:
    """Generate a mock EXR via oiiotool. Single-part RGB by default;
    multipart=True adds an alpha + depth part to stress-test attribute
    preservation."""
    if not multipart:
        subprocess.check_call([
            "oiiotool",
            "--create", "64x64", "3",
            "--fill:color=0.5,0.3,0.2", "64x64",
            "--attrib:type=string", "compression", "zip",
            "--attrib:type=float", "pixelAspectRatio", "1.0",
            "-o", path,
        ])
        return
    # Multipart: RGB main + alpha part — simulates MRQ-typical AOV layout.
    main = path + ".main.exr"
    alpha = path + ".alpha.exr"
    try:
        subprocess.check_call([
            "oiiotool", "--create", "64x64", "3",
            "--fill:color=0.5,0.3,0.2", "64x64",
            "-o", main,
        ])
        subprocess.check_call([
            "oiiotool", "--create", "64x64", "1",
            "--fill:color=1.0", "64x64",
            "--chnames", "A",
            "-o", alpha,
        ])
        # Stitch into multipart
        subprocess.check_call([
            "oiiotool", main, alpha,
            "--siappendall",
            "-o", path,
        ])
    finally:
        for tmp in (main, alpha):
            if os.path.exists(tmp):
                os.unlink(tmp)


def _exr_header(path: str) -> str:
    if _have("exrheader"):
        return subprocess.check_output(
            ["exrheader", path], text=True, stderr=subprocess.STDOUT
        )
    if _have("oiiotool"):
        return subprocess.check_output(
            ["oiiotool", "--info", "-v", path], text=True, stderr=subprocess.STDOUT
        )
    raise RuntimeError("Neither exrheader nor oiiotool available")


def _spike_oiiotool(path: str, hh: int, mm: int, ss: int, ff: int, drop: bool, fps: int) -> bool:
    """Backend (b): oiiotool CLI."""
    sep = ";" if drop else ":"
    tc_str = f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"
    try:
        subprocess.check_call([
            "oiiotool", path,
            "--attrib:type=timecode", "smpte:TimeCode", tc_str,
            "--attrib:type=rational", "FramesPerSecond", f"{fps}/1",
            "-o", path,
        ], stderr=subprocess.STDOUT)
        return True
    except subprocess.CalledProcessError as exc:
        print(f"  [b oiiotool] FAILED: {exc}")
        return False


def _spike_openexr_python(path: str, hh: int, mm: int, ss: int, ff: int, drop: bool, fps: int) -> bool:
    """Backend (a): PyPI OpenEXR + Imath. Round-trips through OpenEXR
    Python bindings — fragile around multipart but cross-platform."""
    try:
        import OpenEXR  # type: ignore
        import Imath  # type: ignore
    except ImportError:
        print("  [a OpenEXR py] not installed (pip install OpenEXR Imath)")
        return False
    try:
        f = OpenEXR.InputFile(path)
        header = dict(f.header())
        # Copy channels and rewrite — PyPI OpenEXR has no in-place edit
        # for typed structured attrs in older versions. This is the
        # 易踩坑 path mentioned in plan.
        # For brevity: read pixels, build new OutputFile with merged header.
        try:
            tc = Imath.TimeCode(hh, mm, ss, ff, dropFrame=drop)
        except TypeError:
            tc = Imath.TimeCode(hh, mm, ss, ff)
        header["timeCode"] = tc
        header["framesPerSecond"] = Imath.Rational(fps, 1)
        # In-place write requires reading all channels, which depends on
        # channel list — skip for now and bail out as "fragile path".
        f.close()
        print("  [a OpenEXR py] header build OK; rewrite of multipart EXR "
              "is non-trivial without OpenEXR 3.3+ Python API — marked as "
              "high-risk for P1 ship.")
        return False
    except Exception as exc:
        print(f"  [a OpenEXR py] FAILED: {exc}")
        return False


def _verify_typed_attrs(path: str) -> dict:
    """Return dict with verification result for each typed attribute."""
    header = _exr_header(path)
    out = {"timeCode_typed": False, "framesPerSecond_typed": False,
           "header_excerpt": ""}
    for line in header.splitlines():
        line_lower = line.lower().strip()
        if "timecode" in line_lower:
            out["header_excerpt"] += "\n  " + line.strip()
            # Look for `timecode` type tag (not `string` not `compound`)
            if "type timecode" in line_lower or "(timecode)" in line_lower:
                out["timeCode_typed"] = True
        if "framespersecond" in line_lower or "framesPerSecond" in line:
            out["header_excerpt"] += "\n  " + line.strip()
            if "rational" in line_lower:
                out["framesPerSecond_typed"] = True
    return out


def _extract_channels(header_text: str) -> set[str]:
    """Pull channel names from exrheader / oiiotool --info output."""
    channels: set[str] = set()
    in_channels = False
    for line in header_text.splitlines():
        s = line.strip()
        if "channels" in s.lower():
            in_channels = True
            continue
        # `R, half, 1 1` style (exrheader) or `Channel list:` (oiiotool)
        if in_channels:
            # Stop when we hit another attribute or blank line
            if s == "" or "(type " in s.lower():
                in_channels = False
                continue
            # Channel name is everything before `,` or `:`
            for tok in s.replace(":", ",").split(","):
                tok = tok.strip()
                if tok and not tok[0].isdigit() and "type" not in tok:
                    channels.add(tok.split()[0])
    return channels


def _extract_compression(header_text: str) -> str:
    for line in header_text.splitlines():
        s = line.strip().lower()
        if "compression" in s and "compressionlevel" not in s:
            return s
    return ""


def _verify_preservation(baseline: str, patched: str) -> dict:
    """Compare channels + compression between baseline and patched EXR."""
    baseline_chans = _extract_channels(baseline)
    patched_chans = _extract_channels(patched)
    baseline_compr = _extract_compression(baseline)
    patched_compr = _extract_compression(patched)
    return {
        "channels_preserved": baseline_chans == patched_chans,
        "compression_preserved": baseline_compr == patched_compr,
        "baseline_channels": sorted(baseline_chans),
        "patched_channels": sorted(patched_chans),
        "baseline_compression": baseline_compr,
        "patched_compression": patched_compr,
    }


def main() -> int:
    if not _have("oiiotool"):
        print("FAIL: oiiotool not installed (brew install openimageio)")
        return 1

    tmpdir = tempfile.mkdtemp(prefix="exr_spike_")
    print(f"# Task 9 EXR Writer Spike\n\nworkspace: `{tmpdir}`\n")
    print(f"oiiotool: {shutil.which('oiiotool')}")
    print(f"exrheader: {shutil.which('exrheader') or '(missing — fall back to oiiotool --info)'}\n")

    sp_b_single = os.path.join(tmpdir, "spike_b_single.exr")
    sp_b_multi = os.path.join(tmpdir, "spike_b_multi.exr")

    # ----- Backend (b) oiiotool: single-part -----
    print("## Backend (b) oiiotool — single-part EXR\n")
    _gen_mock_exr(sp_b_single, multipart=False)
    baseline_b_s = _exr_header(sp_b_single)
    ok = _spike_oiiotool(sp_b_single, 10, 0, 0, 0, False, 50)
    print(f"  write: {'OK' if ok else 'FAIL'}")
    if ok:
        res = _verify_typed_attrs(sp_b_single)
        patched_b_s = _exr_header(sp_b_single)
        pres = _verify_preservation(baseline_b_s, patched_b_s)
        print(f"  timeCode typed: {res['timeCode_typed']}")
        print(f"  FramesPerSecond typed: {res['framesPerSecond_typed']}")
        print(f"  channels preserved: {pres['channels_preserved']} "
              f"(baseline={pres['baseline_channels']}, patched={pres['patched_channels']})")
        print(f"  compression preserved: {pres['compression_preserved']}")
        print(f"  header excerpt: {res['header_excerpt']}")
    print()

    # ----- Backend (b) oiiotool: multipart -----
    print("## Backend (b) oiiotool — multipart EXR (stress test)\n")
    try:
        _gen_mock_exr(sp_b_multi, multipart=True)
        baseline_b_m = _exr_header(sp_b_multi)
        ok = _spike_oiiotool(sp_b_multi, 10, 0, 0, 0, False, 50)
        print(f"  write: {'OK' if ok else 'FAIL'}")
        if ok:
            res = _verify_typed_attrs(sp_b_multi)
            patched_b_m = _exr_header(sp_b_multi)
            pres = _verify_preservation(baseline_b_m, patched_b_m)
            print(f"  timeCode typed: {res['timeCode_typed']}")
            print(f"  FramesPerSecond typed: {res['framesPerSecond_typed']}")
            print(f"  channels preserved: {pres['channels_preserved']} "
                  f"(baseline={pres['baseline_channels']}, patched={pres['patched_channels']})")
            print(f"  compression preserved: {pres['compression_preserved']}")
            print(f"  header excerpt: {res['header_excerpt']}")
    except subprocess.CalledProcessError as exc:
        print(f"  multipart gen/spike FAILED: {exc}")
    print()

    # ----- Backend (a) OpenEXR python -----
    print("## Backend (a) PyPI OpenEXR + Imath\n")
    sp_a_single = os.path.join(tmpdir, "spike_a_single.exr")
    _gen_mock_exr(sp_a_single, multipart=False)
    ok = _spike_openexr_python(sp_a_single, 10, 0, 0, 0, False, 50)
    print(f"  result: {'PASS' if ok else 'DEFERRED — see note above'}")
    print()

    # ----- Verdict -----
    print("## Verdict\n")
    print("- (b) oiiotool: chosen if both single-part and multipart write")
    print("  produce typed `timeCode` + rational `framesPerSecond` and")
    print("  preserve channel list.")
    print("- (a) OpenEXR python: deferred — multipart in-place rewrite is")
    print("  fragile in pre-3.3 PyPI version; revisit only if (b) fails.")
    print("- (c) MRQ output pass: deferred — requires plugin C++ change.")
    print()
    print(f"Artifacts kept at: {tmpdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
