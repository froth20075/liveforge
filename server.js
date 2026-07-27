#!/usr/bin/env node
/**
 * LiveForge LAN Server — instant Live Photo conversion on your own network.
 * Zero npm dependencies. Node 18+, FFmpeg + Python (liveforge.py) required.
 *
 *   node server.js            → http://<your-LAN-IP>:7433
 *
 * Open that URL in Safari on your iPhone (same Wi-Fi), upload a clip,
 * get the JPG+MOV pair back in seconds. Long-press each → Save to Files,
 * then upload both together at icloud.com → Photos.
 */
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");

const PORT = 7433;
const OUT = path.join(__dirname, "server_out");
const TMP = path.join(__dirname, "server_tmp");
for (const d of [OUT, TMP]) fs.mkdirSync(d, { recursive: true });

const PY = process.platform === "win32" ? "python" : "python3";
let counter = Date.now() % 100000;

// ---------------------------------------------------------------- helpers --

function lanIP() {
  for (const ifs of Object.values(os.networkInterfaces()))
    for (const i of ifs || [])
      if (i.family === "IPv4" && !i.internal) return i.address;
  return "localhost";
}

/** Minimal multipart/form-data parser (single file + text fields). */
function parseMultipart(buf, boundary) {
  const b = Buffer.from(`--${boundary}`);
  const fields = {}; let file = null;
  let idx = buf.indexOf(b);
  while (idx !== -1) {
    const next = buf.indexOf(b, idx + b.length);
    if (next === -1) break;
    const part = buf.subarray(idx + b.length + 2, next - 2); // trim CRLFs
    const headEnd = part.indexOf("\r\n\r\n");
    if (headEnd !== -1) {
      const head = part.subarray(0, headEnd).toString();
      const body = part.subarray(headEnd + 4);
      const name = /name="([^"]+)"/.exec(head)?.[1];
      const fname = /filename="([^"]*)"/.exec(head)?.[1];
      if (fname) file = { name: fname || "clip.mp4", data: body };
      else if (name) fields[name] = body.toString().trim();
    }
    idx = next;
  }
  return { fields, file };
}

function runForge(input, opts, outdir) {
  const args = [path.join(__dirname, "liveforge.py"), "convert", input,
                "--outdir", outdir];
  if (opts.bounce === "on") args.push("--bounce");
  if (opts.reverse === "on") args.push("--reverse");
  if (opts.audio === "on") args.push("--keep-audio");
  if (opts.preset && opts.preset !== "none") args.push("--preset", opts.preset);
  if (opts.start) args.push("--start", opts.start);
  if (opts.end) args.push("--end", opts.end);
  if (opts.speed && opts.speed !== "1") args.push("--speed", opts.speed);
  if (opts.keyframe) args.push("--keyframe", opts.keyframe);
  args.push("--res", opts.res || "auto");
  return new Promise((resolve, reject) => {
    const p = spawn(PY, args);
    let err = "";
    p.stderr.on("data", d => (err += d));
    p.on("close", c => (c === 0 ? resolve() : reject(new Error(err.slice(-800)))));
  });
}

// ------------------------------------------------------------------- page --

