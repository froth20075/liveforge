#!/usr/bin/env python3
"""
LiveForge v2 — turn any video into an iPhone Live Photo / Live Wallpaper pair.
A free, unlimited replacement for intoLive Pro.

Requires: Python 3.9+, FFmpeg on PATH, `pip install piexif`

Quick start:
  python liveforge.py convert clip.mp4 --bounce --preset cinematic --res 15promax
  python liveforge.py convert clip.mp4 --logo gcm.png --text "GERMAN CAR MEDIC"
  python liveforge.py convert folder --batch --filename-opts
  python liveforge.py verify live_out/IMG_7001.JPG live_out/IMG_7001.MOV

Output: paired IMG_xxxx.JPG + IMG_xxxx.MOV sharing an Apple Content
Identifier. Upload BOTH together at icloud.com -> Photos and iOS merges
them into a single Live Photo.
"""

import argparse
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import uuid
from pathlib import Path

try:
    import piexif
except ImportError:
    sys.exit("Missing dependency: run  pip install piexif")

# ---------------------------------------------------------------- presets ---

FILTER_PRESETS = {
    "none":      None,
    "cinematic": "eq=contrast=1.12:saturation=1.18:brightness=0.01,unsharp=3:3:0.4",
    "mono":      "hue=s=0,eq=contrast=1.15",
    "warm":      "colorbalance=rm=0.08:gm=0.02:bm=-0.06,eq=saturation=1.1",
    "cool":      "colorbalance=rm=-0.06:bm=0.08,eq=saturation=1.05",
    "vivid":     "eq=contrast=1.2:saturation=1.45",
    "fade":      "curves=all='0/0.06 0.5/0.5 1/0.94',eq=saturation=0.85",
    "noir":      "hue=s=0,curves=all='0/0 0.4/0.28 1/1',vignette=PI/5",
    "amg":       "eq=contrast=1.18:saturation=1.25,colorbalance=rm=0.03:bm=-0.03,"
                 "unsharp=5:5:0.6,vignette=PI/6",   # bold cinematic showroom look
}

RES_PRESETS = {
    "15pro": "1179x2556", "15promax": "1290x2796", "16promax": "1320x2868",
    "14": "1170x2532", "13mini": "1080x2340", "se": "750x1334",
    "auto": "1290x2796", "square": "1080x1080", "landscape": "1920x1080",
}

LOGO_POS = {
    "tl": "24:24", "tr": "W-w-24:24", "bl": "24:H-h-24",
    "br": "W-w-24:H-h-24", "center": "(W-w)/2:(H-h)/2",
}

MAX_LIVE_SECONDS = 5.0


# ------------------------------------------------------- ffmpeg helpers ----

def run(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        sys.exit(f"Command failed: {' '.join(str(c) for c in cmd[:6])} ...")
    return r


def ffprobe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(r.stdout.strip())
    except ValueError:
        sys.exit(f"Could not read duration of {path}")


def has_audio(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)])
    return "audio" in r.stdout


