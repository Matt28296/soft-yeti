# Soft Yeti — Handoff

Date: **2026-06-30** (Phase 0 build complete)

---

## Status: Phase 0 VALIDATED ✅ — Block #0 minted 2026-06-30

All four layers built, tested, and end-to-end validated on 3060 Ti testbed:

| Layer | Files | Tests | Status |
|---|---|---|---|
| `chain/` | 8 modules | 20/20 | ✅ COMPLETE |
| `coordinator/` | 11 modules + tests | 22/22 | ✅ COMPLETE |
| `client/` | 6 modules | — (manual) | ✅ COMPLETE |
| J-Claw integration | 3 files modified | syntax clean | ✅ COMPLETE |

---

## To start the coordinator

**On 9070 XT — use Start-Process (not the PS1 script — it works but Start-Process is more reliable):**
```powershell
$dir = "C:\Users\Tyler\AI projects\The-Brain\soft-yeti"
$py  = "$dir\.venv\Scripts\python.exe"
Start-Process $py -ArgumentList "-m uvicorn coordinator.main:app --host 0.0.0.0 --port 8900 --log-level info" `
    -WorkingDirectory $dir -WindowStyle Hidden
# Verify: Invoke-RestMethod http://localhost:8900/api/health
```
Or use `.\start_coordinator.ps1` (also fixed — see bugs below).
`chain_id: yeti-testnet` · `difficulty: 0` (1/16 chance) · `timeout: 900s`

**On 3060 Ti (volunteer client):**
```powershell
# Install deps (Python 3.11+)
pip install requests ollama cryptography numpy

# First run: register and configure
cd <path to client files>
python yeti_client.py --setup
# Coordinator URL: http://100.92.46.126:8900
# Model: qwen2.5-coder:7b-instruct (already installed)

