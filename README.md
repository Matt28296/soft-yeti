# Soft Yeti

**Distributed volunteer compute network + custom YETI cryptocurrency**

Volunteers run a lightweight client, donate GPU capacity to an AI task pipeline (J-Claw), and earn YETI tokens. YETI is also the subscription currency for the AI product — a closed-loop economy where miners earn what subscribers spend.

> **Phase 0 validated 2026-06-30** — Block #0 minted on 3060 Ti testbed. 6-second end-to-end: task submitted → Ollama inference → PoI hash accepted → block written → output returned.
>
> **Security hardened + Phase 0→1 bridge complete 2026-06-30** — Ed25519 wallet signatures on every submission, `miner_pubkey` + `model_name` recorded in every block, model cross-check in verifier. Block #1 minted via J-Claw YETI pool route (20s, 1.836 YETI, signed submission verified). 44/44 tests pass.

---

## How it works

### Proof-of-Inference-as-Nonce (PoI)

Instead of burning electricity on meaningless hash searches (Bitcoin), Soft Yeti makes **LLM inference itself the nonce search**:

1. The coordinator sends a task (prompt + `task_salt` + `difficulty_target`)
2. The volunteer runs Ollama inference at `temperature > 0`
3. `SHA-256(output_text + task_id + task_salt)` is computed
4. If the hash starts with `difficulty_target` → valid nonce → block minted
5. If not → run inference again (new output = new nonce attempt)

Every failed attempt still produces real AI work. Every successful attempt produces a block AND real AI work. Nothing is wasted.

### Four verification layers

| Layer | Theory | What it catches |
|---|---|---|
| PoI nonce search | 8 | Cloud forwarding (economically irrational at difficulty) |
| GPU micro-benchmark | 7 | Timing correlation between benchmark and inference |
| Temperature-zero fingerprinting | 5 | Canary tasks with known exact outputs (5% of tasks) |
| Memory-hard Argon2 PoW | 2 | CPU/cloud scripts without VRAM (Phase 2) |

### Token economics

```
reward = completion_tokens × 0.001 × nonce_attempts
miner_share = reward × 0.90
treasury_share = reward × 0.10
```

No pre-mine. No ICO. YETI only comes from verified inference work.

---

## Repository structure

```
soft-yeti/
├── HANDOFF.md                  # Full project state, bugs found, Phase roadmap
├── start_coordinator.ps1       # Coordinator startup script (Windows)
│
├── chain/                      # Shared blockchain library (20/20 tests)
│   ├── wallet.py               # Ed25519 keygen, YETI1... address, sign/verify
│   ├── block.py                # Block dataclass, signing_payload(), block_hash
│   ├── difficulty.py           # check_output_hash(), adjust_difficulty()
│   ├── consensus.py            # Coordinator sign_block() + verify_block_signature()
│   ├── storage.py              # JSONL append + aiosqlite index (ChainStorage)
│   ├── chain.py                # append_block(), verify_chain(), get_balance()
│   ├── genesis.py              # create_genesis_block()
│   ├── node.py                 # FastAPI sub-app: /chain/height, /chain/block/{n}, /chain/balance/{addr}
│   └── test_chain.py           # 20 tests
│
├── coordinator/                # FastAPI coordinator server (24/24 tests)
│   ├── requirements.txt
│   ├── main.py                 # All routes + lifespan
│   ├── config.py               # pydantic-settings: keys, difficulty, timeouts
│   ├── schemas.py              # TaskAssignment, InferenceSubmission, GenerateRequest, etc.
│   ├── auth.py                 # bcrypt API key hashing + FastAPI dependency
│   ├── registry.py             # Volunteer registry, TTL heartbeat, healthy_volunteers()
│   ├── task_queue.py           # asyncio queue + asyncio.Event waiter pattern
│   ├── verifier.py             # PoI hash check + canary verification
│   ├── minter.py               # mint_block() → chain.append_block()
│   ├── sanitizer.py            # 6-step prompt sanitization
│   ├── canary.py               # 10 canary tasks with known-exact outputs
│   ├── database.py             # aiosqlite schema init
│   ├── subscription.py         # Placeholder — Phase 2: on-chain YETI → access
│   └── tests/
│       ├── test_api.py
│       ├── test_settings_sanitizer.py
│       └── test_verifier_minter.py
│
└── client/                     # Volunteer client (runs on any GPU machine)
    ├── yeti_client.py          # Entry point: --setup wizard + tray icon
    ├── yeti_node.py            # PoI nonce search + heartbeat + inference loops
    ├── yeti_wallet.py          # Wallet keygen, AES-256-GCM storage, load
    ├── yeti_config.py          # YetiConfig dataclass, config file at ~/.soft_yeti/
    ├── chain_client.py         # Read-only chain queries: balance, history, height
    ├── benchmark.py            # GPU micro-benchmark (numpy stub → Phase 2: Vulkan)
    └── requirements.txt
```

