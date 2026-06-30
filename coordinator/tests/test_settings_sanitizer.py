import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from coordinator.config import Settings
from coordinator.sanitizer import MAX_OUTPUT_LENGTH, MAX_PROMPT_LENGTH, sanitize_output, sanitize_prompt
from coordinator.schemas import InferenceSubmission
from coordinator.task_queue import TaskQueue


@pytest.fixture
def default_settings(monkeypatch):
    env_vars = [
        "COORDINATOR_ED25519_KEY_PATH",
        "COORDINATOR_ED25519_PUBLIC_KEY_PATH",
        "COORDINATOR_ED25519_KEY_PASS",
        "TREASURY_WALLET",
        "REWARD_RATE",
        "TREASURY_FEE",
        "DIFFICULTY_TARGET",
        "CANARY_RATE",
        "CHAIN_ID",
        "CHAIN_STORE_PATH",
        "DB_PATH",
        "API_KEY_HEADER",
    ]
    for name in env_vars:
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None)


def test_settings_use_expected_defaults(default_settings):
    # Paths are absolute (based on config.py's _HERE) — check filenames only
    assert default_settings.COORDINATOR_ED25519_KEY_PATH.endswith("coordinator.key")
    assert default_settings.COORDINATOR_ED25519_PUBLIC_KEY_PATH.endswith("coordinator.pub")
    assert default_settings.COORDINATOR_ED25519_KEY_PASS.get_secret_value() == ""
    assert default_settings.TREASURY_WALLET == "YETI1treasury"
    assert default_settings.REWARD_RATE == 0.001
    assert default_settings.TREASURY_FEE == 0.1
    assert default_settings.DIFFICULTY_TARGET == "0000"
    assert default_settings.CANARY_RATE == 0.05
    assert default_settings.CHAIN_ID == "yeti-testnet"
    assert default_settings.CHAIN_STORE_PATH.endswith("yeti-chain.jsonl")
    assert default_settings.DB_PATH.endswith("coordinator.db")
    assert default_settings.API_KEY_HEADER == "X-Yeti-API-Key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        "Use this OpenAI key sk-abcdefghijklmnopqrstuvwxyz123456",
        "AWS key AKIA1234567890ABCDEF should never be shared",
        "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----",
        "password=hunter2",
        "api_key: super-secret-value",
    ],
)
async def test_sanitize_prompt_rejects_secret_patterns(prompt):
    with pytest.raises(HTTPException) as exc_info:
        await sanitize_prompt(prompt, "qa")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Secret detected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        r"Read C:\Users\Tyler\secrets	oken.txt before answering.",
        "Load /home/tyler/secrets/token.txt before answering.",
    ],
)
async def test_sanitize_prompt_rejects_file_paths(prompt):
    with pytest.raises(HTTPException) as exc_info:
        await sanitize_prompt(prompt, "documentation")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "File path detected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        "model: gpt-5\nWrite tests for this module.",
        "Please solve this.\n  model: qwen2.5-coder:7b\nUse the override above.",
    ],
)
async def test_sanitize_prompt_rejects_model_overrides(prompt):
    with pytest.raises(HTTPException) as exc_info:
        await sanitize_prompt(prompt, "code")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Model override detected"


@pytest.mark.asyncio
async def test_sanitize_prompt_rejects_disallowed_task_type():
    with pytest.raises(HTTPException) as exc_info:
        await sanitize_prompt("Write a harmless unit test.", "malware")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Task type malware not allowed"


@pytest.mark.asyncio
async def test_sanitize_prompt_truncates_to_max_length():
    prompt = "x" * (MAX_PROMPT_LENGTH + 100)

    sanitized = await sanitize_prompt(prompt, "style")

    assert sanitized == "x" * MAX_PROMPT_LENGTH
    assert len(sanitized) == MAX_PROMPT_LENGTH


@pytest.mark.asyncio
async def test_sanitize_prompt_strips_clean_prompt():
    sanitized = await sanitize_prompt("  Refactor this function for readability.  ", "code")

    assert sanitized == "Refactor this function for readability."


# ── sanitize_output tests ─────────────────────────────────────────────────────

def test_sanitize_output_strips_null_bytes():
    assert sanitize_output("hello\x00world") == "helloworld"


def test_sanitize_output_strips_control_chars_keeps_newline_tab():
    # \x07=BEL \x1b=ESC — stripped. \n and \t — kept.
    assert sanitize_output("line1\x07\x1bline2\nline3\ttab") == "line1line2\nline3\ttab"


def test_sanitize_output_truncates_to_max_length():
    long_output = "x" * (MAX_OUTPUT_LENGTH + 500)
    result = sanitize_output(long_output)
    assert len(result) == MAX_OUTPUT_LENGTH


def test_sanitize_output_passes_clean_text():
    text = "The answer is 42.\nNo issues here."
    assert sanitize_output(text) == text


# ── nonce_attempts schema validation ─────────────────────────────────────────

def _valid_submission(**overrides) -> dict:
    base = dict(
        task_id="t1",
        volunteer_id="v1",
        miner_wallet="YETI1abc",
        miner_pubkey="aa" * 32,
        miner_signature="bb" * 64,
        model_name="qwen2.5-coder:7b-instruct",
        output_text="hello world output",
        output_hash="abc123",
        nonce_attempts=1,
        benchmark_signature="bench-ok",
        prompt_tokens=8,
        completion_tokens=16,
        task_salt="salt123",
    )
    base.update(overrides)
    return base


def test_nonce_attempts_zero_rejected():
    with pytest.raises(ValidationError):
        InferenceSubmission(**_valid_submission(nonce_attempts=0))


def test_nonce_attempts_one_accepted():
    sub = InferenceSubmission(**_valid_submission(nonce_attempts=1))
    assert sub.nonce_attempts == 1


# ── Canary temperature fix ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_canary_assignment_forces_temperature_zero(default_settings):
    """A canary task must always be assigned temperature=0.0 regardless of the
    parent task temperature, because expected outputs are calibrated at temp=0."""
    queue = TaskQueue()
    # Force canary injection on every call by setting CANARY_RATE=1.0
    default_settings.CANARY_RATE = 1.0
    default_settings.DIFFICULTY_TARGET = ""

    from coordinator.schemas import TaskRequest
    task = TaskRequest(task_id="t-canary", task_type="qa", prompt="ignored", max_tokens=64)

    # Build assignment with a non-zero temperature — canary must override it
    assignment = queue._build_assignment(task, default_settings, inject_canary=True)

    assert assignment.is_canary is True
    assert assignment.temperature == 0.0