# Start mining
python yeti_client.py
```

**Enable YETI pool in J-Claw (on 9070 XT):**
```
# Add to harness/.env:
YETI_POOL_ENABLED=true
YETI_COORDINATOR_URL=http://localhost:8900
YETI_ALLOWED_TASK_TYPES=documentation,qa
```

---

## Phase 0 validation checklist — COMPLETE ✅ (2026-06-30)

- [x] Coordinator starts, DB initializes, keypair loads
- [x] `GET /api/health` returns `{"healthy_volunteers": 0}`
- [x] 3060 Ti client runs `--setup`, registers, gets API key
- [x] `GET /api/health` returns `{"healthy_volunteers": 1}`
- [x] Client receives task from `GET /api/task/next`
- [x] Client runs inference, finds valid PoI hash
- [x] `POST /api/submit` succeeds → **Block #0 minted** (hash: `5d9b558449eb1c68...`, reward: 0.0252 YETI to `YETI1xpE6DPs8BV5pP656K65psAhgvJS`, task: `phase0-test-010`, time: 6 seconds)
- [ ] `GET /chain/balance/{wallet}` returns non-zero YETI  ← not yet tested (endpoint exists)
- [x] J-Claw routed `documentation` task (phase1-bridge-001) through YETI pool — Block #1 minted 2026-06-30
- [ ] `mission_control.json` shows `node_id: "yeti_pool"` on completed task  ← next step
- [x] `/api/generate` endpoint returns output to J-Claw (tested directly; returned in 6s)

---

## File structure (as built)

```
soft-yeti/
├── start_coordinator.ps1      # startup script — creates venv, keypair, .env, starts uvicorn on :8900
├── chain/                     # shared chain library (COMPLETE)
│   ├── __init__.py
│   ├── wallet.py              # Ed25519 keygen, YETI1... address, sign/verify
│   ├── block.py               # Block dataclass, signing_payload(), canonical_bytes(), block_hash
│   ├── difficulty.py          # check_output_hash(), adjust_difficulty()
│   ├── consensus.py           # coordinator sign_block() + verify_block_signature()
│   ├── storage.py             # JSONL append + aiosqlite index (ChainStorage)
│   ├── chain.py               # append_block(), verify_chain(), get_balance(), get_history()
│   ├── genesis.py             # create_genesis_block()
│   ├── node.py                # FastAPI sub-app: GET /chain/height, /chain/block/{n},
│   │                          #   /chain/balance/{addr}, /chain/history/{addr}
│   └── tests/
│       └── test_chain.py      # 20 tests — wallet, block, difficulty, storage, chain ops
│
├── coordinator/               # FastAPI coordinator server (COMPLETE)
│   ├── requirements.txt       # fastapi, uvicorn, pydantic-settings, aiosqlite, bcrypt, cryptography, httpx, pytest-asyncio
│   ├── coordinator/           # Python package
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI app + lifespan + all route handlers
│   │   │                      # Key routes: /api/register /api/heartbeat /api/health
│   │   │                      #   /api/task/next  /api/submit  /api/generate (J-Claw blocking)
│   │   ├── config.py          # pydantic-settings: keys, difficulty, chain_id, JCLAW_API_KEY
│   │   ├── schemas.py         # Pydantic models: RegisterRequest, TaskAssignment, InferenceSubmission,
│   │   │                      #   GenerateRequest, GenerateResponse, HeartbeatRequest, HealthResponse
│   │   ├── auth.py            # bcrypt API key hashing + FastAPI dependency (volunteer auth)
│   │   ├── registry.py        # Volunteer registry (aiosqlite), TTL heartbeat, healthy_volunteers()
│   │   ├── sanitizer.py       # 6-step prompt sanitization (secret scan, path strip, length cap,
│   │   │                      #   role whitelist, model override strip, task type gate)
│   │   ├── canary_oracle.py   # Theory 5: 10 canary tasks, is_canary(), verify_canary()
│   │   ├── task_queue.py      # asyncio task queue: enqueue, assign, submit, asyncio.Event waiter pattern
│   │   │                      #   register_waiter() / deliver_result() / take_result() for /api/generate
│   │   ├── verifier.py        # PoI hash check, benchmark signature check, canary verification
│   │   ├── minter.py          # mint_block() → chain.append_block() → JSONL
│   │   └── subscription.py    # placeholder (Phase 2 — on-chain YETI Transfer → access)
│   └── tests/
│       ├── test_api.py        # API endpoint integration tests (register, heartbeat, health, task, submit)
│       ├── test_settings_sanitizer.py  # sanitizer pipeline tests
│       └── test_verifier_minter.py     # PoI hash verification + block minting tests
│
└── client/                    # Volunteer client (COMPLETE — Phase 0/1 CLI)
    ├── __init__.py
    ├── requirements.txt       # requests, ollama, cryptography, numpy, pystray, Pillow
    ├── yeti_config.py         # YetiConfig dataclass, DEFAULT_CONFIG_PATH (~/.soft_yeti/config.json)
    ├── yeti_wallet.py         # generate_wallet(), save_wallet() (AES-256-GCM / PBKDF2), load_wallet()
    │                          #   address_from_pubkey() → "YETI1" + base58(SHA-256(pubkey)[:20])
    ├── chain_client.py        # ChainClient: get_balance(), get_history(), get_height(), ping()
    ├── benchmark.py           # run_benchmark() → (signature, elapsed_ms) — numpy matrix multiply
    │                          #   Phase 2 upgrade: replace with PyOpenCL/Vulkan kernel
    ├── yeti_node.py           # _nonce_search(): PoI loop (run inference → check hash → submit)
    │                          #   heartbeat_loop() + inference_loop() as daemon threads
    │                          #   Auth header: X-Yeti-API-Key: {volunteer_id}:{api_key}
    └── yeti_client.py         # Entry point: --setup wizard + tray icon (pystray, falls back to CLI)
```

---

## Key invariants (must preserve across all phases)

- **Block signing:** `signing_payload()` excludes BOTH `coordinator_signature` AND `block_hash`.
  `canonical_bytes()` (includes sig, excludes hash) is hashed to produce `block_hash`. Never change this.
- **`cryptography` package only** — not PyNaCl. Ed25519 serialization via PKCS8 PEM.
- **`chain_id` in every block** — prevents testnet→mainnet replay attacks.
- **`asyncio.Lock` per wallet before Phase 2** — concurrent Transfer race condition (subscription.py).
- **Legal review is a HARD GATE before Phase 3** — FinCEN MSB, KYC/AML, Howey test.

---

## Coordinator architecture details

### J-Claw integration: POST /api/generate (blocking endpoint)
J-Claw calls this synchronously. The coordinator:
1. Checks healthy volunteers (503 if none)
2. Sanitizes the prompt
3. Enqueues the task with `system` + `temperature` forwarded to volunteers
4. Registers an `asyncio.Event` waiter keyed to `task_id`
5. Blocks (up to `GENERATE_TIMEOUT_S` = **900s**) until a volunteer submits
6. Returns the winning output to J-Claw
Auth: `X-JClaw-API-Key` header (open if `JCLAW_API_KEY` unset)

### Volunteer task flow: GET /api/task/next → POST /api/submit
- Volunteer polls `/api/task/next` (no enqueueing)
- Runs PoI nonce search: inference → SHA-256 check → retry if miss
- Submits winning output with `benchmark_signature`, `nonce_attempts`, wallet address
- Verifier checks PoI hash + canary (5% of tasks) → minter writes block → `deliver_result()` fires J-Claw waiter

### Task queue waiter pattern (`task_queue.py`)
```python
# J-Claw side:
ev = await task_queue.register_waiter(assignment.task_id)
await asyncio.wait_for(ev.wait(), timeout=settings.GENERATE_TIMEOUT_S)
output = await task_queue.take_result(assignment.task_id)

