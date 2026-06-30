"""
FastAPI sub-app exposing chain data.

Mount at /chain on the coordinator's main app:
    app.mount("/chain", chain_node)

Endpoints:
    GET /chain/height          — current chain height (number of blocks)
    GET /chain/block/{index}   — block by index
    GET /chain/latest          — most recent block
    GET /chain/balance/{addr}  — YETI balance for a wallet address
    GET /chain/history/{addr}  — recent blocks mined by a wallet
    GET /chain/verify          — run full chain integrity check (slow on large chains)
"""

from fastapi import FastAPI, HTTPException, Query

from .chain import ChainManager

chain_node = FastAPI(title="YETI Chain Node")

# Set by coordinator/main.py at startup:
#   chain_node.state.chain = ChainManager(storage, coordinator_pubkey_hex)
#
# Access here via: chain_node.state.chain


def _get_chain() -> ChainManager:
    mgr = getattr(chain_node.state, "chain", None)
    if mgr is None:
        raise HTTPException(503, "Chain not initialized")
    return mgr


@chain_node.get("/height")
async def get_height():
    return {"height": await _get_chain().get_height()}


@chain_node.get("/latest")
async def get_latest():
    block = await _get_chain().get_latest()
    if block is None:
        raise HTTPException(404, "Chain is empty")
    return block.to_dict()


@chain_node.get("/block/{index}")
async def get_block(index: int):
    block = await _get_chain().get_block(index)
    if block is None:
        raise HTTPException(404, f"Block {index} not found")
    return block.to_dict()


@chain_node.get("/balance/{addr}")
async def get_balance(addr: str):
    balance = await _get_chain().get_balance(addr)
    return {"wallet": addr, "balance_yeti": balance}


@chain_node.get("/history/{addr}")
async def get_history(
    addr: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    blocks = await _get_chain().get_history(addr, limit=limit, offset=offset)
    return {"wallet": addr, "blocks": [b.to_dict() for b in blocks]}


@chain_node.get("/verify")
async def verify_chain():
    ok, message = await _get_chain().verify_chain()
    return {"valid": ok, "message": message}
