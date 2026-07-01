"""FastAPI entry point for the Soft Yeti coordinator backend."""

from __future__ import annotations

import asyncio
import io
import json
import secrets as _secrets
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from coordinator.auth import get_current_volunteer, register_volunteer
from coordinator.config import Settings, get_settings
from coordinator.database import init_db
from coordinator.minter import mint_block
from coordinator.registry import VolunteerRegistry
from coordinator.sanitizer import best_output, sanitize_output, sanitize_prompt
from coordinator.schemas import (
    GenerateRequest,
    GenerateResponse,
    InferenceSubmission,
    SubmitResponse,
    TaskAssignment,
    TaskRequest,
    TransferNotification,
    VolunteerRegistration,
)
from coordinator.subscription import is_subscribed, record_transfer
from coordinator.task_queue import TaskQueue
from coordinator.verifier import verify_submission

settings = get_settings()
registry = VolunteerRegistry()
task_queue = TaskQueue()

limiter = Limiter(key_func=get_remote_address)
_chain_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize coordinator storage before serving requests."""

    await init_db(settings.DB_PATH)
    yield


app = FastAPI(title="Soft Yeti Coordinator", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def _read_chain_jsonl() -> list[dict[str, Any]]:
    """Read all blocks from the JSONL chain store. Returns [] if file absent."""
    chain_path = Path(settings.CHAIN_STORE_PATH)
    if not chain_path.exists():
        return []
    blocks = []
    with chain_path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                blocks.append(json.loads(stripped))
    return blocks


def _last_chain_state() -> tuple[str, int]:
    """Return the previous block hash and next block index from the JSONL chain store."""
    blocks = _read_chain_jsonl()
    if not blocks:
        return "0" * 64, 0
    last_block = blocks[-1]
    prev_hash = str(last_block.get("block_hash", "0" * 64))
    next_index = int(last_block.get("index", -1)) + 1
    return prev_hash, next_index


def _append_block(block: dict[str, Any]) -> None:
    """Append a minted block to the local JSONL chain store."""

    chain_path = Path(settings.CHAIN_STORE_PATH)
    chain_path.parent.mkdir(parents=True, exist_ok=True)
    with chain_path.open("a", encoding="utf-8") as chain_file:
        chain_file.write(json.dumps(block, sort_keys=True, separators=(",", ":")) + "\n")


async def _require_jclaw_auth(request: Request) -> None:
    """FastAPI dependency for J-Claw → coordinator API calls.
    When JCLAW_API_KEY is unset the endpoint is open (Phase 0 testbed only).
    """
    if not settings.JCLAW_API_KEY:
        return
    provided = request.headers.get("X-JClaw-API-Key", "")
    if not _secrets.compare_digest(provided, settings.JCLAW_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid J-Claw API key")


_EXPLORER_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Soft Yeti — Chain Explorer</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0a0f;color:#e8e8f0;min-height:100vh}
a{color:#a78bfa;text-decoration:none}
a:hover{text-decoration:underline}
.hdr{background:#0d0d16;border-bottom:1px solid #1e1e30;padding:.9rem 1.5rem;display:flex;align-items:center;gap:1.25rem;flex-wrap:wrap}
.logo{font-size:1.2rem;font-weight:800;background:linear-gradient(135deg,#a78bfa,#60a5fa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;white-space:nowrap}
.chain-stats{display:flex;gap:1.25rem;font-size:.78rem;color:#5050a0;margin-left:auto;flex-wrap:wrap}
.chain-stats span{color:#c0c0e0;font-weight:600}
.search-bar{display:flex;gap:.5rem;padding:.6rem 1.5rem;background:#0d0d16;border-bottom:1px solid #181828}
.search-bar input{flex:1;max-width:520px;background:#12121c;border:1px solid #2a2a3e;border-radius:8px;padding:.5rem .9rem;color:#e8e8f0;font-size:.85rem;outline:none;font-family:monospace}
.search-bar input:focus{border-color:#7c3aed}
.search-bar input::placeholder{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#404060}
.search-bar button{background:#7c3aed;color:#fff;border:none;border-radius:8px;padding:.5rem 1.1rem;font-size:.85rem;cursor:pointer;font-weight:600}
.search-bar button:hover{background:#6d28d9}
.main{padding:1.25rem 1.5rem;max-width:1080px;margin:0 auto}
.section-label{font-size:.72rem;font-weight:700;color:#404070;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.75rem}
.card{background:#12121c;border:1px solid #1e1e30;border-radius:12px;overflow:hidden;margin-bottom:1.25rem}
table{width:100%;border-collapse:collapse;font-size:.83rem}
th{text-align:left;padding:.55rem 1rem;color:#404070;font-weight:700;font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #181828;white-space:nowrap}
td{padding:.65rem 1rem;border-bottom:1px solid #13131f;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px}
tr:last-child td{border-bottom:none}
tr:hover td{background:#14141f}
.mono{font-family:monospace;font-size:.78rem;color:#8080b0}
.reward{color:#86efac;font-weight:600}
.dimmed{color:#404070;font-size:.75rem}
.kv{display:grid;grid-template-columns:190px 1fr;gap:0}
.kv-k{padding:.6rem 1rem;color:#404070;font-size:.78rem;font-weight:700;border-bottom:1px solid #13131f;background:#0f0f1a;white-space:nowrap}
.kv-v{padding:.6rem 1rem;font-family:monospace;font-size:.78rem;border-bottom:1px solid #13131f;word-break:break-all}
.kv>div:last-child,.kv>div:nth-last-child(2){border-bottom:none}
.nav-row{display:flex;gap:.6rem;margin-bottom:1rem;align-items:center;flex-wrap:wrap}
.btn{background:#1a1a28;border:1px solid #252538;color:#9090b0;padding:.4rem .9rem;border-radius:8px;font-size:.8rem;cursor:pointer;display:inline-block;white-space:nowrap}
.btn:hover{background:#20203a;color:#e0e0f0;text-decoration:none}
.balance-box{padding:1.25rem 1rem;display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}
.stat-box{background:#0f0f1a;border:1px solid #1a1a2a;border-radius:8px;padding:.75rem 1rem}
.stat-label{font-size:.7rem;color:#404070;text-transform:uppercase;letter-spacing:.06em;margin-bottom:.3rem}
.stat-val{font-size:1.15rem;font-weight:700;color:#e0e0f0}
.stat-val.yeti{color:#86efac}
.empty-state{padding:2.5rem;text-align:center;color:#303050;font-size:.9rem}
.error-state{padding:2.5rem;text-align:center;color:#f87171;font-size:.9rem}
@media(max-width:640px){
  td,th{padding:.5rem .65rem}
  .main{padding:1rem}
  .kv{grid-template-columns:130px 1fr}
  .balance-box{grid-template-columns:1fr 1fr}
}
</style>
</head>
<body>
<div id="root"><div class="empty-state">Loading…</div></div>
<script>
// ── helpers ──────────────────────────────────────────────────────────────────
function esc(s){const d=document.createElement('div');d.textContent=String(s??'');return d.innerHTML}
function h(tag,cls,inner){return '<'+tag+(cls?' class="'+cls+'"':'')+'>'+inner+'</'+tag+'>'}
function fmt_hash(s){return s?s.slice(0,10)+'…'+s.slice(-4):'—'}
function fmt_wallet(s){return s?s.slice(0,10)+'…'+s.slice(-5):'—'}
function fmt_yeti(n){return n==null?'—':(+n).toFixed(4)+' YETI'}
function fmt_time(ts){
  if(!ts)return '—';
  const diff=(Date.now()/1000)-ts;
  if(diff<60)return Math.floor(diff)+'s ago';
  if(diff<3600)return Math.floor(diff/60)+'m ago';
  if(diff<86400)return Math.floor(diff/3600)+'h ago';
  return new Date(ts*1000).toLocaleDateString();
}
function fmt_ts_full(ts){
  if(!ts)return '—';
  return new Date(ts*1000).toISOString().replace('T',' ').replace(/\\.\\d+Z$/,' UTC');
}

// ── API ───────────────────────────────────────────────────────────────────────
async function GET(path){
  const r=await fetch(path);
  if(!r.ok)throw new Error(r.status+' '+r.statusText);
  return r.json();
}

// ── state ─────────────────────────────────────────────────────────────────────
let _height=0, _chainId='yeti-testnet';

async function refreshStats(){
  try{
    const h=await GET('/chain/height');
    _height=h.height||0;
    if(_height>0){const b=await GET('/chain/latest');_chainId=b.chain_id||_chainId;}
  }catch(e){}
}

// ── header ─────────────────────────────────────────────────────────────────────
function renderHeader(){
  return '<div class="hdr">'
    +'<a href="#" class="logo">⬡ Soft Yeti Explorer</a>'
    +'<div class="chain-stats">'
    +'<div>Height&nbsp;<span>'+_height+'</span></div>'
    +'<div>Chain&nbsp;<span>'+esc(_chainId)+'</span></div>'
    +'<a href="/" style="color:#5050a0;font-size:.75rem">← Home</a>'
    +'</div>'
    +'</div>'
    +'<div class="search-bar">'
    +'<input id="sq" placeholder="Block number or wallet address" />'
    +'<button onclick="doSearch()">Search</button>'
    +'</div>';
}

function doSearch(){
  const v=(document.getElementById('sq')||{}).value||'';
  const s=v.trim();
  if(!s)return;
  location.hash=s.match(/^\\d+$/)?'block/'+s:'wallet/'+s;
}
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&document.activeElement?.id==='sq')doSearch();});

// ── home view ─────────────────────────────────────────────────────────────────
async function viewHome(){
  await refreshStats();
  const blocks=[];
  const from=Math.max(0,_height-12);
  for(let i=_height-1;i>=from;i--){
    try{blocks.push(await GET('/chain/block/'+i));}catch(e){}
  }
  const rows=blocks.length?blocks.map(b=>
    '<tr>'
    +'<td><a href="#block/'+b.index+'">#'+b.index+'</a></td>'
    +'<td class="mono" title="'+esc(b.block_hash)+'">'+fmt_hash(b.block_hash)+'</td>'
    +'<td class="mono"><a href="#wallet/'+esc(b.miner_wallet)+'">'+fmt_wallet(b.miner_wallet)+'</a></td>'
    +'<td class="reward">'+fmt_yeti(b.miner_reward)+'</td>'
    +'<td class="dimmed">'+fmt_time(b.timestamp)+'</td>'
    +'<td class="dimmed">'+esc(b.nonce_attempts)+' nonce'+(b.nonce_attempts===1?'':'s')+'</td>'
    +'<td class="dimmed">'+(b.model_name||'—')+'</td>'
    +'</tr>'
  ).join(''):'<tr><td colspan="7" class="empty-state">No blocks yet</td></tr>';

  document.getElementById('root').innerHTML=renderHeader()
    +'<div class="main">'
    +'<div class="section-label">Recent Blocks</div>'
    +'<div class="card"><table>'
    +'<thead><tr><th>Block</th><th>Hash</th><th>Miner</th><th>Reward</th><th>Age</th><th>Nonce</th><th>Model</th></tr></thead>'
    +'<tbody>'+rows+'</tbody>'
    +'</table></div>'
    +'</div>';
}

// ── block detail ──────────────────────────────────────────────────────────────
async function viewBlock(index){
  await refreshStats();
  let b;
  try{b=await GET('/chain/block/'+index);}catch(e){
    document.getElementById('root').innerHTML=renderHeader()
      +'<div class="main"><div class="nav-row"><a class="btn" href="#">← All Blocks</a></div>'
      +'<div class="error-state">Block #'+esc(index)+' not found</div></div>';
    return;
  }
  const fields=[
    ['Index',b.index],
    ['Block Hash',esc(b.block_hash)],
    ['Prev Hash',esc(b.prev_hash)],
    ['Chain ID',esc(b.chain_id)],
    ['Timestamp',esc(fmt_ts_full(b.timestamp))],
    ['Miner Wallet','<a href="#wallet/'+esc(b.miner_wallet)+'">'+esc(b.miner_wallet)+'</a>'],
    ['Miner Reward','<span class="reward">'+fmt_yeti(b.miner_reward)+'</span>'],
    ['Base Reward',b.base_reward!=null?fmt_yeti(b.base_reward):'—'],
    ['Treasury Reward',fmt_yeti(b.treasury_reward)],
    ['Nonce Attempts',esc(b.nonce_attempts)],
    ['Completion Tokens',esc(b.completion_tokens)],
    ['Total Completion Tokens',b.total_completion_tokens!=null?esc(b.total_completion_tokens):'—'],
    ['Prompt Tokens',esc(b.prompt_tokens)],
    ['Model',esc(b.model_name||'—')],
    ['Volunteer',esc(b.volunteer_id)],
    ['Task ID',esc(b.task_id)],
    ['Difficulty Target',esc(b.difficulty_target)||'(none)'],
    ['Output Hash',esc(b.output_hash)],
    ['Task Content Hash',esc(b.task_content_hash)],
    ['Coordinator Sig','<span class="mono">'+esc(b.coordinator_signature)+'</span>'],
    ['Version',esc(b.version)],
  ];
  const kv=fields.map(([k,v])=>'<div class="kv-k">'+k+'</div><div class="kv-v">'+v+'</div>').join('');
  const prev=index>0?'<a class="btn" href="#block/'+(index-1)+'">← Block '+(index-1)+'</a>':'';
  const next=index<_height-1?'<a class="btn" href="#block/'+(index+1)+'">Block '+(index+1)+' →</a>':'';
  document.getElementById('root').innerHTML=renderHeader()
    +'<div class="main">'
    +'<div class="nav-row"><a class="btn" href="#">← All Blocks</a>'+prev+next+'</div>'
    +'<div class="section-label">Block #'+esc(index)+'</div>'
    +'<div class="card"><div class="kv">'+kv+'</div></div>'
    +'</div>';
}

// ── wallet view ───────────────────────────────────────────────────────────────
async function viewWallet(addr){
  if(!addr){viewHome();return;}
  await refreshStats();
  let bal,hist;
  try{
    [bal,hist]=await Promise.all([GET('/chain/balance/'+addr),GET('/chain/history/'+addr)]);
  }catch(e){
    document.getElementById('root').innerHTML=renderHeader()
      +'<div class="main"><div class="nav-row"><a class="btn" href="#">← All Blocks</a></div>'
      +'<div class="error-state">Failed to load wallet</div></div>';
    return;
  }
  const blocks=[...(hist.blocks||[])].reverse();
  const rows=blocks.length?blocks.map(b=>
    '<tr>'
    +'<td><a href="#block/'+b.index+'">#'+b.index+'</a></td>'
    +'<td class="mono" title="'+esc(b.block_hash)+'">'+fmt_hash(b.block_hash)+'</td>'
    +'<td class="reward">'+fmt_yeti(b.miner_reward)+'</td>'
    +'<td class="dimmed">'+fmt_time(b.timestamp)+'</td>'
    +'<td class="dimmed">'+esc(b.nonce_attempts)+' nonce'+(b.nonce_attempts===1?'':'s')+'</td>'
    +'</tr>'
  ).join(''):'<tr><td colspan="5" class="empty-state">No blocks mined</td></tr>';

  const total=fmt_yeti(bal.balance_yeti);
  document.getElementById('root').innerHTML=renderHeader()
    +'<div class="main">'
    +'<div class="nav-row"><a class="btn" href="#">← All Blocks</a></div>'
    +'<div class="section-label">Wallet</div>'
    +'<div class="card">'
    +'<div class="balance-box">'
    +'<div class="stat-box"><div class="stat-label">Address</div><div class="stat-val mono" style="font-size:.7rem;color:#8080b0;word-break:break-all">'+esc(addr)+'</div></div>'
    +'<div class="stat-box"><div class="stat-label">Balance</div><div class="stat-val yeti">'+esc(total)+'</div></div>'
    +'<div class="stat-box"><div class="stat-label">Blocks Mined</div><div class="stat-val">'+esc(blocks.length)+'</div></div>'
    +'</div></div>'
    +'<div class="section-label">Mining History</div>'
    +'<div class="card"><table>'
    +'<thead><tr><th>Block</th><th>Hash</th><th>Reward</th><th>Age</th><th>Nonce</th></tr></thead>'
    +'<tbody>'+rows+'</tbody>'
    +'</table></div>'
    +'</div>';
}

// ── router ────────────────────────────────────────────────────────────────────
async function route(){
  const hash=location.hash.replace(/^#\\/?/,'');
  const slash=hash.indexOf('/');
  const view=slash<0?hash:hash.slice(0,slash);
  const arg=slash<0?'':hash.slice(slash+1);
  if(view==='block')await viewBlock(parseInt(arg,10));
  else if(view==='wallet')await viewWallet(arg);
  else await viewHome();
}

window.addEventListener('hashchange',route);
route();
</script>
</body>
</html>
"""