def find_font():
    """Locate a bold system font for drawtext, cross-platform."""
    candidates = []
    if platform.system() == "Windows":
        w = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        candidates = [w / "arialbd.ttf", w / "arial.ttf", w / "segoeuib.ttf"]
    elif platform.system() == "Darwin":
        candidates = [Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
                      Path("/System/Library/Fonts/Helvetica.ttc")]
    else:
        candidates = [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


# ------------------------------------------- Apple MakerNote (the magic) ----

def build_apple_makernote(content_id: str) -> bytes:
    """Minimal Apple MakerNote containing only ContentIdentifier (0x0011)."""
    header = b"Apple iOS\x00\x00\x01MM"
    value = content_id.encode("ascii") + b"\x00"
    value_offset = 32  # header(14) + count(2) + entry(12) + next_ifd(4)
    ifd = struct.pack(">H", 1)
    ifd += struct.pack(">HHII", 0x0011, 2, len(value), value_offset)
    ifd += struct.pack(">I", 0)
    return header + ifd + value


def inject_jpeg_identifier(jpeg_path: Path, content_id: str):
    try:
        exif = piexif.load(str(jpeg_path))
    except Exception:
        exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    exif.setdefault("Exif", {})
    exif["Exif"][piexif.ExifIFD.MakerNote] = build_apple_makernote(content_id)
    exif.setdefault("0th", {})[piexif.ImageIFD.Make] = b"Apple"
    piexif.insert(piexif.dump(exif), str(jpeg_path))


def read_jpeg_identifier(jpeg_path: Path):
    try:
        exif = piexif.load(str(jpeg_path))
        note = exif.get("Exif", {}).get(piexif.ExifIFD.MakerNote, b"")
    except Exception:
        return None
    m = re.search(rb"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-"
                  rb"[0-9A-F]{12}", note)
    return m.group(0).decode() if m else None


def mov_contains_identifier(mov_path: Path, content_id: str):
    data = mov_path.read_bytes()
    return (b"com.apple.quicktime.content.identifier" in data
            and content_id.encode() in data)


# ----------------------------------------------------- filename options ----

def parse_filename_opts(stem: str, base_args):
    """clip__bounce_amg_speed-1.5_s-2_e-6_k-3_res-15promax.mp4 style tokens."""
    import copy
    a = copy.copy(base_args)
    if "__" not in stem:
        return a
    for tok in stem.split("__", 1)[1].split("_"):
        t = tok.lower()
        if t == "bounce":
            a.bounce = True
        elif t == "reverse":
            a.reverse = True
        elif t == "audio":
            a.keep_audio = True
        elif t in FILTER_PRESETS:
            a.preset = t
        elif t.startswith("speed-"):
            a.speed = float(t[6:])
        elif t.startswith("s-"):
            a.start = float(t[2:])
        elif t.startswith("e-"):
            a.end = float(t[2:])
        elif t.startswith("k-"):
            a.keyframe = float(t[2:])
        elif t.startswith("res-"):
            a.res = t[4:]
    return a


# ----------------------------------------------------------- core pipeline --

def build_video_filter(args, target_res):
    w, h = target_res.split("x")
    anchor = {"top": "0", "center": "(ih-oh)/2", "bottom": "ih-oh"}[args.crop]
    parts = [
        f"crop=w='min(iw,ih*{w}/{h})':h='min(ih,iw*{h}/{w})':x='(iw-ow)/2':y='{anchor}',"
        f"scale={w}:{h}"
    ]
    if args.speed != 1.0:
        parts.append(f"setpts=PTS/{args.speed}")
    if args.reverse:
        parts.append("reverse")
    if args.lut:
        lut = str(Path(args.lut).resolve()).replace("\\", "/").replace(":", "\\:")
        parts.append(f"lut3d='{lut}'")
    preset = FILTER_PRESETS.get(args.preset)
    if preset:
        parts.append(preset)
    if args.text:
        font = find_font()
        fontarg = f"fontfile='{font}':" if font else ""
        txt = args.text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "")
        parts.append(
            f"drawtext={fontarg}text='{txt}':fontsize=h/18:fontcolor=white:"
            f"borderw=3:bordercolor=black@0.6:x=(w-text_w)/2:y=h-h/8"
        )
    return ",".join(parts)


def verify_pair(jpg_path: Path, mov_path: Path, content_id: str):
    """Structural check only; Photos/iCloud import remains the final compatibility test."""
    if read_jpeg_identifier(jpg_path) != content_id:
        return False
    if not mov_contains_identifier(mov_path, content_id):
        return False
    data = mov_path.read_bytes()
    top = _parse_boxes(data, 0, len(data))
    moov = next((b for b in top if b[2] == b"moov"), None)
    if not moov:
        return False
    tracks = [b for b in _parse_boxes(data, moov[0]+moov[3], moov[0]+moov[1]) if b[2] == b"trak"]
    for track in tracks:
        mdia = next((b for b in _parse_boxes(data, track[0]+track[3], track[0]+track[1]) if b[2] == b"mdia"), None)
        if not mdia:
            continue
        minf = next((b for b in _parse_boxes(data, mdia[0]+mdia[3], mdia[0]+mdia[1]) if b[2] == b"minf"), None)
        if not minf:
            continue
        stbl = next((b for b in _parse_boxes(data, minf[0]+minf[3], minf[0]+minf[1]) if b[2] == b"stbl"), None)
        if not stbl:
            continue
        children = _parse_boxes(data, stbl[0]+stbl[3], stbl[0]+stbl[1])
        stsd = next((b for b in children if b[2] == b"stsd"), None)
        stsz = next((b for b in children if b[2] == b"stsz"), None)
        if not stsd or not stsz:
            continue
        payload = data[stsd[0]:stsd[0]+stsd[1]]
        if b"mebx" in payload and b"com.apple.quicktime.still-image-time" in payload:
            return int.from_bytes(data[stsz[0]+16:stsz[0]+20], "big") > 0
    return False


