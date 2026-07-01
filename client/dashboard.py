"""Soft Yeti local dashboard — serves a PWA at http://localhost:8901.

Shows mining status, YETI balance, GPU info, and a toggle to start/stop mining.
Started automatically by setup_volunteer.ps1 after first-time setup.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
import uvicorn

sys.path.insert(0, str(Path(__file__).parent))
from yeti_config import DEFAULT_CONFIG_PATH, YetiConfig

DASHBOARD_PORT = 8901
CLIENT_DIR = Path(__file__).parent

_mining_proc: subprocess.Popen | None = None
_proc_lock = threading.Lock()
_log_file = None


def _detect_gpu() -> str:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            timeout=5, text=True, stderr=subprocess.DEVNULL,
        )
        name = out.strip().split("\n")[0].strip()
        if name:
            return name
    except Exception:
        pass
    try:
        import wmi  # type: ignore
        gpus = wmi.WMI().Win32_VideoController()
        if gpus:
            return gpus[0].Name
    except Exception:
        pass
    return "GPU"


def _get_balance(coordinator_url: str, wallet: str) -> float:
    try:
        r = requests.get(
            f"{coordinator_url.rstrip('/')}/chain/balance/{wallet}",
            timeout=5,
        )
        if r.ok:
            return float(r.json().get("balance", 0.0))
    except Exception:
        pass
    return 0.0


def _is_mining() -> bool:
    with _proc_lock:
        return _mining_proc is not None and _mining_proc.poll() is None


def _start_mining() -> None:
    global _mining_proc, _log_file
    with _proc_lock:
        if _mining_proc and _mining_proc.poll() is None:
            return
        python = str(CLIENT_DIR / ".venv" / "Scripts" / "python.exe")
        if not Path(python).exists():
            python = sys.executable
        log_path = CLIENT_DIR / "mining.log"
        _log_file = log_path.open("a", encoding="utf-8")
        _mining_proc = subprocess.Popen(
            [python, str(CLIENT_DIR / "yeti_client.py")],
            cwd=str(CLIENT_DIR),
            stdout=_log_file,
            stderr=_log_file,
        )


def _stop_mining() -> None:
    global _mining_proc
    with _proc_lock:
        if _mining_proc and _mining_proc.poll() is None:
            _mining_proc.terminate()
            try:
                _mining_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _mining_proc.kill()
        _mining_proc = None


# Detect GPU once at startup
_GPU = _detect_gpu()
app = FastAPI()


def _status_data() -> dict:
    cfg = YetiConfig.load()
    wallet = ""
    try:
        wpath = Path(cfg.wallet_path)
        if wpath.exists():
            raw = json.loads(wpath.read_text(encoding="utf-8"))
            wallet = raw.get("address", "")
    except Exception:
        pass
    balance = _get_balance(cfg.coordinator_url, wallet) if wallet else 0.0
    return {
        "mining": _is_mining(),
        "gpu": _GPU,
        "model": cfg.model_name,
        "vram_gb": cfg.vram_gb,
        "wallet": wallet,
        "balance": balance,
        "coordinator_url": cfg.coordinator_url,
        "volunteer_id": cfg.volunteer_id,
    }


@app.get("/api/status")
def api_status() -> JSONResponse:
    return JSONResponse(_status_data())


@app.post("/api/toggle")
def api_toggle() -> JSONResponse:
    if _is_mining():
        _stop_mining()
        data = _status_data()
        data["mining"] = False
    else:
        _start_mining()
        data = _status_data()
        data["mining"] = True
    return JSONResponse(data)


MANIFEST = json.dumps({
    "name": "Soft Yeti",
    "short_name": "Soft Yeti",
    "description": "Volunteer GPU mining node — earn YETI tokens",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0a0a0f",
    "theme_color": "#7c3aed",
    "icons": [
        {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"},
    ],
})

SW_JS = """\
const CACHE = 'sy-v1';
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['/'])));
  self.skipWaiting();
});
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('fetch', e => {
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
"""

ICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#7c3aed"/>
      <stop offset="100%" style="stop-color:#4f46e5"/>
    </linearGradient>
  </defs>
  <polygon points="50,5 93,27.5 93,72.5 50,95 7,72.5 7,27.5" fill="url(#g)"/>
  <text x="50" y="65" text-anchor="middle" font-size="42" fill="white" font-family="sans-serif">Y</text>
</svg>
"""

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Soft Yeti</title>
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<meta name="theme-color" content="#0a0a0f">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Soft Yeti">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0a0a0f;
  min-height:100vh;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  padding:1rem;
}
.card{
  background:#12121c;
  border:1px solid #2a2a3e;
  border-radius:24px;
  width:100%;
  max-width:380px;
  overflow:hidden;
  box-shadow:0 24px 64px rgba(0,0,0,0.6);
}
.card-header{
  padding:1.25rem 1.5rem;
  display:flex;
  align-items:center;
  gap:0.875rem;
  border-bottom:1px solid #1e1e2e;
}
.logo-mark{
  width:42px;height:42px;
  background:linear-gradient(135deg,#7c3aed,#4f46e5);
  border-radius:11px;
  display:flex;align-items:center;justify-content:center;
  flex-shrink:0;
}
.logo-mark svg{width:24px;height:24px}
.card-title{flex:1}
.card-title h2{font-size:1.05rem;font-weight:700;color:#e8e8f0;letter-spacing:-0.01em}
.card-title p{font-size:0.72rem;color:#5050a0;margin-top:2px}
.toggle{position:relative;display:inline-block;width:54px;height:30px;flex-shrink:0;cursor:pointer}
.toggle input{opacity:0;width:0;height:0}
.slider{
  position:absolute;top:0;left:0;right:0;bottom:0;
  background:#1e1e2e;border:1px solid #3a3a5e;
  border-radius:30px;transition:.25s;
}
.slider:before{
  position:absolute;content:"";
  height:22px;width:22px;left:3px;bottom:3px;
  background:#4a4a7a;border-radius:50%;transition:.25s;
}
input:checked+.slider{background:#7c3aed;border-color:#7c3aed}
input:checked+.slider:before{transform:translateX(24px);background:#fff}
.status-bar{
  padding:0.6rem 1.5rem;
  display:flex;align-items:center;gap:0.5rem;
  background:#0d0d17;
  border-bottom:1px solid #1a1a28;
}
.dot{
  width:7px;height:7px;border-radius:50%;
  background:#2a2a4a;transition:.3s;flex-shrink:0;
}
.dot.on{background:#22c55e;box-shadow:0 0 6px #22c55e99}
.dot.connecting{background:#f59e0b;box-shadow:0 0 6px #f59e0b99}
#statusText{font-size:0.75rem;color:#5050a0}
#statusText em{font-style:normal;color:#8080b0}
.balance-section{padding:1.375rem 1.5rem;border-bottom:1px solid #1a1a28}
.bal-label{font-size:0.68rem;color:#4a4a7a;text-transform:uppercase;letter-spacing:.1em;margin-bottom:.2rem}
.bal-row{display:flex;align-items:baseline;gap:.35rem}
.bal-value{font-size:2.6rem;font-weight:700;color:#a78bfa;letter-spacing:-.04em;line-height:1}
.bal-unit{font-size:.95rem;color:#6060a0;font-weight:400}
.stats{padding:0.5rem 1.5rem 0.75rem}
.stat{
  display:flex;justify-content:space-between;align-items:center;
  padding:.55rem 0;border-bottom:1px solid #181828;
}
.stat:last-child{border-bottom:none}
.sl{font-size:.73rem;color:#444470;font-weight:500;width:76px;flex-shrink:0;text-transform:uppercase;letter-spacing:.04em}
.sv{font-size:.82rem;color:#b0b0d0;text-align:right;word-break:break-all}
.sv.mono{font-family:'Menlo','Consolas',monospace;font-size:.72rem;color:#7070a0}
.install-bar{
  margin:.25rem 1.25rem 1.25rem;
  padding:.7rem 1rem;
  background:#0d0d17;border:1px solid #2a2a3e;border-radius:10px;
  display:none;align-items:center;justify-content:space-between;gap:.5rem;
}
.install-bar p{font-size:.75rem;color:#5050a0}
.install-bar button{
  font-size:.72rem;color:#a78bfa;background:none;
  border:1px solid #4a2a9a;border-radius:6px;
  padding:.25rem .7rem;cursor:pointer;white-space:nowrap;
}
.install-bar button:hover{background:#1a1a3a}
</style>
</head>
<body>
<div class="card">
  <div class="card-header">
    <div class="logo-mark">
      <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
        <polygon points="50,5 93,27.5 93,72.5 50,95 7,72.5 7,27.5" fill="white" opacity=".9"/>
        <text x="50" y="67" text-anchor="middle" font-size="48" fill="#7c3aed" font-family="sans-serif" font-weight="bold">Y</text>
      </svg>
    </div>
    <div class="card-title">
      <h2>Soft Yeti</h2>
      <p>Volunteer Mining Node</p>
    </div>
    <label class="toggle" title="Toggle mining on / off">
      <input type="checkbox" id="miningToggle">
      <span class="slider"></span>
    </label>
  </div>

  <div class="status-bar">
    <div class="dot" id="dot"></div>
    <div id="statusText">Connecting...</div>
  </div>

  <div class="balance-section">
    <div class="bal-label">YETI Earned</div>
    <div class="bal-row">
      <span class="bal-value" id="balance">—</span>
      <span class="bal-unit">YETI</span>
    </div>
  </div>

  <div class="stats">
    <div class="stat">
      <span class="sl">GPU</span>
      <span class="sv" id="gpu">—</span>
    </div>
    <div class="stat">
      <span class="sl">VRAM</span>
      <span class="sv" id="vram">—</span>
    </div>
    <div class="stat">
      <span class="sl">Model</span>
      <span class="sv" id="model">—</span>
    </div>
    <div class="stat">
      <span class="sl">Wallet</span>
      <span class="sv mono" id="wallet" title="">—</span>
    </div>
    <div class="stat">
      <span class="sl">Node ID</span>
      <span class="sv mono" id="volunteer">—</span>
    </div>
  </div>

  <div class="install-bar" id="installBar">
    <p>Add to Home Screen for quick access</p>
    <button id="installBtn">+ Install</button>
  </div>
</div>

<script>
let deferredPrompt = null;
let busy = false;

window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  deferredPrompt = e;
  document.getElementById('installBar').style.display = 'flex';
});

document.getElementById('installBtn').addEventListener('click', async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  if (outcome === 'accepted') document.getElementById('installBar').style.display = 'none';
  deferredPrompt = null;
});

const toggle = document.getElementById('miningToggle');
toggle.addEventListener('change', async () => {
  if (busy) { toggle.checked = !toggle.checked; return; }
  busy = true;
  setStatus('connecting');
  try {
    const r = await fetch('/api/toggle', { method: 'POST' });
    const d = await r.json();
    render(d);
  } catch {
    toggle.checked = !toggle.checked;
    setStatus('off');
  } finally {
    busy = false;
  }
});

function setStatus(state, model) {
  const dot = document.getElementById('dot');
  const txt = document.getElementById('statusText');
  dot.className = 'dot';
  if (state === 'on') {
    dot.classList.add('on');
    txt.innerHTML = 'Mining <em>· ' + (model || '') + '</em>';
  } else if (state === 'connecting') {
    dot.classList.add('connecting');
    txt.innerHTML = '<em>Starting...</em>';
  } else {
    txt.innerHTML = 'Idle — toggle to start mining';
  }
}

function fmt(addr) {
  if (!addr || addr.length < 16) return addr;
  return addr.slice(0, 10) + '…' + addr.slice(-6);
}

function render(d) {
  toggle.checked = !!d.mining;
  setStatus(d.mining ? 'on' : 'off', d.model);

  const bal = d.balance !== undefined ? parseFloat(d.balance).toFixed(4) : '—';
  document.getElementById('balance').textContent = bal;
  if (d.gpu)        document.getElementById('gpu').textContent = d.gpu;
  if (d.vram_gb)    document.getElementById('vram').textContent = d.vram_gb + ' GB';
  if (d.model)      document.getElementById('model').textContent = d.model;
  if (d.wallet) {
    const el = document.getElementById('wallet');
    el.textContent = fmt(d.wallet);
    el.title = d.wallet;
  }
  if (d.volunteer_id) {
    document.getElementById('volunteer').textContent = fmt(d.volunteer_id);
  }
}

async function poll() {
  try {
    const r = await fetch('/api/status');
    render(await r.json());
  } catch {}
}

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js');
}

poll();
setInterval(poll, 10000);
</script>
</body>
</html>
"""


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/manifest.json")
def manifest_route() -> Response:
    return Response(MANIFEST, media_type="application/manifest+json")


@app.get("/sw.js")
def sw_route() -> Response:
    return Response(SW_JS, media_type="application/javascript")


@app.get("/icon.svg")
def icon_route() -> Response:
    return Response(ICON_SVG, media_type="image/svg+xml")


if __name__ == "__main__":
    threading.Timer(2.0, lambda: webbrowser.open(f"http://localhost:{DASHBOARD_PORT}")).start()
    uvicorn.run(app, host="127.0.0.1", port=DASHBOARD_PORT, log_level="warning")