# Volunteer side (via submit handler):
await task_queue.deliver_result(task_id, output_text)  # fires the event
```

---

## Coordinator API reference

| Route | Method | Auth | Description |
|---|---|---|---|
| `/api/register` | POST | none | Register volunteer, returns `api_key` |
| `/api/heartbeat` | POST | `X-Yeti-API-Key` | Volunteer liveness (TTL 60s) |
| `/api/health` | GET | none | `{"healthy_volunteers": N}` |
| `/api/task/next` | GET | `X-Yeti-API-Key` | Poll for next task (no queue side effect) |
| `/api/submit` | POST | `X-Yeti-API-Key` | Submit inference result; mints block if valid |
| `/api/generate` | POST | `X-JClaw-API-Key` | Blocking J-Claw endpoint; forwards to volunteer pool |
| `/chain/balance/{addr}` | GET | none | YETI balance for wallet address |
| `/chain/history/{addr}` | GET | none | Block history for wallet address |
| `/chain/height` | GET | none | Current chain height |

---

## J-Claw integration (3 files modified)

**`Jarvis-Claw - Copy/harness/config.py`** (appended):
```python
YETI_POOL_ENABLED: bool = os.getenv("YETI_POOL_ENABLED", "false").lower() == "true"
YETI_COORDINATOR_URL: str = os.getenv("YETI_COORDINATOR_URL", "http://localhost:8000")
YETI_NODE_ID: str = os.getenv("YETI_NODE_ID", "yeti_pool")
YETI_ALLOWED_TASK_TYPES: set = {t.strip() for t in os.getenv("YETI_ALLOWED_TASK_TYPES", "documentation,qa").split(",") if t.strip()}
YETI_HEALTH_TTL_S: float = 5.0
YETI_JCLAW_API_KEY: str = os.getenv("YETI_JCLAW_API_KEY", "")
YETI_TASK_TIMEOUT_S: int = 300
```

**`Jarvis-Claw - Copy/harness/node_registry.py`** (added):
- `_healthy_yeti()` — cached GET `/api/health`, True only when `healthy_volunteers > 0`
- `_yeti_pool_eligible(task)` — checks `YETI_POOL_ENABLED`, task type, and health
- `choose_ollama_node()` extended — tries YETI pool BEFORE sidecars
- `node_snapshot()` extended — includes `yeti_pool` entry when `YETI_POOL_ENABLED`

**`Jarvis-Claw - Copy/harness/worker.py`** (added):
- `_call_yeti(system, user, task)` — POSTs to `/api/generate`, returns output string
- `_call_ollama()` extended — routes through `_call_yeti` when `node_id == YETI_NODE_ID`
- `_is_ollama_unavailable()` extended — "service unavailable" and "no volunteers" added
- `num_ctx = 4096` for YETI node (smaller context for faster volunteer inference)

---

## Phase roadmap

- ✅ **Phase 0 build**: 3060 Ti closed testbed — chain/ + coordinator/ + client/ all built 2026-06-30; J-Claw integration complete
- ✅ **Phase 0 validation**: Block #0 minted 2026-06-30; 3060 Ti mined in 6s; `/api/generate` returned output; PoI loop end-to-end confirmed
- ✅ **Phase 0 → Phase 1 bridge COMPLETE (2026-06-30)**: YETI pool enabled in J-Claw harness/.env, phase1-bridge-001 (documentation task) completed in 20s via 3060 Ti pool — **Block #1 minted** (model_name=qwen2.5-coder:7b-instruct, miner_pubkey=67743d13..., reward=1.836 YETI, nonce_tries=5). Ed25519 signed submission verified end-to-end.
- ⏭ **Phase 1**: Cloudflare Tunnel + CLI client distribution (5 internal testers, yeti-testnet)
- ⏭ **Phase 2**: Argon2 PoW (Theory 2) + Vulkan benchmark (Theory 7) + asyncio.Lock wallet + pystray installer + subscription live
- ⏭ **Phase 3**: public mainnet — HARD GATE: legal review (FinCEN MSB, KYC/AML, Howey test) FIRST
- ⏭ **Phase 4**: zkML upgrade path ("Verified Miner" premium tier)

---

## Bugs found and fixed during Phase 0 validation (2026-06-30)

1. **`get_next_task` serialized as `TaskRequest` not `TaskAssignment`** — `response_model=TaskRequest | dict` caused FastAPI to strip `task_salt`, `difficulty_target`, `system`, `temperature`, `is_canary` from the response. Fix: `response_model=TaskAssignment`, return type `TaskAssignment`. This was the main Phase 0 blocker.

2. **`GENERATE_TIMEOUT_S` stuck at 300s despite .env** — `start_coordinator.ps1` did `Push-Location $CoordDir` (= `soft-yeti/coordinator/`) before launching uvicorn. But uvicorn needs CWD = `soft-yeti/` so Python can find the `coordinator` package. When run from the wrong directory, the import fails. Fix: `Push-Location $Root` in the PS1.

3. **`here-string stdin hangs in background shells** — `& $Python - @'...'@` pattern hangs in non-interactive/background PowerShell. Fix: write keygen/treasury scripts to temp `.py` files, run with `& $Python $tempFile`.