def convert(src: Path, outdir: Path, base_args, index: int):
    args = (parse_filename_opts(src.stem, base_args)
            if getattr(base_args, "filename_opts", False) else base_args)

    duration = ffprobe_duration(src)
    start = max(0.0, args.start)
    end = min(duration, args.end) if args.end else duration
    if end <= start:
        sys.exit("--end must be greater than --start")

    effective = (end - start) / args.speed * (2 if args.bounce else 1)
    if effective > MAX_LIVE_SECONDS:
        allowed = MAX_LIVE_SECONDS * args.speed / (2 if args.bounce else 1)
        end = start + allowed
        print(f"  [auto-trim] capped at {allowed:.2f}s source time "
              f"(≤{MAX_LIVE_SECONDS:.0f}s Live Photo)")

    content_id = str(uuid.uuid4()).upper()
    stem = f"IMG_{7000 + index:04d}"
    mov_out = outdir / f"{stem}.MOV"
    jpg_out = outdir / f"{stem}.JPG"

    res = RES_PRESETS.get(args.res, args.res)
    if not re.fullmatch(r"\d+x\d+", res):
        sys.exit(f"Bad --res value: {args.res}")
    rw, rh = (int(v) // 2 * 2 for v in res.split("x"))  # libx264 needs even
    res = f"{rw}x{rh}"

    vf = build_video_filter(args, res)

    print(f"» {src.name}  →  {stem}  (id {content_id[:8]}…)")

    keep_audio = args.keep_audio and has_audio(src) and not args.reverse \
        and not args.bounce and args.speed == 1.0

    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", f"{start}", "-to", f"{end}", "-i", str(src)]

    if args.logo:
        cmd += ["-i", str(args.logo)]
        pos = LOGO_POS.get(args.logo_pos, args.logo_pos)
        logo_w = int(int(res.split("x")[0]) * args.logo_scale / 4)
        fc = (f"[0:v]{vf}[base];"
              f"[1:v]scale={logo_w}:-1[lg];"
              f"[base][lg]overlay={pos}")
        if args.bounce:
            fc += ",split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1"
        cmd += ["-filter_complex", fc]
    elif args.bounce:
        cmd += ["-filter_complex",
                f"{vf},split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1"]
    else:
        cmd += ["-vf", vf]

    if keep_audio:
        cmd += ["-c:a", "aac", "-b:a", "96k"]
    else:
        cmd += ["-an"]

    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "medium", "-crf", "19", "-r", str(args.fps),
            "-movflags", "use_metadata_tags",
            "-metadata", f"com.apple.quicktime.content.identifier={content_id}",
            "-metadata", "com.apple.quicktime.live-photo.auto=1",
            "-f", "mov", str(mov_out)]
    run(cmd)

    # Still keyframe grabbed from the processed MOV so all effects match
    mov_dur = ffprobe_duration(mov_out)
    key_t = mov_dur / 2
    if args.keyframe is not None:
        key_t = min(max(0.0, (args.keyframe - start) / args.speed),
                    max(mov_dur - 0.05, 0))
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{key_t}", "-i", str(mov_out),
         "-frames:v", "1", "-q:v", "2", str(jpg_out)])

    inject_jpeg_identifier(jpg_out, content_id)
    inject_still_image_time(mov_out, key_t)

    ok = (read_jpeg_identifier(jpg_out) == content_id
          and mov_contains_identifier(mov_out, content_id))
    print(f"  structural pair check: {'✓ PASSED' if ok else '✗ FAILED'}"
          f"   still@{key_t:.2f}s   {mov_dur:.2f}s clip")
    return ok




# ---------------------------------------- still-image-time track (mebx) -----
# Photos requires the MOV to carry a timed-metadata track holding
# com.apple.quicktime.still-image-time; without it, iCloud will not pair.