---

## Quick start

### Coordinator (GPU machine running Ollama + J-Claw)

```powershell
cd soft-yeti

# One-time setup: creates venv, keypair, .env, starts server
.\start_coordinator.ps1

# Or start directly (preferred — more reliable in background):
$dir = "C:\path\to\soft-yeti"
$py  = "$dir\.venv\Scripts\python.exe"
Start-Process $py `
    -ArgumentList "-m uvicorn coordinator.main:app --host 0.0.0.0 --port 8900 --log-level info" `
    -WorkingDirectory $dir -WindowStyle Hidden

# Verify
Invoke-RestMethod http://localhost:8900/api/health
# {"status": "ok", "healthy_volunteers": 0}
```

### Volunteer client (any machine with Ollama + GPU)

```bash
# Install deps
pip install requests ollama cryptography numpy

# First run: register with coordinator
python yeti_client.py --setup
# Coordinator URL: http://<coordinator-ip>:8900
# Model: qwen2.5-coder:7b-instruct (or any model you have)

# Start mining
python yeti_client.py
```

### Enable in J-Claw

```bash
# Add to Jarvis-Claw/harness/.env:
YETI_POOL_ENABLED=true
YETI_COORDINATOR_URL=http://localhost:8900
YETI_ALLOWED_TASK_TYPES=documentation,qa
```

---

## Coordinator API

| Route | Method | Auth | Description |
|---|---|---|---|
| `/api/register` | POST | none | Register volunteer → api_key |
| `/api/heartbeat` | POST | `X-Yeti-API-Key` | Liveness ping (TTL 60s) |
| `/api/health` | GET | none | `{"healthy_volunteers": N}` |
| `/api/task/next` | GET | `X-Yeti-API-Key` | Poll for next task |
| `/api/submit` | POST | `X-Yeti-API-Key` | Submit inference result; mints block if valid |
| `/api/generate` | POST | `X-JClaw-API-Key` | Blocking J-Claw endpoint (waits for volunteer output) |
| `/chain/balance/{addr}` | GET | none | YETI balance for wallet |
| `/chain/history/{addr}` | GET | none | Block history for wallet |
| `/chain/height` | GET | none | Current chain height |

### `/api/generate` — blocking J-Claw endpoint

J-Claw POSTs a task and blocks until a volunteer completes it:

```python
# Internal flow (asyncio.Event waiter pattern):
ev = await task_queue.register_waiter(task_id)          # J-Claw registers
await asyncio.wait_for(ev.wait(), timeout=900)          # blocks up to 15 min
output = await task_queue.take_result(task_id)          # returns volunteer output

# Volunteer side:
await task_queue.deliver_result(task_id, output_text)   # fires the event
```

---

## Wallet format

```
Address = "YETI1" + base58(SHA-256(pubkey)[:20])
Example:  YETI1xpE6DPs8BV5pP656K65psAhgvJS
```

