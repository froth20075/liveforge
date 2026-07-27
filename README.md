# LiveForge ⚡

Turn any video into a real iPhone **Live Photo / Live Wallpaper** — free, unlimited, no watermarks, no subscription. A full replacement for intoLive Pro, powered by FFmpeg and a hand-crafted Apple Content Identifier pairing.

Every conversion produces `IMG_xxxx.JPG` + `IMG_xxxx.MOV` sharing an Apple Content Identifier — the exact mechanism iOS uses to recognize a Live Photo.

## Four ways to run it

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
| `--preset` | `cinematic` `amg` `mono` `warm` `cool` `vivid` `fade` `noir` |
| `--res` | `15pro` `15promax` `14` `se` `auto` or `WxH` |
| `--keep-audio` | Real Live Photos have sound — keep it |
| `--text "..."` | Caption overlay |
| `--logo x.png` | PNG watermark (`--logo-pos tl/tr/bl/br/center`) |
| `--lut file.cube` | Apply a color LUT |
| `--crop top/center/bottom` | Crop anchor |
| `--batch --filename-opts` | Folder mode with per-file filename options |

Verify any pair: `python liveforge.py verify IMG.JPG IMG.MOV`

Clips are auto-capped at 5 seconds — iOS's Live Photo sweet spot.

### 2. GitHub Actions — video URL (zero installs, runs in the cloud)

**Actions tab → "Convert video URL to Live Photo" → Run workflow.** Paste a direct video URL, pick your options in the form, run. Download the finished pair from the run's **Artifacts** section.

### 3. GitHub Actions — inbox drop

Drop a video into `inbox/` (GitHub web upload works from your phone). The workflow converts it, commits the pair to `outputs/`, **publishes it as a Release** (direct downloads, no login needed), and clears the inbox.

Encode options right in the filename: `g63__bounce_amg_speed-1.5_k-3_res-15promax.mp4`
Tokens: `bounce` `reverse` `audio` · any preset name · `speed-X` `s-X` `e-X` `k-X` `res-X`

### 4. LiveForge Studio — phone browser control panel

Enable **GitHub Pages** (Settings → Pages → branch `main`, folder `/docs`) and open the site on your iPhone. Save your repo + a fine-grained PAT (Contents:write, Actions:write) once, then: pick a video → toggle effects → **Forge**. Runs and finished pairs (with download buttons) appear right in the page.

### Bonus: LAN server (instant mode)

On any machine with FFmpeg + Python: `node server.js` — zero npm installs. Open the printed LAN URL in Safari on the same Wi-Fi, upload, get the pair back in seconds instead of waiting for a cloud runner.

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