def _b(kind, payload):
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _fb(kind, payload, version=0, flags=0):
    return _b(kind, struct.pack(">B", version) + flags.to_bytes(3, "big") + payload)


def _parse_boxes(data, start, end):
    out = []
    off = start
    while off + 8 <= end:
        size = int.from_bytes(data[off:off+4], "big")
        kind = bytes(data[off+4:off+8])
        hdr = 8
        if size == 1:
            size = int.from_bytes(data[off+8:off+16], "big"); hdr = 16
        elif size == 0:
            size = end - off
        if size < hdr:
            break
        out.append((off, size, kind, hdr))
        off += size
    return out


def inject_still_image_time(mov_path: Path, still_seconds: float):
    data = bytearray(mov_path.read_bytes())
    top = _parse_boxes(data, 0, len(data))
    moov = next((t for t in top if t[2] == b"moov"), None)
    mdat = next((t for t in reversed(top) if t[2] == b"mdat"), None)
    if not moov or not mdat:
        sys.exit("still-image-time: moov/mdat not found")
    if moov[0] < mdat[0]:
        sys.exit("still-image-time: faststart layout unsupported")

    # movie header: timescale / duration / next track id
    mvhd = next(t for t in _parse_boxes(data, moov[0]+moov[3], moov[0]+moov[1])
                if t[2] == b"mvhd")
    v = data[mvhd[0]+8]
    p = mvhd[0] + 12
    if v == 1:
        mts = int.from_bytes(data[p+16:p+20], "big")
        mdur = int.from_bytes(data[p+20:p+28], "big")
    else:
        mts = int.from_bytes(data[p+8:p+12], "big")
        mdur = int.from_bytes(data[p+12:p+16], "big")
    nid_off = mvhd[0] + mvhd[1] - 4
    track_id = int.from_bytes(data[nid_off:nid_off+4], "big")
    data[nid_off:nid_off+4] = struct.pack(">I", track_id + 1)

    still_mv = min(max(0, round(still_seconds * mts)), max(mdur - 1, 0))
    span_mv = max(mdur - still_mv, 1)
    mts_meta = 600
    span_meta = max(round(span_mv * mts_meta / mts), 1)

    sample = b"\x00\x00\x00\x09\x00\x00\x00\x01\xff"
    sample_off = mdat[0] + mdat[1]          # append at current mdat end
    if sample_off != moov[0]:
        raise ValueError("Unsupported MOV layout: mdat must immediately precede moov")

    keyd = _b(b"keyd", b"mdta" + b"com.apple.quicktime.still-image-time")
    # Full-box header (version/flags), entry count, then the key record.
    keys = _fb(b"keys", struct.pack(">I", 1) + keyd)
    mebx = _b(b"mebx", b"\x00"*6 + struct.pack(">H", 1) + keys)
    stsd = _fb(b"stsd", struct.pack(">I", 1) + mebx)
    stts = _fb(b"stts", struct.pack(">III", 1, 1, span_meta))
    stsc = _fb(b"stsc", struct.pack(">IIII", 1, 1, 1, 1))
    stsz = _fb(b"stsz", struct.pack(">II", len(sample), 1))
    stco = _fb(b"stco", struct.pack(">II", 1, sample_off))
    stbl = _b(b"stbl", stsd + stts + stsc + stsz + stco)
    url_ = _fb(b"url ", b"", flags=1)
    dref = _fb(b"dref", struct.pack(">I", 1) + url_)
    dinf = _b(b"dinf", dref)
    nmhd = _fb(b"nmhd", b"")
    minf = _b(b"minf", nmhd + dinf + stbl)
    hdlr = _fb(b"hdlr", b"\x00"*4 + b"meta" + b"\x00"*12 +
               b"Core Media Metadata\x00")
    mdhd = _fb(b"mdhd", struct.pack(">IIIIHH", 0, 0, mts_meta, span_meta,
                                    0x55C4, 0))
    mdia = _b(b"mdia", mdhd + hdlr + minf)
    entries = b""
    if still_mv > 0:
        entries += struct.pack(">IiI", still_mv, -1, 0x00010000)
    entries += struct.pack(">IiI", span_mv, 0, 0x00010000)
    elst = _fb(b"elst", struct.pack(">I", 2 if still_mv else 1) + entries)
    edts = _b(b"edts", elst)
    matrix = struct.pack(">9i", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    tkhd = _fb(b"tkhd", struct.pack(">IIIII", 0, 0, track_id, 0, mdur) +
               b"\x00"*8 + struct.pack(">HHHH", 0, 0, 0, 0) + matrix +
               struct.pack(">II", 0, 0), flags=7)
    trak = _b(b"trak", tkhd + edts + mdia)

    # splice: sample after mdat, trak at end of moov (moov sits after mdat)
    new = bytes(data[:sample_off]) + sample + bytes(data[sample_off:])
    new = bytearray(new)
    # patch mdat size
    if mdat[3] == 16:
        new[mdat[0]+8:mdat[0]+16] = struct.pack(">Q", mdat[1] + len(sample))
    else:
        new[mdat[0]:mdat[0]+4] = struct.pack(">I", mdat[1] + len(sample))
    moov_off = moov[0] + len(sample)
    moov_end = moov_off + moov[1]
    new = new[:moov_end] + trak + new[moov_end:]
    new[moov_off:moov_off+4] = struct.pack(">I", moov[1] + len(trak))
    mov_path.write_bytes(bytes(new))


# ------------------------------------------------------------------- main ---

def add_convert_args(p):
    p.add_argument("input", help="video file, or a folder with --batch")
    p.add_argument("-o", "--outdir", default="live_out")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=None)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--reverse", action="store_true")
    p.add_argument("--bounce", action="store_true")
    p.add_argument("--keyframe", type=float, default=None)
    p.add_argument("--preset", default="none", choices=sorted(FILTER_PRESETS))
    p.add_argument("--lut", default=None, help="path to a .cube LUT file")
    p.add_argument("--res", default="auto")
    p.add_argument("--crop", default="center", choices=["top", "center", "bottom"])
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--keep-audio", action="store_true",
                   help="keep audio (real Live Photos have sound; "
                        "disabled automatically with bounce/reverse/speed)")
    p.add_argument("--text", default=None, help="caption overlay")
    p.add_argument("--logo", default=None, help="PNG watermark path")
    p.add_argument("--logo-pos", default="br",
                   help="tl | tr | bl | br | center | x:y")
    p.add_argument("--logo-scale", type=float, default=1.0)
    p.add_argument("--batch", action="store_true")
    p.add_argument("--filename-opts", action="store_true",
                   help="parse options from filenames: "
                        "clip__bounce_amg_speed-1.5_res-15promax.mp4")


