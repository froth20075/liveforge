# LiveForge ⚡

Turn any video into a real iPhone **Live Photo / Live Wallpaper** — free, unlimited, no watermarks, no subscription. A full replacement for intoLive Pro, powered by FFmpeg and a hand-crafted Apple Content Identifier pairing.

Every conversion produces `IMG_xxxx.JPG` + `IMG_xxxx.MOV` sharing an Apple Content Identifier — the exact mechanism iOS uses to recognize a Live Photo.

## Three ways to run it

### 1. Locally (Windows / Mac / Linux)

```bash
pip install piexif        # FFmpeg must be on PATH
python liveforge.py clip.mp4 --bounce --preset cinematic --res 15promax
```

| Option | What it does |
|---|---|
| `--start / --end` | Trim (seconds) |
| `--speed 1.5` | Speed up / slow down |
| `--reverse` | Play backwards |
| `--bounce` | Forward-then-backward seamless loop |
| `--keyframe 3.2` | Pick the still frame shown when not pressing |
| `--preset` | `cinematic` `mono` `warm` `cool` `vivid` `fade` `noir` |
| `--res` | `15pro` `15promax` `14` `se` `auto` or `WxH` |
| `--batch` | Convert every video in a folder |

Clips are auto-capped at 5 seconds — iOS's Live Photo sweet spot.

### 2. GitHub Actions — video URL (zero installs, runs in the cloud)

**Actions tab → "Convert video URL to Live Photo" → Run workflow.** Paste a direct video URL, pick your options in the form, run. Download the finished pair from the run's **Artifacts** section.

### 3. GitHub Actions — inbox drop

Drop a video into the `inbox/` folder (GitHub web upload works from your phone) and push. The workflow converts it, commits the pair to `outputs/`, and clears the inbox. Grab the files from `outputs/` or the run artifact.

## Getting the pair onto your iPhone

Upload **both files of a pair together** at [icloud.com](https://www.icloud.com) → Photos. iCloud merges them into one Live Photo. Then: Photos → the Live Photo → set as wallpaper.

## Trigger from an iPhone Shortcut

Create a fine-grained Personal Access Token with `actions: write` on this repo, then a Shortcut with **Get Contents of URL**:

- URL: `https://api.github.com/repos/YOUR_USER/liveforge/actions/workflows/convert-url.yml/dispatches`
- Method: `POST`
- Headers: `Authorization: Bearer YOUR_PAT`, `Accept: application/vnd.github+json`
- Body (JSON):

```json
{
  "ref": "main",
  "inputs": { "video_url": "https://example.com/clip.mp4", "bounce": "true", "preset": "cinematic" }
}
```

Share sheet → conversion in the cloud → download pair → iCloud upload. No computer required.

## How the pairing works

A Live Photo is just a JPEG whose Apple MakerNote contains a `ContentIdentifier` (tag `0x0011`) plus a MOV carrying the same UUID in its `com.apple.quicktime.content.identifier` metadata key. LiveForge writes both from scratch — no macOS frameworks needed.

## License

MIT — build on it, ship it, wallpaper every G63 in Kampala.