const PAGE = `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LiveForge LAN</title><style>
body{background:#0a0c0e;color:#c9d4dc;font:14px ui-monospace,monospace;
  max-width:520px;margin:0 auto;padding:20px}
h1{color:#fff;font-size:20px;letter-spacing:.05em}h1 b{color:#ffb400}
label{display:block;color:#5d6b76;font-size:10px;text-transform:uppercase;
  letter-spacing:.12em;margin:14px 0 4px}
input,select{width:100%;background:#080a0c;color:#c9d4dc;border:1px solid #1e262c;
  border-radius:4px;padding:10px;font:inherit;box-sizing:border-box}
.r{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
.cb{display:flex;gap:16px;margin-top:6px}.cb label{margin:0;display:flex;
  align-items:center;gap:6px;font-size:12px;color:#c9d4dc;text-transform:none}
.cb input{width:auto}
button{width:100%;margin-top:18px;padding:14px;border:0;border-radius:4px;
  background:#ffb400;color:#0a0c0e;font-weight:700;font-size:15px;
  letter-spacing:.08em;text-transform:uppercase}
.out a{display:block;color:#ffb400;margin:10px 0;font-size:15px}
.err{color:#ff5470;white-space:pre-wrap}</style></head><body>
<h1>LIVE<b>FORGE</b> LAN</h1>
<form method="POST" action="/convert" enctype="multipart/form-data">
<label>Video</label><input type="file" name="video" accept="video/*,.gif" required>
<div class="cb">
<label><input type="checkbox" name="bounce">bounce</label>
<label><input type="checkbox" name="reverse">reverse</label>
<label><input type="checkbox" name="audio">audio</label></div>
<label>Preset</label><select name="preset">
<option>none</option><option>cinematic</option><option>amg</option><option>noir</option>
<option>vivid</option><option>warm</option><option>cool</option><option>mono</option>
<option>fade</option></select>
<div class="r"><div><label>Start s</label><input name="start" inputmode="decimal"></div>
<div><label>End s</label><input name="end" inputmode="decimal"></div>
<div><label>Speed</label><input name="speed" inputmode="decimal" placeholder="1"></div></div>
<div class="r"><div><label>Keyframe</label><input name="keyframe" inputmode="decimal"></div>
<div style="grid-column:span 2"><label>Device</label><select name="res">
<option value="auto">auto</option><option value="16promax">16 Pro Max</option>
<option value="15promax">15 Pro Max</option><option value="15pro">15 Pro</option>
<option value="14">14 / 13</option><option value="se">SE</option></select></div></div>
<button>Forge</button></form>
<p style="color:#5d6b76;font-size:11px;margin-top:16px">After forging: long-press
each file → save, then upload BOTH together at icloud.com → Photos.</p>
</body></html>`;

// ----------------------------------------------------------------- server --

http.createServer((req, res) => {
  if (req.method === "GET" && req.url === "/") {
    res.writeHead(200, { "Content-Type": "text/html" });
    return res.end(PAGE);
  }
  if (req.method === "GET" && req.url.startsWith("/out/")) {
    const f = path.join(OUT, path.basename(decodeURIComponent(req.url)));
    if (!fs.existsSync(f)) { res.writeHead(404); return res.end("gone"); }
    res.writeHead(200, {
      "Content-Type": f.endsWith(".MOV") ? "video/quicktime" : "image/jpeg",
      "Content-Disposition": `attachment; filename="${path.basename(f)}"`,
    });
    return fs.createReadStream(f).pipe(res);
  }
  if (req.method === "POST" && req.url === "/convert") {
    const boundary = /boundary=(.+)$/.exec(req.headers["content-type"] || "")?.[1];
    if (!boundary) { res.writeHead(400); return res.end("bad request"); }
    const chunks = [];
    req.on("data", c => chunks.push(c));
    req.on("end", async () => {
      try {
        const { fields, file } = parseMultipart(Buffer.concat(chunks), boundary);
        if (!file || !file.data.length) throw new Error("no video received");
        const id = ++counter;
        const ext = path.extname(file.name) || ".mp4";
        const inPath = path.join(TMP, `in_${id}${ext}`);
        const outdir = path.join(TMP, `job_${id}`);
        fs.writeFileSync(inPath, file.data);
        console.log(`[${id}] ${file.name} (${(file.data.length / 1048576).toFixed(1)} MB)`);
        await runForge(inPath, fields, outdir);
        const links = [];
        for (const f of fs.readdirSync(outdir)) {
          const dest = `${id}_${f}`;
          fs.copyFileSync(path.join(outdir, f), path.join(OUT, dest));
          links.push(`<a href="/out/${dest}">↓ ${dest}</a>`);
        }
        fs.rmSync(inPath, { force: true });
        fs.rmSync(outdir, { recursive: true, force: true });
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end(PAGE.replace("<form", `<div class="out"><b style="color:#39d98a">
          ✓ forged</b>${links.join("")}</div><form`));
        console.log(`[${id}] done`);
      } catch (e) {
        res.writeHead(500, { "Content-Type": "text/html" });
        res.end(PAGE.replace("<form", `<p class="err">✗ ${e.message}</p><form`));
      }
    });
    return;
  }
  res.writeHead(404); res.end("not found");
}).listen(PORT, "0.0.0.0", () => {
  console.log(`\n  LiveForge LAN server`);
  console.log(`  iPhone (same Wi-Fi): http://${lanIP()}:${PORT}\n`);
});