Keys: Ed25519 (PKCS8 PEM via `cryptography` package — NOT PyNaCl, to avoid serialization incompatibilities).

Wallets are stored encrypted at `~/.soft_yeti/wallet.json` (AES-256-GCM + PBKDF2).

---

## Block structure

```json
{
  "index": 0,
  "chain_id": "yeti-testnet",
  "prev_hash": "0000...0000",
  "task_id": "phase0-test-010",
  "volunteer_id": "volunteer-uuid",
  "miner_wallet": "YETI1xpE6DPs8BV5pP656K65psAhgvJS",
  "output_text": "A blockchain is...",
  "output_hash": "5d9b558449eb1c68...",
  "nonce_attempts": 1,
  "prompt_tokens": 42,
  "completion_tokens": 28,
  "model_name": "qwen2.5-coder:7b-instruct",
  "miner_pubkey": "67743d1315e19619...",
  "miner_reward": 0.0252,
  "treasury_reward": 0.0028,
  "timestamp": 1751248800.0,
  "block_hash": "5d9b558449eb1c68...",
  "coordinator_signature": "base64..."
}
```

**Block signing invariant**: `signing_payload()` excludes BOTH `coordinator_signature` AND `block_hash`. `canonical_bytes()` (includes sig, excludes hash) is hashed to produce `block_hash`. Never change this.

---

## Configuration (coordinator)

| Variable | Default | Description |
|---|---|---|
| `DIFFICULTY_TARGET` | `"0"` | Leading hex chars required in output hash (empty = always pass) |
| `GENERATE_TIMEOUT_S` | `900.0` | Seconds J-Claw waits for volunteer (15 min) |
| `CANARY_RATE` | `0.05` | Fraction of tasks that are canary (fingerprinting) checks |
| `REWARD_RATE` | `0.001` | YETI per completion token |
| `TREASURY_FEE` | `0.1` | Treasury's share of rewards |
| `CHAIN_ID` | `yeti-testnet` | Chain identifier (prevents replay attacks across networks) |

All set via `coordinator/.env`. Use absolute paths for file settings — pydantic-settings resolves relative paths against CWD, not the package directory.

---

## Development notes

### Running tests

```bash
# Chain library (20 tests)
cd soft-yeti
python -m pytest chain/test_chain.py -v

# Coordinator (24 tests — includes 2 Ed25519 signature tests added in security hardening)
cd soft-yeti/coordinator
pip install -r requirements.txt
python -m pytest tests/ -v
```

### Key invariants — do not break these

1. **`TaskAssignment` return type on `/api/task/next`** — must be `response_model=TaskAssignment`, NOT `TaskRequest`. FastAPI uses the declared return type's schema to serialize the response. Using `TaskRequest` silently drops `task_salt`, `difficulty_target`, `system`, `temperature`, `is_canary` — the volunteer gets an incomplete assignment and `KeyError` follows.

2. **`asyncio.Lock` per wallet before Phase 2** — `subscription.py` has a concurrent Transfer race condition. Must add before Phase 2 concurrent Transfer handlers go live.

3. **`cryptography` package only** — not PyNaCl. Ed25519 serialization via PKCS8 PEM. The two libraries use incompatible serialization formats.

4. **`chain_id` in every block** — prevents testnet→mainnet replay attacks. Never omit.

5. **Coordinator must run from `soft-yeti/` as CWD** — uvicorn needs to find the `coordinator` package directory. Running from `soft-yeti/coordinator/` causes `ModuleNotFoundError`.

### Lessons learned during Phase 0 validation

| Bug | Root cause | Fix |
|---|---|---|
| `KeyError: 'task_salt'` | `response_model=TaskRequest` stripped TaskAssignment fields | `response_model=TaskAssignment` |
| Timeout stuck at 300s | `.env` not found (wrong CWD) → Python class default used | Absolute paths in `.env`; correct CWD |
| Keygen script hangs | `& $Python - @'...'@` stdin here-string hangs in background PS | Write script to temp `.py` file |
| `FileNotFoundError: coordinator.key` | `.env` relative path resolved against wrong CWD | Absolute paths in `.env` |
| Port still in use after kill | `Stop-Process` kills uvicorn parent, not child server | Kill by port ownership: `Get-NetTCPConnection -LocalPort 8900` |

