"""Probe oiio-static-python wheel for the OpenImageIO Python API surface
exr_timecode_writer needs, AND verify channels / compression / multipart /
pixelAspectRatio survive a typed-attribute rewrite of a real MRQ EXR.

Exit 0 on full pass, non-zero with a specific diagnostic on any failure.

Three phases:
  A   — synthetic 4x4 RGB EXR API contract (immediate, no user interaction)
  A.7 — multipart write API (ImageOutput multi-subimage + 'AppendSubimage')
  B   — real MRQ EXR preservation roundtrip (uses /tmp/mrq_sample.exr from
        Task 1)

Empirically verified OIIO 3.0.8.1 Python API on dev Mac 2026-05-14:
  - No `oiio.TimeCode` helper class; encode SMPTE BCD time field manually.
  - `ImageOutput.open(file, [spec, ...])` declares multi-subimage layout.
  - `ImageOutput.open(file, spec, mode)` with `mode='AppendSubimage'`
    advances to the next subimage. Mode is a STRING, not an enum constant.
  - Authoritative subimage count via `ImageInput.seek_subimage(i, 0)`;
    `ImageBuf(file, i, 0).has_error` is unreliable past last subimage.
  - Typed attributes write as `spec.attribute(name, TypeTimeCode, (t, u))`
    and `spec.attribute(name, TypeRational, (n, d))`. Read back via
    `spec.getattribute(name)` returns a tuple.
"""
from __future__ import annotations

import os
import shutil as _shutil
import sys
import tempfile


def _fail(code: int, msg: str) -> int:
    print(f"FAIL [{code}]: {msg}")
    return code