_LANDING_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Soft Yeti — Mine AI, Earn YETI</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0a0a0f;color:#e8e8f0;
  min-height:100vh;display:flex;flex-direction:column;
  align-items:center;justify-content:center;padding:2rem;
  text-align:center;
}
.hex{font-size:3.5rem;margin-bottom:.5rem;line-height:1}
h1{
  font-size:2.75rem;font-weight:800;letter-spacing:-.04em;
  background:linear-gradient(135deg,#a78bfa,#60a5fa);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  margin-bottom:.6rem;
}
.tag{font-size:1.2rem;color:#6060a0;margin-bottom:3rem;line-height:1.5}
.steps{display:flex;gap:1.25rem;margin-bottom:3rem;flex-wrap:wrap;justify-content:center}
.step{
  background:#12121c;border:1px solid #2a2a3e;border-radius:14px;
  padding:1.5rem 1.25rem;width:180px;text-align:center;
}
.sn{font-size:1.75rem;font-weight:700;color:#7c3aed;margin-bottom:.4rem}
.st{font-weight:600;font-size:.95rem;color:#d0d0e8;margin-bottom:.25rem}
.sd{font-size:.8rem;color:#5050a0;line-height:1.4}
.dl{
  display:inline-flex;align-items:center;gap:.6rem;
  background:linear-gradient(135deg,#7c3aed,#4f46e5);
  color:#fff;text-decoration:none;
  padding:.9rem 2.25rem;border-radius:12px;
  font-size:1.05rem;font-weight:600;
  margin-bottom:1rem;transition:opacity .2s;
}
.dl:hover{opacity:.88}
.manual{font-size:.85rem;color:#4a4a7a;margin-top:.5rem}
.manual strong{color:#8080c0}
code{
  display:block;background:#12121c;border:1px solid #2a2a3e;
  border-radius:8px;padding:.8rem 1rem;margin:.6rem auto 0;
  font-size:.78rem;color:#8080b0;text-align:left;
  max-width:480px;white-space:pre;overflow-x:auto;
}
.gh{margin-top:2.5rem;font-size:.82rem;color:#404060}
.gh a{color:#7c3aed;text-decoration:none}
</style>
</head>
<body>
<div class="hex">⬡</div>
<h1>Soft Yeti</h1>
<p class="tag">Donate spare GPU compute to AI inference.<br>Earn YETI tokens automatically.</p>
<div class="steps">
  <div class="step"><div class="sn">1</div><div class="st">Download</div><div class="sd">One script sets everything up</div></div>
  <div class="step"><div class="sn">2</div><div class="st">Mine</div><div class="sd">Your GPU runs real AI tasks</div></div>
  <div class="step"><div class="sn">3</div><div class="st">Earn</div><div class="sd">YETI tokens accumulate in your wallet</div></div>
</div>
<a href="/download/setup.bat" class="dl">⬇&nbsp; Download Setup Script</a>
<div class="manual">
  <p>Double-click the downloaded file — it installs itself to a <code style="display:inline;padding:.1rem .4rem">soft-yeti</code> folder in your home directory and walks you through the rest.</p>
  <p>Or clone and run manually (Windows):</p>
  <code>git clone https://github.com/Matt28296/soft-yeti
cd soft-yeti
powershell -ExecutionPolicy Bypass -File setup_volunteer.ps1</code>
</div>
<div class="gh">Open source on <a href="https://github.com/Matt28296/soft-yeti" target="_blank">GitHub</a> &nbsp;·&nbsp; <a href="/explorer">Chain Explorer</a></div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def landing() -> HTMLResponse:
    return HTMLResponse(_LANDING_HTML)


@app.get("/explorer", response_class=HTMLResponse)
async def explorer() -> HTMLResponse:
    return HTMLResponse(_EXPLORER_HTML)


_NO_CACHE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


@app.get("/download/setup.ps1", response_class=PlainTextResponse)
async def download_setup() -> PlainTextResponse:
    setup_path = Path(__file__).parent.parent / "setup_volunteer.ps1"
    content = setup_path.read_text(encoding="utf-8") if setup_path.exists() else "# Not found"
    return PlainTextResponse(
        content,
        headers={"Content-Disposition": 'attachment; filename="setup_volunteer.ps1"', **_NO_CACHE_HEADERS},
    )


@app.get("/download/setup.bat", response_class=PlainTextResponse)
async def download_setup_bat() -> PlainTextResponse:
    """Double-click-friendly bootstrap — .bat executes on double-click, unlike .ps1."""
    setup_path = Path(__file__).parent.parent / "setup.bat"
    content = setup_path.read_text(encoding="utf-8") if setup_path.exists() else "@echo off\r\necho Not found\r\npause\r\n"
    return PlainTextResponse(
        content,
        headers={"Content-Disposition": 'attachment; filename="setup.bat"', **_NO_CACHE_HEADERS},
    )


_ZIP_EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache"}


@app.get("/download/volunteer.zip")
async def download_volunteer_zip() -> Response:
    """Self-hosted bundle of setup_volunteer.ps1 + client/ (the repo is private, so
    testers can't `git clone` or pull GitHub's archive endpoint without credentials).
    setup.bat downloads and extracts this instead of the lone .ps1 file.
    """
    root = Path(__file__).parent.parent
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        setup_ps1 = root / "setup_volunteer.ps1"
        if setup_ps1.exists():
            zf.write(setup_ps1, arcname="setup_volunteer.ps1")
        client_dir = root / "client"
        for path in client_dir.rglob("*"):
            if path.is_dir():
                continue
            if any(part in _ZIP_EXCLUDE_DIRS for part in path.relative_to(root).parts):
                continue
            zf.write(path, arcname=str(path.relative_to(root)))
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="soft-yeti-volunteer.zip"', **_NO_CACHE_HEADERS},
    )


@app.get("/api/health")
async def health() -> dict[str, int | str]:
    """Return coordinator health and live volunteer count."""

    return {
        "status": "ok",
        "healthy_volunteers": len(registry.healthy_volunteers()),
    }


@app.get("/api/client-version")
async def client_version() -> Response:
    """Current bundled client version — volunteers poll this to detect + self-update.
    Reads client/VERSION fresh from disk each request (bump that file to ship an update).
    """
    version_path = Path(__file__).parent.parent / "client" / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else "0"
    return Response(
        content=json.dumps({"version": version}),
        media_type="application/json",
        headers=_NO_CACHE_HEADERS,
    )


@app.post("/api/generate", response_model=GenerateResponse)
async def generate(
    req: GenerateRequest,
    _: None = Depends(_require_jclaw_auth),
) -> GenerateResponse:
    """Blocking endpoint for J-Claw to submit a task and receive the volunteer's output.

    Enqueues the task, waits for a volunteer to complete it, then returns the output text.
    Returns 503 immediately when no healthy volunteers are registered, or on timeout.
    """
    if not registry.healthy_volunteers():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no volunteers available",
        )

    sanitized = await sanitize_prompt(req.prompt, req.task_type, settings)
    task = TaskRequest(
        task_id=req.task_id,
        task_type=req.task_type,
        prompt=sanitized,
        max_tokens=req.max_tokens,
    )
    # Carry system + temperature through to the volunteer via the assignment
    task_with_extras = type("_TaskWithExtras", (), {
        "task_id": req.task_id,
        "task_type": req.task_type,
        "prompt": sanitized,
        "max_tokens": req.max_tokens,
        "system": req.system,
        "temperature": req.temperature,
    })()

    assignment = await task_queue.enqueue_prompt(task_with_extras, settings=settings)
    ev = await task_queue.register_waiter(assignment.task_id)

    try:
        await asyncio.wait_for(ev.wait(), timeout=settings.GENERATE_TIMEOUT_S)
    except asyncio.TimeoutError:
        await task_queue.complete_assignment(assignment.task_id)
        await task_queue.take_result(assignment.task_id)  # clean up registered event
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service unavailable: no volunteer completed the task in time",
        )

    output = await task_queue.take_result(assignment.task_id)
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service unavailable: result missing after delivery signal",
        )
    return GenerateResponse(task_id=req.task_id, output=output)


@app.get("/api/task/next", response_model=TaskAssignment)
async def get_next_task(
    volunteer_id: str = Depends(get_current_volunteer),
) -> TaskAssignment:
    """Volunteer polls for the next queued task without submitting a new one."""

    await registry.heartbeat(volunteer_id)
    assignment = await task_queue.assign_next()
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No task available")
    return assignment


@app.post("/api/register")
@limiter.limit("5/minute")
async def register(request: Request, registration: VolunteerRegistration) -> dict[str, str]:
    """Register a volunteer and return its one-time API key."""

    try:
        api_key = await register_volunteer(settings.DB_PATH, registration)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await registry.register_seen(
        volunteer_id=registration.volunteer_id,
        model_name=registration.model_name,
        vram_gb=registration.vram_gb,
        miner_wallet=registration.miner_wallet,
    )
    return {"volunteer_id": registration.volunteer_id, "api_key": api_key}


@app.post("/api/task")
async def assign_task(
    task: TaskRequest,
    volunteer_id: str = Depends(get_current_volunteer),
):
    """Queue and assign a task to an authenticated volunteer."""

    await registry.heartbeat(volunteer_id)
    await task_queue.enqueue_prompt(task, settings=settings)
    assignment = await task_queue.assign_next()
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No task available",
        )
    return assignment


@app.post("/api/submit", response_model=SubmitResponse)
@limiter.limit("30/minute")
async def submit_inference(
    request: Request,
    submission: InferenceSubmission,
    volunteer_id: str = Depends(get_current_volunteer),
) -> SubmitResponse:
    """Verify a volunteer submission and mint a YETI block when accepted."""

    if submission.volunteer_id != volunteer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Submission volunteer does not match API key",
        )

    assignment = task_queue.pending.get(submission.task_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown task assignment",
        )

    accepted, reason = await verify_submission(submission, assignment, settings)
    if not accepted:
        await registry.mark_failure(volunteer_id)
        return SubmitResponse(accepted=False, reason=reason)

    async with _chain_lock:
        prev_hash, block_index = _last_chain_state()
        block = await mint_block(
            submission=submission,
            task_assignment=assignment,
            settings=settings,
            prev_hash=prev_hash,
            block_index=block_index,
        )
        _append_block(block)
    await task_queue.complete_assignment(submission.task_id)
    chosen = best_output(submission.all_outputs, submission.output_text)
    await task_queue.deliver_result(submission.task_id, sanitize_output(chosen))

    record = await registry.register_seen(
        volunteer_id=volunteer_id,
        miner_wallet=submission.miner_wallet,
    )
    record.tasks_completed += 1

    return SubmitResponse(
        accepted=True,
        reason="ok",
        block_index=block_index,
        miner_reward=float(block["miner_reward"]),
    )


@app.post("/api/heartbeat")
async def heartbeat(volunteer_id: str = Depends(get_current_volunteer)) -> dict[str, bool]:
    """Refresh the authenticated volunteer liveness timestamp."""

    ok = await registry.heartbeat(volunteer_id)
    if not ok:
        await registry.register_seen(volunteer_id=volunteer_id)
    return {"ok": True}


@app.post("/api/subscription/notify")
async def subscription_notify(
    transfer: TransferNotification,
    _: None = Depends(_require_jclaw_auth),
) -> dict[str, bool]:
    """Record a YETI transfer and extend the recipient subscription."""

    await record_transfer(settings.DB_PATH, transfer)
    return {"ok": True}


@app.get("/api/subscription/check/{wallet}")
async def subscription_check(wallet: str) -> dict[str, bool]:
    """Return whether a wallet currently has an active subscription."""

    return {"subscribed": await is_subscribed(settings.DB_PATH, wallet)}


# ---------------------------------------------------------------------------
# Chain read routes — read directly from the JSONL store (no ChainStorage/
# ChainManager needed; the SQLite-indexed chain node is a Phase 2 upgrade).
# ---------------------------------------------------------------------------

@app.get("/chain/height")
async def chain_height() -> dict[str, int]:
    return {"height": len(_read_chain_jsonl())}


@app.get("/chain/latest")
async def chain_latest() -> dict[str, Any]:
    blocks = _read_chain_jsonl()
    if not blocks:
        raise HTTPException(status_code=404, detail="Chain is empty")
    return blocks[-1]


@app.get("/chain/block/{index}")
async def chain_block(index: int) -> dict[str, Any]:
    blocks = _read_chain_jsonl()
    if index < 0 or index >= len(blocks):
        raise HTTPException(status_code=404, detail=f"Block {index} not found")
    return blocks[index]


@app.get("/chain/balance/{addr}")
async def chain_balance(addr: str) -> dict[str, Any]:
    blocks = _read_chain_jsonl()
    balance = sum(b.get("miner_reward", 0.0) for b in blocks if b.get("miner_wallet") == addr)
    return {"wallet": addr, "balance_yeti": round(balance, 8)}


@app.get("/chain/history/{addr}")
async def chain_history(addr: str) -> dict[str, Any]:
    blocks = _read_chain_jsonl()
    mined = [b for b in blocks if b.get("miner_wallet") == addr]
    return {"wallet": addr, "blocks": mined}


if __name__ == "__main__":
    uvicorn.run("coordinator.main:app", host="0.0.0.0", port=8000, reload=True)
