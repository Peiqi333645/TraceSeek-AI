"""寻迹AI助手统一网关：充值码、余额、用户令牌与 OpenAI 兼容转发。"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

DB_PATH = Path(os.getenv("GATEWAY_DB", "gateway.db"))
ADMIN_KEY = os.getenv("GATEWAY_ADMIN_KEY", "")
UPSTREAM_BASE_URL = os.getenv("UPSTREAM_BASE_URL", "https://api.deepseek.com")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "")
UPSTREAM_MODEL = os.getenv("UPSTREAM_MODEL", "deepseek-chat")

app = FastAPI(title="寻迹AI助手网关", docs_url=None, redoc_url=None)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _init() -> None:
    with closing(_db()) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, account TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
          device_id TEXT NOT NULL, balance INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS codes(
          code_hash TEXT PRIMARY KEY, credits INTEGER NOT NULL, used_by INTEGER, used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS usage_log(
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, credits INTEGER NOT NULL,
          prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        con.commit()


_init()


class Activation(BaseModel):
    code: str
    device_id: str


class CodeBatch(BaseModel):
    count: int = 1
    credits: int = 500


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "请先充值激活")
    return authorization[7:].strip()


def _user(token: str) -> sqlite3.Row:
    with closing(_db()) as con:
        row = con.execute("SELECT * FROM users WHERE token_hash=? AND active=1", (_hash(token),)).fetchone()
    if not row:
        raise HTTPException(401, "登录已失效，请重新激活")
    return row


@app.post("/admin/codes")
def create_codes(body: CodeBatch, x_admin_key: str | None = Header(default=None)):
    if not ADMIN_KEY or not secrets.compare_digest(x_admin_key or "", ADMIN_KEY):
        raise HTTPException(403, "无权操作")
    count = min(max(body.count, 1), 100)
    credits = max(body.credits, 1)
    codes = ["TS-" + secrets.token_hex(6).upper() for _ in range(count)]
    with closing(_db()) as con:
        con.executemany("INSERT INTO codes(code_hash, credits) VALUES(?,?)", [(_hash(c), credits) for c in codes])
        con.commit()
    return {"codes": codes, "credits": credits}


@app.post("/v1/activate")
def activate(body: Activation):
    if not body.code.strip() or not body.device_id.strip():
        raise HTTPException(400, "充值码或设备信息不能为空")
    with closing(_db()) as con:
        con.execute("BEGIN IMMEDIATE")
        code = con.execute("SELECT * FROM codes WHERE code_hash=?", (_hash(body.code.strip()),)).fetchone()
        if not code or code["used_by"] is not None:
            raise HTTPException(400, "充值码无效或已使用")
        token = secrets.token_urlsafe(32)
        existing = con.execute("SELECT * FROM users WHERE device_id=? AND active=1", (body.device_id,)).fetchone()
        if existing:
            account = existing["account"]
            user_id = existing["id"]
            con.execute(
                "UPDATE users SET token_hash=?,balance=balance+? WHERE id=?",
                (_hash(token), code["credits"], user_id),
            )
            balance = existing["balance"] + code["credits"]
        else:
            account = "TS" + secrets.token_hex(3).upper()
            cur = con.execute(
                "INSERT INTO users(account,token_hash,device_id,balance) VALUES(?,?,?,?)",
                (account, _hash(token), body.device_id, code["credits"]),
            )
            user_id = cur.lastrowid
            balance = code["credits"]
        con.execute("UPDATE codes SET used_by=?,used_at=CURRENT_TIMESTAMP WHERE code_hash=?", (user_id, code["code_hash"]))
        con.commit()
    return {"access_token": token, "account": account, "balance": balance, "model": "smart-review"}


@app.get("/v1/account")
def account(authorization: str | None = Header(default=None)):
    row = _user(_bearer(authorization))
    return {"account": row["account"], "balance": row["balance"]}


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict, authorization: str | None = Header(default=None)):
    token = _bearer(authorization)
    row = _user(token)
    if row["balance"] < 1:
        raise HTTPException(402, "AI分析次数不足，请充值")
    if not UPSTREAM_API_KEY:
        raise HTTPException(503, "运营端尚未配置上游API")
    outgoing = {**payload, "model": UPSTREAM_MODEL}
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            UPSTREAM_BASE_URL.rstrip("/") + "/chat/completions",
            json=outgoing,
            headers={"Authorization": f"Bearer {UPSTREAM_API_KEY}", "Content-Type": "application/json"},
        )
    if response.status_code >= 400:
        raise HTTPException(502, "AI服务暂时不可用，本次未扣费")
    data = response.json()
    usage = data.get("usage") or {}
    with closing(_db()) as con:
        con.execute("BEGIN IMMEDIATE")
        changed = con.execute("UPDATE users SET balance=balance-1 WHERE id=? AND balance>=1", (row["id"],)).rowcount
        if not changed:
            raise HTTPException(402, "AI分析次数不足，请充值")
        con.execute(
            "INSERT INTO usage_log(user_id,credits,prompt_tokens,completion_tokens) VALUES(?,?,?,?)",
            (row["id"], 1, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))),
        )
        con.commit()
    data["model"] = "smart-review"
    return data