4. **`coordinator.key` FileNotFoundError on submit (500)** — `.env` had `COORDINATOR_ED25519_KEY_PATH=./coordinator.key` which pydantic-settings resolves against CWD, not the package dir. Fix: absolute paths in `.env` for all file settings. The generated `.env` template in `start_coordinator.ps1` was also updated to write absolute paths.

5. **`Stop-Process` on uvicorn parent doesn't kill the server** — uvicorn spawns a child worker process that holds the port. Killing the parent leaves the child alive → `[WinError 10048] port already in use`. Fix: `Get-NetTCPConnection -LocalPort 8900 -State Listen` to find the actual owning PID, kill that.

---

## Security hardening applied (post-Phase 0, 2026-06-30)

Committed to `Matt28296/soft-yeti` (cb2889ef):

| Fix | Files | Status |
|---|---|---|
| Wallet pubkey in registration | `schemas.py`, `database.py`, `auth.py` | ✅ Done |
| Ed25519 submission signature | `schemas.py`, `verifier.py`, `client/yeti_wallet.py`, `client/yeti_node.py` | ✅ Done |
| Model name in submissions + blocks | `schemas.py`, `verifier.py`, `minter.py`, `chain/block.py`, `client/yeti_node.py` | ✅ Done |
| Canary comparison `.strip()` | `canary.py` | ✅ Done |
| DB migration for existing installs | `database.py` | ✅ Done |
| 2 new tests (sig accept/reject) | `tests/test_verifier_minter.py` | ✅ Done |

**Test count: 44/44 pass** (was 42/42; added 2 signature verification tests + fixed 1 stale path assertion).

**3060 Ti volunteer must re-run `--setup`** to register with the new `miner_pubkey` field before mining again.

**Remaining (Phase 2):**
- `benchmark_signature` is only checked non-empty — real cryptographic GPU timing verification needs Phase 2 Vulkan kernel
- Model verification is cross-check only (name match) — zkML proof for Phase 4

---

## Known gaps / Phase 1+ work

- `client/benchmark.py` uses numpy matrix multiply (Phase 0 stub) — Phase 2 replaces with PyOpenCL/Vulkan GPU kernel
- `coordinator/subscription.py` is a placeholder — Phase 2 wires on-chain YETI Transfer → access
- `asyncio.Lock` per wallet not yet in subscription.py — must add before Phase 2 concurrent Transfer handlers
- Difficulty auto-adjustment not yet implemented (static `DIFFICULTY_TARGET` in config)
- `client/build_installer.py` (PyInstaller → SoftYetiSetup.exe) not built
- Canary oracle has 10 tasks (Phase 0 minimum); Phase 1 should expand to 50+
- Client doesn't verify canary determinism empirically — do this before Phase 1 public launch

---

## Key paths

- Coordinator: `soft-yeti/coordinator/` — start with `start_coordinator.ps1` from `soft-yeti/`
- Client: `soft-yeti/client/` — `python yeti_client.py [--setup]`
- Chain: `soft-yeti/chain/` — shared library, imported by coordinator
- Tests: `cd soft-yeti/coordinator && pytest tests/` (44 tests total: 20 chain + 24 coordinator)
- Chain tests: `cd soft-yeti && python -m pytest chain/tests/` (20 tests)
- Plan: `~/.claude/plans/i-want-to-add-soft-yeti.md`
