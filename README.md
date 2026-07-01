# Soft Yeti

**Distributed volunteer compute network + custom YETI cryptocurrency**

Volunteers run a lightweight client, donate GPU capacity to an AI task pipeline (J-Claw), and earn YETI tokens. YETI is also the subscription currency for the AI product — a closed-loop economy where miners earn what subscribers spend.

> **Phase 0 validated 2026-06-30** — Block #0 minted on 3060 Ti testbed. 6-second end-to-end: task submitted → Ollama inference → PoI hash accepted → block written → output returned.
>
> **Security hardened + Phase 0→1 bridge complete 2026-06-30** — Ed25519 wallet signatures on every submission, `miner_pubkey` + `model_name` recorded in every block, model cross-check in verifier. Block #1 minted via J-Claw YETI pool route (20s, 1.836 YETI, signed submission verified). Canary oracle expanded to 50 tasks. Volunteer ID hijacking fix. Rate limiting on `/api/register` + `/api/submit`. Wallet passphrase encryption. Dual-agent security review applied: reward inflation fix, Ed25519 bypass fix, chain-append lock, timeout memory cleanup, failure-count enforcement. **53/53 tests pass (33 coordinator + 20 chain).**

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
├── coordinator/                # FastAPI coordinator server (40/40 tests)
│   ├── requirements.txt
│   ├── main.py                 # All routes + lifespan + rate limiting + chain lock
│   ├── config.py               # pydantic-settings: keys, difficulty, timeouts
│   ├── schemas.py              # TaskAssignment, InferenceSubmission, GenerateRequest, etc.
│   ├── auth.py                 # bcrypt API key hashing + ownership-checked registration
│   ├── registry.py             # Volunteer registry, TTL heartbeat, failure_count enforcement
│   ├── task_queue.py           # asyncio queue + asyncio.Event waiter pattern
│   ├── verifier.py             # PoI hash check + canary verification + Ed25519 guard
│   ├── minter.py               # mint_block() → chain.append_block()
│   ├── sanitizer.py            # 6-step prompt sanitization
│   ├── canary.py               # 50 canary tasks with known-exact outputs (5 categories)
│   ├── database.py             # aiosqlite schema init
│   ├── subscription.py         # Placeholder — Phase 2: on-chain YETI → access
│   └── tests/
│       ├── test_api.py
│       ├── test_auth.py        # 5 tests: ownership-checked registration
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

**Windows — one-command setup:**
```powershell
# Clone repo, then from soft-yeti/:
.\setup_volunteer.ps1
# Follow prompts: enter the coordinator URL, your Ollama model, and GPU VRAM
# Script creates venv, installs deps, pulls model if missing, runs --setup wizard

# Start mining:
cd client
.venv\Scripts\python yeti_client.py
```

**Manual (any OS):**
```bash
cd client
pip install -r requirements.txt
python yeti_client.py --setup
# Coordinator URL: <provided by operator>
python yeti_client.py
```

> **Wallet passphrase:** set one during setup — it encrypts `~/.soft_yeti/wallet.json`
> with AES-256-GCM. The client prompts for it on each startup. No passphrase = plaintext file.
>
> **Coordinator restart:** the coordinator's in-memory volunteer registry resets on
> restart. Re-run `python yeti_client.py --setup` (same volunteer ID, wallet, and
> pubkey — only the API key rotates). Your earned balance is safe on-chain.

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

Wallets are stored at `~/.soft_yeti/wallet.json`. The setup wizard prompts for a passphrase: if one is set, the file is AES-256-GCM encrypted (PBKDF2-HMAC-SHA256, 100k iterations); if left blank, the file is plaintext. On startup, the client detects the encrypted flag and prompts for the passphrase before loading. Keep `wallet.json` and your passphrase safe — there is no recovery path if either is lost.

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

# Coordinator (40 tests)
cd soft-yeti
pip install -r coordinator/requirements.txt
python -m pytest coordinator/tests/ -v
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

## Phase 1 — Cloudflare Tunnel + Dashboard

The coordinator is live at **`https://api.soft-yeti.com`** via a named Cloudflare Tunnel (stable — does not change on restart). Landing page at **`https://soft-yeti.com`**.

**External tester quick-start:**
```powershell
git clone https://github.com/Matt28296/soft-yeti
cd soft-yeti
.\setup_volunteer.ps1
# Coordinator URL when prompted: https://api.soft-yeti.com
```

Or manual (any OS):
```bash
cd soft-yeti/client
pip install -r requirements.txt
python yeti_client.py --setup
# Coordinator URL: https://api.soft-yeti.com
python yeti_client.py
```

**Local dashboard** (runs alongside the mining client):
```powershell
pip install fastapi uvicorn
python client/dashboard.py
# Opens http://localhost:8901 — toggle, balance, GPU card, PWA install
```

> **Model ladder** (auto-detected by `setup_volunteer.ps1`):
> `<4 GB` → `qwen2.5:1.5b-instruct` · `4-6 GB` → `phi4-mini:3.8b-instruct` · `6-10 GB` → `qwen2.5-coder:7b-instruct` · `10-20 GB` → `deepseek-coder-v2:16b` · `20+ GB` → `qwen2.5-coder:32b`
> Canary oracle validated 50/50 on both `qwen2.5:1.5b-instruct` and `qwen2.5-coder:7b-instruct`.

---

## Phase roadmap