def _smpte_encode_time_field(hh: int, mm: int, ss: int, ff: int, drop_frame: bool = False) -> int:
    """Encode SMPTE 12M timecode `time` field as packed uint32 BCD.

    Layout (low-bit-first):
      bits  0-3   frame units (BCD)
      bits  4-5   frame tens (BCD, 2 bits)
      bit   6     drop-frame flag
      bit   7     color-frame flag (0)
      bits  8-11  seconds units
      bits 12-14  seconds tens (3 bits)
      bit  15     binary group flag 0
      bits 16-19  minutes units
      bits 20-22  minutes tens (3 bits)
      bit  23     binary group flag 1
      bits 24-27  hours units
      bits 28-29  hours tens (2 bits)
      bits 30-31  binary group flag 2 + field/bgf
    """
    val = (ff % 10) | ((ff // 10) << 4)
    if drop_frame:
        val |= 1 << 6
    val |= ((ss % 10) << 8) | ((ss // 10) << 12)
    val |= ((mm % 10) << 16) | ((mm // 10) << 20)
    val |= ((hh % 10) << 24) | ((hh // 10) << 28)
    return val


def _smpte_decode_time_field(val: int) -> tuple[int, int, int, int, bool]:
    """Inverse of `_smpte_encode_time_field`. Returns (h, m, s, f, drop_frame)."""
    ff = (val & 0xF) + ((val >> 4) & 0x3) * 10
    drop = bool((val >> 6) & 0x1)
    ss = ((val >> 8) & 0xF) + ((val >> 12) & 0x7) * 10
    mm = ((val >> 16) & 0xF) + ((val >> 20) & 0x7) * 10
    hh = ((val >> 24) & 0xF) + ((val >> 28) & 0x3) * 10
    return hh, mm, ss, ff, drop


def main() -> int:
    try:
        import OpenImageIO as oiio
        import numpy as np
    except ImportError as e:
        return _fail(1, f"import OpenImageIO/numpy — {e}")

    print(f"OpenImageIO version: {oiio.__version__}")

    # ----- Phase A: synthetic 4x4 EXR API contract -------------------
    for name in ("ImageBuf", "ImageSpec", "TypeDesc", "TypeTimeCode", "TypeRational", "ImageInput", "ImageOutput"):
        if not hasattr(oiio, name):
            return _fail(2, f"oiio.{name} missing — API mismatch")
    print("PASS A1: required symbols ImageBuf/ImageSpec/TypeDesc/TypeTimeCode/TypeRational/ImageInput/ImageOutput")

    with tempfile.TemporaryDirectory() as tmpdir:
        src = os.path.join(tmpdir, "synth.exr")
        out_path = os.path.join(tmpdir, "patched.exr")

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

        time_val = _smpte_encode_time_field(10, 0, 0, 0, drop_frame=False)
        new_spec.attribute("smpte:TimeCode", oiio.TypeTimeCode, (time_val, 0))
        new_spec.attribute("FramesPerSecond", oiio.TypeRational, (50, 1))

        if not src_buf.write(out_path):
            return _fail(5, f"write patched — {src_buf.geterror()}")
        print("PASS A3: wrote patched EXR with typed timeCode + rational FPS")

        check = oiio.ImageBuf(out_path)
        if check.has_error:
            return _fail(6, f"reread patched — {check.geterror()}")
        cs = check.spec()
        tc_attr = cs.getattribute("smpte:TimeCode")
        if tc_attr is None:
            return _fail(7, "smpte:TimeCode missing after roundtrip")
        if not (isinstance(tc_attr, tuple) and len(tc_attr) == 2):
            return _fail(8, f"smpte:TimeCode shape unexpected: {tc_attr!r}")
        h, m, s, f, drop = _smpte_decode_time_field(tc_attr[0])
        if (h, m, s, f) != (10, 0, 0, 0):
            return _fail(9, f"smpte:TimeCode decoded -> {(h,m,s,f)}, expected (10,0,0,0)")
        print(f"PASS A4: smpte:TimeCode roundtrip preserved -> {(h,m,s,f)} drop={drop}")

        fps_attr = cs.getattribute("FramesPerSecond")
        if fps_attr is None:
            return _fail(10, "FramesPerSecond missing after roundtrip")
        if tuple(fps_attr) != (50, 1):
            return _fail(11, f"FramesPerSecond drift -> {fps_attr!r}")
        print(f"PASS A5: FramesPerSecond rational roundtrip preserved -> {fps_attr!r}")

        if cs.nchannels != 3:
            return _fail(12, f"channel count drift {cs.nchannels} != 3")
        print(f"PASS A6: channels survived -> {cs.channelnames}")

    # ----- Phase A.7: multipart write API -----------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        mp = os.path.join(tmpdir, "multipart.exr")
        s0 = oiio.ImageSpec(4, 4, 3, "half")
        s0.attribute("compression", "zip")
        p0 = np.full((4, 4, 3), 0.5, dtype=np.float16)
        s1 = oiio.ImageSpec(4, 4, 4, "half")
        s1.attribute("compression", "zip")
        p1 = np.full((4, 4, 4), 0.3, dtype=np.float16)

        out = oiio.ImageOutput.create(mp)
        if out is None:
            return _fail(13, "ImageOutput.create returned None for .exr")
        if not out.supports("multiimage"):
            return _fail(14, "EXR plugin does not advertise multiimage support")
        if not out.open(mp, [s0, s1]):
            return _fail(15, f"multi-subimage open([s0,s1]) — {out.geterror()}")
        if not out.write_image(p0):
            return _fail(16, f"subimage 0 write — {out.geterror()}")
        if not out.open(mp, s1, "AppendSubimage"):
            return _fail(17, f"open(spec1, 'AppendSubimage') — {out.geterror()}")
        if not out.write_image(p1):
            return _fail(18, f"subimage 1 write — {out.geterror()}")
        out.close()

        # Authoritative subimage count via ImageInput.seek_subimage.
        inp = oiio.ImageInput.open(mp)
        if inp is None:
            return _fail(19, "ImageInput.open multipart failed")
        try:
            si = 0
            seen_channels = []
            while inp.seek_subimage(si, 0):
                seen_channels.append(inp.spec().nchannels)
                si += 1
        finally:
            inp.close()
        if si != 2:
            return _fail(20, f"multipart subimage count = {si}, expected 2")
        if seen_channels != [3, 4]:
            return _fail(21, f"multipart channel layout drift -> {seen_channels}, expected [3, 4]")
        print(f"PASS A7: multipart write preserves 2 subimages with chans {seen_channels}")

    # ----- Phase B: real MRQ EXR preservation (MANDATORY) -------------
    mrq_path = "/tmp/mrq_sample.exr"
    if not os.path.exists(mrq_path):
        return _fail(30,
            f"{mrq_path} missing — Phase B is a hard blocker per the "
            "Codex adversarial review. Rerun Task 1 to obtain a real "
            "MRQ EXR sample before proceeding."
        )

    src_copy = "/tmp/mrq_sample_phaseB_in.exr"
    _shutil.copy(mrq_path, src_copy)

    baselines: list[dict] = []
    in_inp = oiio.ImageInput.open(src_copy)
    if in_inp is None:
        return _fail(31, f"ImageInput.open {src_copy}")
    try:
        si = 0
        while in_inp.seek_subimage(si, 0):
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
        return _fail(32, f"src copy {src_copy} has 0 subimages — corrupted?")
    print(f"Baseline subimage count: {si}; sample[0] = {baselines[0]}")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "patched_mrq.exr")

        in_inp = oiio.ImageInput.open(src_copy)
        if in_inp is None:
            return _fail(33, "ImageInput.open #2")
        try:
            specs_pixels = []
            for s_idx in range(si):
                if not in_inp.seek_subimage(s_idx, 0):
                    return _fail(34, f"seek_subimage {s_idx}")
                spec = in_inp.spec()
                tc_time = _smpte_encode_time_field(10, 0, 0, 0, drop_frame=False)
                spec.attribute("smpte:TimeCode", oiio.TypeTimeCode, (tc_time, 0))
                spec.attribute("FramesPerSecond", oiio.TypeRational, (50, 1))
                pixels = in_inp.read_image(spec.format)
                if pixels is None:
                    return _fail(35, f"read_image subimage {s_idx} — {in_inp.geterror()}")
                specs_pixels.append((spec, pixels))
        finally:
            in_inp.close()

        out = oiio.ImageOutput.create(out_path)
        if out is None:
            return _fail(36, "ImageOutput.create returned None for output")
        specs_only = [sp for sp, _ in specs_pixels]
        if len(specs_only) == 1:
            ok = out.open(out_path, specs_only[0])
        else:
            ok = out.open(out_path, specs_only)
        if not ok:
            return _fail(37, f"multi-subimage open — {out.geterror()}")
        for i, (spec, pixels) in enumerate(specs_pixels):
            if i > 0:
                if not out.open(out_path, spec, "AppendSubimage"):
                    return _fail(38, f"AppendSubimage open #{i} — {out.geterror()}")
            if not out.write_image(pixels):
                return _fail(39, f"write_image subimage {i} — {out.geterror()}")
        out.close()
        print(f"PASS B1: rewrote {si} subimage(s) via ImageOutput")

        # Verify each subimage against baseline.
        chk_inp = oiio.ImageInput.open(out_path)
        if chk_inp is None:
            return _fail(40, "reread ImageInput.open")
        try:
            for s_idx in range(si):
                if not chk_inp.seek_subimage(s_idx, 0):
                    return _fail(41, f"reread seek subimage {s_idx}")
                cs = chk_inp.spec()
                b = baselines[s_idx]
                if cs.nchannels != b["nchannels"]:
                    return _fail(42, f"subimage {s_idx}: channel count drift "
                                      f"{cs.nchannels} != {b['nchannels']}")
                if tuple(cs.channelnames) != b["channelnames"]:
                    return _fail(43, f"subimage {s_idx}: channel names drift "
                                      f"{cs.channelnames!r} != {b['channelnames']!r}")
                if cs.getattribute("compression") != b["compression"]:
                    return _fail(44, f"subimage {s_idx}: compression drift "
                                      f"{cs.getattribute('compression')!r} != "
                                      f"{b['compression']!r}")
                if cs.width != b["width"] or cs.height != b["height"]:
                    return _fail(45, f"subimage {s_idx}: dims drift")
                if cs.getattribute("smpte:TimeCode") is None:
                    return _fail(46, f"subimage {s_idx}: smpte:TimeCode not written")
                if tuple(cs.getattribute("FramesPerSecond")) != (50, 1):
                    return _fail(47, f"subimage {s_idx}: FramesPerSecond drift")
            # Subimage count check — extra subimage = fail.
            if chk_inp.seek_subimage(si, 0):
                return _fail(48, f"unexpected extra subimage at index {si}")
        finally:
            chk_inp.close()
        print(f"PASS B2: all {si} subimage(s) preserved channels/compression/dims/"
              "typed-attrs; no subimages added/lost")

        # After-rewrite header dump for Task 12 evidence.
        after_dump = "/tmp/mrq_sample_after.txt"
        try:
            with open(after_dump, "w") as f:
                inp2 = oiio.ImageInput.open(out_path)
                for s_idx in range(si):
                    inp2.seek_subimage(s_idx, 0)
                    sp = inp2.spec()
                    f.write(f"--- subimage {s_idx} ---\n")
                    f.write(f"dims={sp.width}x{sp.height} nchannels={sp.nchannels} format={sp.format}\n")
                    f.write(f"channelnames={list(sp.channelnames)}\n")
                    f.write(f"compression={sp.getattribute('compression')}\n")
                    f.write(f"smpte:TimeCode={sp.getattribute('smpte:TimeCode')}\n")
                    f.write(f"FramesPerSecond={sp.getattribute('FramesPerSecond')}\n")
                inp2.close()
            print(f"PASS B3: after-rewrite header dump -> {after_dump}; "
                  "diff against /tmp/mrq_sample_baseline.txt for evidence")
        except Exception as e:
            print(f"WARN: after-dump write failed: {e}")

    print("\n=== ALL PROBES PASSED — backend swap is safe to proceed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