def main():
    top = argparse.ArgumentParser(description="LiveForge v2")
    sub = top.add_subparsers(dest="cmd")

    pc = sub.add_parser("convert", help="convert video(s) to Live Photo pairs")
    add_convert_args(pc)

    pv = sub.add_parser("verify", help="verify a JPG+MOV pair")
    pv.add_argument("jpg")
    pv.add_argument("mov")

    # Back-compat: `liveforge.py video.mp4 ...` still works
    argv = sys.argv[1:]
    if argv and argv[0] not in ("convert", "verify", "-h", "--help"):
        argv = ["convert"] + argv
    args = top.parse_args(argv)

    if args.cmd == "verify":
        cid = read_jpeg_identifier(Path(args.jpg))
        if not cid:
            sys.exit("✗ No Apple ContentIdentifier found in JPEG")
        if verify_pair(Path(args.jpg), Path(args.mov), cid):
            print(f"✓ STRUCTURAL CHECK PASSED — shared identifier {cid} (Photos import not yet confirmed)")
        else:
            sys.exit(f"✗ MOV does not carry identifier {cid}")
        return

    if shutil.which("ffmpeg") is None:
        sys.exit("FFmpeg not found on PATH")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    src = Path(args.input)

    if args.batch:
        exts = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".gif"}
        vids = sorted(x for x in src.iterdir() if x.suffix.lower() in exts)
        if not vids:
            sys.exit(f"No videos found in {src}")
    else:
        vids = [src]

    ok_all = all(convert(v, outdir, args, i) for i, v in enumerate(vids, 1))
    print(f"\nDone — {len(vids)} pair(s) in {outdir.resolve()}")
    print("Import: upload BOTH files of a pair together at icloud.com → Photos.")
    if not ok_all:
        sys.exit(1)


if __name__ == "__main__":
    main()
