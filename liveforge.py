#!/usr/bin/env python3
"""
LiveForge — turn any video into an iPhone Live Photo / Live Wallpaper pair.
A free, unlimited replacement for intoLive Pro.

Requires: Python 3.9+, FFmpeg on PATH, `pip install piexif`

Usage examples:
  python liveforge.py input.mp4
  python liveforge.py input.mp4 --start 2 --end 6 --keyframe 3.5
  python liveforge.py input.mp4 --bounce --speed 1.5 --preset cinematic
  python liveforge.py input.mp4 --reverse --res 1290x2796
  python liveforge.py folder_of_clips --batch

Output: a paired IMG_xxxx.JPG + IMG_xxxx.MOV sharing an Apple Content
Identifier. Import both together (iCloud.com upload is the reliable
Windows route) and iOS merges them into a single Live Photo.
"""

import argparse
import os
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
}

# Common iPhone wallpaper resolutions (portrait)
RES_PRESETS = {
    "15pro":    "1179x2556",
    "15promax": "1290x2796",
    "14":       "1170x2532",
    "se":       "750x1334",
    "auto":     "1290x2796",   # max-size default, iOS scales down fine
}

MAX_LIVE_SECONDS = 5.0  # iOS keeps Live Photos short; >5s risks rejection


# ------------------------------------------------------- ffmpeg helpers ----