---

## Phase 1 — Cloudflare Tunnel

The coordinator is reachable publicly via Cloudflare Tunnel. External volunteers use the tunnel URL instead of a Tailscale IP.

**Quick tunnel (ephemeral — URL changes on restart):**
```powershell
# From soft-yeti/ directory — cloudflared.exe must be present (not committed, download separately)
.\cloudflared.exe tunnel --url http://localhost:8900 --logfile cloudflared.log --loglevel info
```

The URL appears in `cloudflared.log` after ~5 seconds. Example:
```
https://gourmet-blackberry-two-relaxation.trycloudflare.com
```

**External tester quick-start** (replace URL with current tunnel):
```bash
git clone https://github.com/Matt28296/soft-yeti
cd soft-yeti/client
pip install requests ollama cryptography numpy
python yeti_client.py --setup
# Coordinator URL: https://<current-tunnel>.trycloudflare.com
# Model: <your Ollama model, e.g. qwen2.5-coder:7b-instruct>
# VRAM: <your GPU VRAM in GB>
python yeti_client.py
```

> For a stable persistent URL (Phase 1 production): create a named Cloudflare Tunnel with a Cloudflare account. The quick tunnel is sufficient for 5-tester internal phase.

---

## Phase roadmap

| Phase | Status | Description |
|---|---|---|
| **0 — Testbed** | ✅ Complete | Block #0 minted 2026-06-30 (3060 Ti, 6s). Security hardened: Ed25519 submission signatures, miner_pubkey + model_name in every block. 44/44 tests pass. |
| **0→1 Bridge** | ✅ Complete | J-Claw YETI pool enabled; Block #1 minted via pool route (20s, 1.836 YETI, signed). Phase 1 ready. |
| **1 — Internal** | ⏭ In progress | Cloudflare Tunnel, CLI distribution, 5 internal testers, yeti-testnet |
| **2 — Hardening** | ⏭ | Argon2 PoW, Vulkan benchmark, asyncio.Lock wallet, subscription live |
| **3 — Mainnet** | ⏭ HARD GATE | Legal review (FinCEN MSB, KYC/AML, Howey test) FIRST |
| **4 — zkML** | ⏭ | "Verified Miner" premium tier, zero-knowledge model proofs |

---

## Security constraints

- **Legal review is a hard gate before Phase 3** — FinCEN MSB registration, KYC/AML compliance, Howey test analysis. No exceptions, no shortcuts.
- Secrets in `.env` are never committed — use `.env.example` as the template
- Coordinator private key (`coordinator.key`) must never be committed
- `JCLAW_API_KEY` is empty in Phase 0 (open endpoint) — set before Phase 1 external testers

---

## Chain milestone blocks

```
Block #0 — Genesis
  index:       0
  hash:        5d9b558449eb1c68...
  miner:       YETI1xpE6DPs8BV5pP656K65psAhgvJS
  reward:      0.0252 YETI
  task:        phase0-test-010
  minted:      2026-06-30 ~03:44 UTC
  time:        6 seconds end-to-end

Block #1 — First signed submission (security hardening validated)
  index:       1
  hash:        (see yeti-chain.jsonl)
  miner:       YETI1xpE6DPs8BV5pP656K65psAhgvJS
  model_name:  qwen2.5-coder:7b-instruct
  miner_pubkey: 67743d1315e19619...
  reward:      1.836 YETI
  task:        phase1-bridge-001
  nonce_tries: 5
  minted:      2026-06-30
  time:        20 seconds (J-Claw → YETI pool → 3060 Ti → block)
```