| Phase | Status | What shipped |
|---|---|---|
| **0 — Testbed** | ✅ Complete | Block #0 minted 2026-06-30 (3060 Ti, 6s end-to-end). Full PoI loop: task → Ollama inference → hash check → block write → output returned to J-Claw. |
| **Security round 1** | ✅ Complete | Ed25519 submission signatures + miner_pubkey recorded in every block. Model cross-check in verifier. JCLAW_API_KEY guard on `/api/generate` + `/api/subscription/notify`. Nonce cap (500). |
| **0→1 Bridge** | ✅ Complete | Block #1 via J-Claw YETI pool route (20s, 1.836 YETI, signed). Canary oracle 10→50 tasks (5 categories). Volunteer ID hijacking fix. Rate limiting (5/min register, 30/min submit). Wallet passphrase encryption. `setup_volunteer.ps1` bootstrap. |
| **Security round 2** | ✅ Complete | Dual-agent (fork + Codex) security review. Reward inflation fix (token accumulation across nonce attempts). Ed25519 bypass fix (missing-pubkey volunteers now rejected). `_chain_lock` for concurrent block appends. Timeout memory leak. Failure-count enforcement. **53/53 tests pass (33 coordinator + 20 chain).** |
| **1 — Internal testers** | ⏳ In progress | Canary temp fix ✅, output sanitization ✅, nonce_attempts ge=1 ✅, VRAM auto-detect + model ladder ✅, exponential backoff ✅, `normalize_canary_output()` ✅, canary **50/50 on 7B** ✅ (`860b39c`+`5d88680`), PWA dashboard at localhost:8901 ✅ (`75a0116`+`bdf4557`), GPU name persisted in config ✅ (`64fb1c1`), **named tunnel live at soft-yeti.com** ✅, canary **50/50 on 1.5B** (laptop testers) ✅ (`ff02d5e`). **60/60 tests pass.** Remaining: 5-tester invite. |
| **1.5 — Zero-protocol quality wins** | ⏭ | Deliver all N nonce-attempt outputs to J-Claw (best picked by embedding similarity). Minimum quality gate in client (filter repetition/truncation before hashing). Base rate per inference run (per_attempt_reward regardless of block win). Zero blockchain changes. |
| **2 — Hardening + Protocol foundation** | ⏭ | Argon2 memory-hard PoW (256MB/attempt). Vulkan/PyOpenCL real GPU benchmark (backend-agnostic interface designed for mobile Metal in Phase 3). True model fingerprinting (per-model canary calibration). **Proof of Inference Depth (PoID)** — N self-refinement passes cryptographically chained; all passes delivered; reward ∝ depth; eliminates hash lottery. On-chain model registry (weights hash, reputation score, family, `model_type: standard\|bitnet`, `inference_backend: ollama\|metal\|vulkan` — mobile-ready from day one). Difficulty auto-adjustment. Subscription economy live. `SoftYetiSetup.exe` one-click installer. |
| **3 — Quality + Decentralization** | ⏭ HARD GATE | Legal review FIRST (FinCEN MSB, KYC/AML, Howey test, App Store mining policy). Then: BFT multi-validator consensus (5-of-9 threshold sigs, staked YETI, slashing). Reference model judge (tiny fixed-weight model, hash pinned in protocol, deterministic quality scores). Peer quality committee (commit-reveal, 5-miner panels, median wins). Bayesian miner reputation (Beta distribution — churn-tolerant for mobile volunteers who disconnect on screen lock). Model diversity enforcement (≥3 model families per block). Elastic emission + 30% fee burn (deflationary at scale). DHT task queue (decentralized routing). **Mobile volunteer tier** — iOS + Android foreground-only mining via BitNet models (1.58-bit ternary weights) + QVAC Fabric (Metal/Vulkan). iPhone 16 Pro Max A18 Pro confirmed capable of 7B–13B BitNet inference. Swift iOS app via TestFlight. Separate `metal` routing pool + per-model canary oracle calibrated on iPhone hardware. |
| **4 — zkML + Full permissionless** | ⏭ | zkML proofs (model weights + inference cryptographically proven; retires canary oracle and GPU benchmark; BitNet's ternary weight math makes zkML circuits cheaper — mobile may be first practical zkML tier). Recursive task DAGs (cryptographically linked reasoning chains; immutable AI audit trails for regulated industries). **Proof of Inference Diversity (PoDiv)** — M model families per task, reward ∝ ensemble contribution; mobile BitNet volunteers earn a diversity premium (architecturally distinct outputs, not competing head-to-head with desktop GPUs). Permissionless validators (stake + probation + on-chain concentration cap). |
| **5 — Enterprise + Ecosystem** | ⏭ | On-chain computation lineage API (cryptographic provenance for finance/healthcare/legal). Open model ecosystem flywheel (on-chain quality leaderboard; miners flock to high-reputation models; developers earn from inference revenue). Full closed-loop tokenomics (burn > issuance at high utilization → deflationary). |

---

## Security constraints

- **Legal review is a hard gate before Phase 3** — FinCEN MSB registration, KYC/AML compliance, Howey test analysis. No exceptions, no shortcuts.
- Secrets in `.env` are never committed — use `.env.example` as the template
- Coordinator private key (`coordinator.key`) must never be committed
- `JCLAW_API_KEY` must be set in `coordinator/.env` — protects `/api/generate` and `/api/subscription/notify`. Set before Phase 1 external testers (already done on the testbed machine).
- `/api/register` is rate-limited to 5/minute per IP; `/api/submit` to 30/minute per IP

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