def run(cmd, quiet=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        sys.exit(f"Command failed: {' '.join(cmd[:6])} ...")
    return r


def ffprobe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(r.stdout.strip())
    except ValueError:
        sys.exit(f"Could not read duration of {path}")


# ------------------------------------------- Apple MakerNote (the magic) ----

def build_apple_makernote(content_id: str) -> bytes:
    """Minimal Apple MakerNote containing only ContentIdentifier (tag 0x0011).

    Layout: 14-byte header 'Apple iOS\\x00\\x00\\x01MM', then one big-endian
    IFD. Value offsets are relative to the start of the MakerNote blob.
    """
    header = b"Apple iOS\x00\x00\x01MM"
    value = content_id.encode("ascii") + b"\x00"
    # header(14) + count(2) + entry(12) + next_ifd(4) = 32
    value_offset = 32
    ifd = struct.pack(">H", 1)                                  # 1 entry
    ifd += struct.pack(">HHII", 0x0011, 2, len(value), value_offset)
    ifd += struct.pack(">I", 0)                                 # next IFD = 0
    return header + ifd + value


def inject_jpeg_identifier(jpeg_path: Path, content_id: str):
    try:
        exif = piexif.load(str(jpeg_path))
    except Exception:
        exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    exif.setdefault("Exif", {})
    exif["Exif"][piexif.ExifIFD.MakerNote] = build_apple_makernote(content_id)
    piexif.insert(piexif.dump(exif), str(jpeg_path))


# ----------------------------------------------------------- core pipeline --

def build_video_filter(args, target_res):
    w, h = target_res.split("x")
    parts = []
    # center-crop to target aspect then scale
    parts.append(
        f"crop='min(iw,ih*{w}/{h})':'min(ih,iw*{h}/{w})',scale={w}:{h}"
    )
    if args.speed != 1.0:
        parts.append(f"setpts=PTS/{args.speed}")
    if args.reverse:
        parts.append("reverse")
    preset = FILTER_PRESETS.get(args.preset)
    if preset:
        parts.append(preset)
    return ",".join(parts)


def convert(src: Path, outdir: Path, args, index: int):
    duration = ffprobe_duration(src)
    start = max(0.0, args.start)
    end = min(duration, args.end) if args.end else duration
    if end <= start:
        sys.exit("--end must be greater than --start")

    effective = (end - start) / args.speed
    if args.bounce:
        effective *= 2
    if effective > MAX_LIVE_SECONDS:
        # auto-trim rather than fail
        allowed = MAX_LIVE_SECONDS * args.speed / (2 if args.bounce else 1)
        end = start + allowed
        print(f"  [auto-trim] clip capped at {allowed:.2f}s source time "
              f"to keep the Live Photo under {MAX_LIVE_SECONDS:.0f}s")

    content_id = str(uuid.uuid4()).upper()
    stem = f"IMG_{7000 + index:04d}"
    mov_out = outdir / f"{stem}.MOV"
    jpg_out = outdir / f"{stem}.JPG"

    res = RES_PRESETS.get(args.res, args.res)
    if not re.fullmatch(r"\d+x\d+", res):
        sys.exit(f"Bad --res value: {args.res}")

    vf = build_video_filter(args, res)
    if args.bounce:
        vf_full = f"{vf},split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1"
    else:
        vf_full = vf

    print(f"» {src.name}  →  {stem}.JPG + {stem}.MOV   (id {content_id[:8]}…)")

    # 1) The MOV — H.264, no audio (wallpapers are silent), with the
    #    QuickTime content identifier written into the mdta keys atom.
    run([
        "ffmpeg", "-y", "-ss", f"{start}", "-to", f"{end}", "-i", str(src),
        "-filter_complex" if args.bounce else "-vf", vf_full,
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "medium", "-crf", "20", "-r", "30",
        "-movflags", "use_metadata_tags",
        "-metadata", f"com.apple.quicktime.content.identifier={content_id}",
        "-f", "mov", str(mov_out),
    ])

    # 2) The still keyframe — grabbed from the *processed* MOV so filters,
    #    speed and reverse all match what plays.
    mov_dur = ffprobe_duration(mov_out)
    key_t = mov_dur / 2
    if args.keyframe is not None:
        key_t = min(max(0.0, (args.keyframe - start) / args.speed),
                    max(mov_dur - 0.05, 0))
    run([
        "ffmpeg", "-y", "-ss", f"{key_t}", "-i", str(mov_out),
        "-frames:v", "1", "-q:v", "2", str(jpg_out),
    ])

    # 3) Pair them with the shared Apple Content Identifier.
    inject_jpeg_identifier(jpg_out, content_id)
    return jpg_out, mov_out, content_id


# ------------------------------------------------------------------- main ---

def main():
    p = argparse.ArgumentParser(description="Video → iPhone Live Photo pair")
    p.add_argument("input", help="video file, or a folder with --batch")
    p.add_argument("-o", "--outdir", default="live_out")
    p.add_argument("--start", type=float, default=0.0, help="trim start (s)")
    p.add_argument("--end", type=float, default=None, help="trim end (s)")
    p.add_argument("--speed", type=float, default=1.0, help="e.g. 2 = 2x")
    p.add_argument("--reverse", action="store_true")
    p.add_argument("--bounce", action="store_true",
                   help="forward-then-backward seamless loop")
    p.add_argument("--keyframe", type=float, default=None,
                   help="source timestamp for the still image (default: middle)")
    p.add_argument("--preset", default="none",
                   choices=sorted(FILTER_PRESETS.keys()))
    p.add_argument("--res", default="auto",
                   help="15pro | 15promax | 14 | se | auto | WxH")
    p.add_argument("--batch", action="store_true",
                   help="convert every video in the input folder")
    args = p.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("FFmpeg not found on PATH")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    src = Path(args.input)

    vids = []
    if args.batch:
        exts = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".gif"}
        vids = sorted(x for x in src.iterdir() if x.suffix.lower() in exts)
        if not vids:
            sys.exit(f"No videos found in {src}")
    else:
        vids = [src]

    results = []
    for i, v in enumerate(vids, start=1):
        results.append(convert(v, outdir, args, i))

    print(f"\nDone — {len(results)} Live Photo pair(s) in {outdir.resolve()}")
    print("Import route (Windows → iPhone): upload BOTH files of a pair "
          "together at icloud.com → Photos. iOS merges them into one "
          "Live Photo automatically.")


if __name__ == "__main__":
    main()
