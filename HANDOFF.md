# Soft Yeti — Handoff

Date: **2026-06-30** (Phase 0 build complete)

---

## Status: Phase 1.5 COMPLETE — awaiting 5-tester invite (Phase 1 final gate)

Phase 0 complete + security hardened + Phase 0→1 bridge complete (2026-06-30).

| Layer | Files | Tests | Status |
|---|---|---|---|
| `chain/` | 8 modules | 20/20 | ✅ COMPLETE |
| `coordinator/` | 13 modules + tests | **40/40** | ✅ COMPLETE |
| `client/` | 6 modules | — (manual) | ✅ COMPLETE |
| J-Claw integration | 3 files modified | syntax clean | ✅ COMPLETE |

**60/60 tests pass total (40 coordinator + 20 chain).**

**Next gate:** Cloudflare tunnel URL (quick ephemeral tunnel works for 5-tester phase; named tunnel requires a domain on Cloudflare account) → send URL to 5 internal testers.

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

**On 3060 Ti (volunteer client) — new bootstrap script:**
```powershell
cd soft-yeti
.\setup_volunteer.ps1
# Prompts: coordinator URL, model, VRAM, wallet passphrase
# Creates venv, installs deps, pulls model if missing, runs --setup wizard

# Start mining:
cd client
.venv\Scripts\python yeti_client.py
# If wallet is encrypted, prompts for passphrase on startup
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
- [x] `GET /chain/balance/{wallet}` returns non-zero YETI  — confirmed 1.8612 YETI balance on-chain
- [x] J-Claw routes a `documentation` task through YETI pool  — Block #1 minted via J-Claw pool route (20s, 1.836 YETI)
- [x] `mission_control.json` shows `node_id: "yeti_pool"` on completed task  — confirmed via Phase 0→1 bridge run
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
├── coordinator/               # FastAPI coordinator server (COMPLETE — 33/33 tests)
│   ├── requirements.txt       # fastapi, uvicorn, pydantic-settings, aiosqlite, bcrypt, cryptography, httpx, slowapi, pytest-asyncio
│   ├── coordinator/           # Python package
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI app + lifespan + all route handlers + rate limiting + _chain_lock
│   │   │                      # Key routes: /api/register /api/heartbeat /api/health
│   │   │                      #   /api/task/next  /api/submit  /api/generate (J-Claw blocking)
│   │   ├── config.py          # pydantic-settings: keys, difficulty, chain_id, JCLAW_API_KEY
│   │   ├── schemas.py         # Pydantic models: RegisterRequest, TaskAssignment, InferenceSubmission,
│   │   │                      #   GenerateRequest, GenerateResponse, HeartbeatRequest, HealthResponse
│   │   ├── auth.py            # bcrypt API key hashing + ownership-checked registration (no ID hijacking)
│   │   ├── registry.py        # Volunteer registry (aiosqlite), TTL heartbeat, failure_count enforcement
│   │   ├── sanitizer.py       # 6-step prompt sanitization (secret scan, path strip, length cap,
│   │   │                      #   role whitelist, model override strip, task type gate)
│   │   ├── canary.py          # Theory 5: 50 canary tasks (5 categories), is_canary(), verify_canary()
│   │   ├── task_queue.py      # asyncio task queue: enqueue, assign, submit, asyncio.Event waiter pattern
│   │   │                      #   register_waiter() / deliver_result() / take_result() for /api/generate
│   │   ├── verifier.py        # PoI hash check + Ed25519 signature guard + canary verification
│   │   ├── minter.py          # mint_block() → chain.append_block() → JSONL
│   │   └── subscription.py    # placeholder (Phase 2 — on-chain YETI Transfer → access)
│   └── tests/
│       ├── test_api.py        # API endpoint integration tests (register, heartbeat, health, task, submit)
│       ├── test_auth.py       # 5 tests: ownership-checked registration (ID hijacking protection)
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

## Node architecture & governance

### Current node roles (Phase 0–1)

| Node | Machine | Role | Status |
|---|---|---|---|
| **Core node** | 9070 XT | Primary coordinator — mints blocks, holds chain JSONL, signs all submissions | Always-on |
| **Secondary node** | 3060 Ti | Hot-standby coordinator + volunteer miner — continues chain if core goes down | Standby; active as miner |

The **core node** is the single authoritative coordinator for now. The secondary node:
- Runs the volunteer client (`yeti_client.py`) full-time as a miner
- Can take over as coordinator if the core goes down: `.\start_coordinator_secondary.ps1` copies the synced chain + key and starts uvicorn on `:8900`
- J-Claw routes YETI tasks to the secondary automatically via `YETI_COORDINATOR_FALLBACK_URL` (health probe tries primary first, falls back transparently)

**Never run both coordinators simultaneously** — no consensus mechanism exists yet to merge diverging chains. Start the secondary only after confirming the core is truly down.

**Chain sync (required for failover):** Syncthing must sync these three files from the 9070 XT to the 3060 Ti continuously:
- `coordinator/coordinator.key` — same signing key so secondary-minted blocks are valid
- `coordinator/coordinator.pub`
- `coordinator/yeti-chain.jsonl` — current chain state

### Governance rule — majority vote for core changes

> **Any change that affects the network's core rules requires agreement from more than 50% of active nodes.**

"Core changes" include:
- Adding a new node to the coordinator/validator set
- Removing or replacing a node
- Changing `CHAIN_ID`, `REWARD_RATE`, `TREASURY_FEE`, `BASE_RATE`, or `DIFFICULTY_TARGET` at the protocol level
- Upgrading coordinator code in a way that changes block format or consensus rules
- Rotating the coordinator signing key

**Current threshold (2 nodes — 9070 XT + 3060 Ti):** both nodes must agree (1 of 2 = 50%, which does not meet the *greater than* 50% bar — you need 2 of 2).

**As nodes grow:** 3 nodes → 2 of 3; 5 nodes → 3 of 5; 9 nodes → 5 of 9 (aligns with Phase 3 BFT threshold).

**Until Phase 3 BFT is implemented:** governance votes are manual — both operators explicitly confirm in writing (GitHub commit, message, etc.) before any core change is applied. Phase 3 codifies this as on-chain threshold signature voting with 30-day transition windows.

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
- ✅ **Security hardening (round 1)**: Ed25519 sigs, model cross-check, JCLAW_API_KEY, nonce cap (500), subscription notify auth, canary 10→50, volunteer ID hijacking fix, rate limiting (5/min register, 30/min submit), wallet passphrase encryption prompt
- ✅ **Phase 0 → Phase 1 bridge**: Block #1 minted via J-Claw YETI pool route (20s, 1.836 YETI, signed). Bootstrap script `setup_volunteer.ps1` written.
- ✅ **Security hardening (round 2 — dual-review findings)**: Reward inflation fix (completion_tokens accumulated across nonce attempts), Ed25519 bypass fix (pre-hardening volunteers with no stored pubkey now rejected), chain append lock (`_chain_lock`), timeout memory leak cleanup, `failure_count` enforcement in registry. **53/53 tests pass.**
- ✅ **Phase 1 pre-tunnel fixes (2026-06-30)**:
  - Canary temperature fix — `task_queue.py` now forces `temperature=0.0` on canary assignments
  - Output sanitization — `sanitize_output()` in `sanitizer.py` strips control chars + truncates to 32k chars; wired into `main.py` before `deliver_result`
  - `nonce_attempts` minimum changed from `ge=0` to `ge=1` in `schemas.py`
  - Model auto-detection in `setup_volunteer.ps1` — detects VRAM via nvidia-smi → rocm-smi → WMI, selects model from ladder: <4 GB=qwen2.5:1.5b, 4-6=phi4-mini:3.8b, 6-10=qwen2.5-coder:7b-instruct (default), 10-20=deepseek-coder-v2:16b, 20+=qwen2.5-coder:32b. Passes detected values to setup wizard via env vars.
  - `validate_canary.py` — empirical validation script
  - Exponential backoff in `yeti_node.py` (`_backoff_delay` 5s→120s cap)
  - **60/60 tests pass (40 coordinator + 20 chain).**
- ✅ **Empirical canary validation (2026-06-30)**: ran `validate_canary.py` against live `qwen2.5-coder:7b-instruct`. Fixed 7 unreliable prompts + added `normalize_canary_output()` (strips Python quote-wrapping, markdown code blocks, trailing punctuation). **50/50 PASS.**
- ✅ **Git push (2026-06-30)**: commits `860b39c` + `5d88680` pushed to `Matt28296/soft-yeti` main. Git installed on 9070 XT via winget.
- ✅ **PWA dashboard (2026-07-01)**: local FastAPI server at `localhost:8901`. Card UI with mining toggle, live YETI balance (auto-refresh 10s), GPU/model/wallet display, PWA install prompt. Commit `75a0116`. Bug fixes (wallet address path + balance key) in `bdf4557`.
- ✅ **GPU name persisted in config (2026-07-01)**: `gpu_name` field added to `YetiConfig`; `setup_volunteer.ps1` passes `YETI_DETECTED_GPU` env var; dashboard uses persisted value with runtime fallback. Commit `64fb1c1`.
- ✅ **Named Cloudflare tunnel live (2026-07-01)**: `soft-yeti.com`, `www.soft-yeti.com`, `api.soft-yeti.com` all route to coordinator port 8900. Stable URL — does not change on restart.
- ✅ **Canary extended to laptop models (2026-07-01)**: ran `validate_canary.py` against `qwen2.5:1.5b-instruct` (model ladder <4GB / CPU inference). 30/50 initial failures — 1.5B fails boolean comparisons and multi-term arithmetic. Fixed 23 prompts with simple single-operation arithmetic. Added trailing punctuation strip to `normalize_canary_output()`. Raised `validate_canary.py` timeout 60s→300s (model cold-load). **50/50 on both 1.5B and 7B.** Commit `ff02d5e`. NOTE: Ollama KV-cache corruption bug discovered — `num_predict:1` warmup call poisons cache; all subsequent similar-prompt calls return EOS (empty response). Fix: never use `num_predict:1` for warmup; use `ollama stop <model>` to clear before re-testing.
- ✅ **Phase 1.5 — Zero protocol change quality wins (2026-07-01)**: Commit `8feb6e0`. **60/60 tests pass.**
  - Quality gate in client — `_passes_quality_gate()` in `yeti_node.py` filters outputs <20 chars or stuck in repetition loop before hash check; junk never hits the chain
  - Best-output delivery — client accumulates all outputs in `all_outputs` (cap 10); coordinator's `best_output()` in `sanitizer.py` scores by length + repetition, delivers highest-quality output to J-Claw (not just the hash-winner)
  - Base rate reward — `total_completion_tokens` tracked per task; `base_reward = total_ct × BASE_RATE (0.0001)` added to block gross on top of existing block reward; clients that don't send `total_completion_tokens` fall back to `ct × nonce_attempts`
  - New block fields: `total_completion_tokens`, `base_reward`; new submission fields: `total_completion_tokens`, `all_outputs` (all optional with defaults — old clients unaffected)
- ⏭ **Phase 1 — final gate**: send soft-yeti.com URL to 5 external testers → confirm connectivity + first block minted per tester → Phase 1 complete.
- ⏭ **Phase 2 — Hardening + Protocol foundation**:
  - Argon2 memory-hard PoW (Theory 2) — 256MB RAM per attempt; CPU/cloud scripts without VRAM can't forge this
  - Vulkan/PyOpenCL GPU benchmark — replace numpy stub with real GPU timing proof; **design backend-agnostic benchmark interface (Metal/Vulkan/CUDA) now** — avoids Phase 3 rewrite when mobile tier lands
  - True model fingerprinting — per-model expected-output calibration (replace name-match-only); first 10 tasks after registration are model-specific canary checks
  - **Proof of Inference Depth (PoID)** — alternative to hash lottery: miner runs N sequential self-refinement passes (`Pass_N = LLM("Improve: " + output_N-1)`), each chained via `hash(prev_output)` in the salt so passes can't be faked; all N outputs delivered; reward proportional to depth. No wasted inference. Introduced alongside hash-target mode for A/B test; default in Phase 3 if quality validates.
  - **On-chain model registry** — model ID (weights hash/Ollama digest), reputation score updated per task, family + parameter count recorded; high-reputation models earn 5% reward bonus. **Include `model_type` field (`standard` | `bitnet`) and `inference_backend` field (`ollama` | `metal` | `vulkan`) from day one** — mobile volunteers in Phase 3 need a distinct registry tier; retrofitting is painful.
  - Difficulty auto-adjustment — dynamic target based on block rate
  - ✅ `asyncio.Lock` per wallet in `subscription.py` — already implemented (Codex round 2)
  - Subscription economy live — on-chain YETI Transfer → access grants
  - Encrypted API key storage in client config (`~/.soft_yeti/config.json`)
  - ✅ Exponential backoff on client reconnect — `_backoff_delay(fail_count)` in `yeti_node.py` (5s→10s→20s…→120s cap, resets on success)
  - PyInstaller `SoftYetiSetup.exe` — one-click Windows installer
- ⏭ **Phase 3 — Quality + Decentralization**: HARD GATE — legal review (FinCEN MSB registration, KYC/AML compliance, Howey test analysis, **App Store mining policy**) FIRST. No exceptions.
  - BFT multi-validator consensus — threshold signatures (5-of-9 validators, staked YETI, slashing for fraud); block finality is deterministic not probabilistic; coordinator becomes first validator
  - Reference model judge — tiny fixed-weight model (hash pinned in protocol) scores every output at temperature=0; all nodes independently produce identical scores; no coordination needed
  - Peer quality committee — 10% of tasks selected for 5-miner committee review; commit-reveal scheme prevents herding; median score wins; outliers lose stake fraction
  - Bayesian miner reputation — `Beta(α,β)` per miner updated by quality scores; reward multiplier = `f(expected_quality, confidence)`; new miners earn at ~0.7× (low confidence prior); **Bayesian churn tolerance is essential for mobile volunteers** (screen lock = frequent disconnect; reputation must not crater on offline gaps)
  - Model diversity enforcement — each block requires ≥3 distinct model families; BFT at model layer; single-model compromise can't dominate >⅓ of any block
  - Elastic emission + EIP-1559 fee burn — emission tied to network utilization; 30% of task fees burned; deflationary at high utilization
  - DHT task queue — decentralized task routing; any node can post tasks; eliminates coordinator as single routing point
  - Judge model governance — on-chain vote (supermajority, 30-day transition) required to update reference judge weights; most politically critical control point in the protocol
  - **Mobile volunteer tier (iOS + Android)** — foreground-only mining via BitNet models (Microsoft 1.58-bit ternary weights) + QVAC Fabric (Metal on iOS, Vulkan on Android); iPhone 16 Pro Max A18 Pro confirmed capable of 7B–13B BitNet inference; no Ollama dependency. Requirements: (a) select a BitNet coding model (wait for BitNet `qwen2.5-coder` variant or use best available), (b) validate new per-model canary oracle against that model on iPhone hardware at temperature=0, (c) build Swift iOS app embedding QVAC Fabric — replicates Python mining loop foreground-only, (d) TestFlight distribution to testers. **Coordinator change:** add `inference_backend=metal` routing pool; mobile tasks get own difficulty target calibrated for A18 inference speed (~5–15s/attempt).
- ⏭ **Phase 4 — zkML + Full permissionless**:
  - zkML verification — ZK proof that specific model weights performed specific inference on specific input; verifying cheap, forging impossible; retires canary oracle, GPU benchmark, model fingerprinting (replaced by proof). **BitNet's ternary weight math (weights ∈ {-1,0,1}) makes zkML circuit construction significantly cheaper than FP16 — mobile miners may be the first tier where zkML is practical**
  - Recursive task DAGs — tasks declare input dependencies; blockchain verifies DAG integrity via output hashes; cryptographically immutable reasoning chains usable for regulated-industry audit trails
  - **Proof of Inference Diversity (PoDiv)** — M miners from different model families independently process same task; meta-model aggregates; miners earn proportionally to how much their output contributed to ensemble consensus. **Mobile BitNet volunteers are first-class PoDiv participants** — BitNet's different weight distribution and quantization produce meaningfully different outputs from GGUF models on the same prompt, which is exactly the diversity PoDiv rewards. Mobile miners earn a premium for being architecturally distinct, not competing head-to-head with desktop GPUs.
  - Permissionless validators — open validator entry (stake + 30-day probation + <5% concentration cap); stake concentration enforced on-chain
- ⏭ **Phase 5 — Network effects + Enterprise**:
  - On-chain computation lineage product — enterprise API for cryptographic provenance of any output (model identity, quality score, full input, timestamp, DAG); no competitor offers immutable AI reasoning audit trails
  - Open model ecosystem flywheel — on-chain model leaderboard (real-time quality scores from task performance); miners flock to high-reputation models; model developers share revenue with miners running their weights
  - Full closed-loop tokenomics at scale — burn rate exceeds issuance at sustained high utilization; YETI deflationary by network utility not artificial scarcity

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

**Test count after initial hardening: 46/46** (was 42/42; 2 sig tests + 2 nonce cap tests added).

**3060 Ti volunteer must re-run `--setup`** to register with the new `miner_pubkey` field before mining again.

---

## Phase 1 security + distribution additions (post-bridge, 2026-06-30)

| Fix | Files | Status |
|---|---|---|
| Canary oracle 10→50 tasks (5 categories) | `coordinator/canary.py` | ✅ Done |
| Volunteer ID hijacking fix (INSERT OR REPLACE → ownership check) | `coordinator/auth.py` | ✅ Done |
| 409 on hijack attempt | `coordinator/main.py` | ✅ Done |
| 5 new auth unit tests | `coordinator/tests/test_auth.py` | ✅ Done |
| Rate limiting (slowapi) on `/api/register` (5/min) + `/api/submit` (30/min) | `coordinator/main.py`, `coordinator/requirements.txt` | ✅ Done |
| Wallet passphrase prompt in setup wizard | `client/yeti_client.py` | ✅ Done |
| Passphrase prompt on startup for encrypted wallets | `client/yeti_client.py` | ✅ Done |
| Tester bootstrap script | `setup_volunteer.ps1` | ✅ Done |
| Test fixture fix (`JCLAW_API_KEY=""`) | `coordinator/tests/test_api.py` | ✅ Done |

**Test count: 31/31** coordinator tests pass.

**Remaining (Phase 2):**
- `benchmark_signature` is only checked non-empty — real cryptographic GPU timing verification needs Phase 2 Vulkan kernel
- Model verification is cross-check only (name match) — zkML proof for Phase 4

---

## Known gaps / Phase 2+ work

- `client/benchmark.py` uses numpy matrix multiply (Phase 0 stub) — Phase 2 replaces with PyOpenCL/Vulkan GPU kernel
- `coordinator/subscription.py` is a placeholder — Phase 2 wires on-chain YETI Transfer → access
- ✅ `asyncio.Lock` per wallet — already in `subscription.py` (`_wallet_locks` + `_wallet_locks_guard`)
- Difficulty auto-adjustment not yet implemented (static `DIFFICULTY_TARGET` in config)
- `client/build_installer.py` (PyInstaller → SoftYetiSetup.exe) not built
- ✅ Empirical canary validation complete — **50/50 PASS** against `qwen2.5-coder:7b-instruct` @ temperature=0. `normalize_canary_output()` added to `canary.py` (strips outer Python quotes + extracts Output: sections from code blocks). 7 prompts replaced with simpler equivalents where model gave wrong answers.
- **Canary oracle detects non-inference cheaters, NOT model substitution.** All 50 prompts have objectively correct answers (math, Python expressions) that any competent LLM returns identically. A volunteer swapping `llama3:8b` for `qwen2.5-coder:7b-instruct` passes canary just fine. The model cross-check in `verifier.py` is a name-match only, not cryptographic. True model fingerprinting requires per-model expected-output calibration (Phase 2) or zkML proofs (Phase 4).

---

## Key paths

- Coordinator: `soft-yeti/coordinator/` — start with `start_coordinator.ps1` from `soft-yeti/`
- Client: `soft-yeti/client/` — `python yeti_client.py [--setup]`
- Chain: `soft-yeti/chain/` — shared library, imported by coordinator
- Tests: `cd soft-yeti && python -m pytest coordinator/tests/` (40 tests)
- Chain tests: `cd soft-yeti && python -m pytest chain/test_chain.py` (20 tests)
- Plan: `~/.claude/plans/i-want-to-add-soft-yeti.md`
