"""商业版充值网关客户端。只保存用户令牌，不保存 DeepSeek/豆包主密钥。"""
from __future__ import annotations

import hashlib
import platform
import uuid

import httpx

from .config import Settings


def _device_id() -> str:
    raw = f"{platform.node()}:{uuid.getnode()}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def activate(settings: Settings, code: str) -> dict:
    if not settings.billing_base_url:
        return {"ok": False, "error": "运营端充值服务尚未配置"}
    try:
        response = httpx.post(
            settings.billing_base_url.rstrip("/") + "/v1/activate",
            json={"code": code.strip(), "device_id": _device_id()}, timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("access_token"):
            return {"ok": False, "error": "充值服务未返回用户令牌"}
        return {"ok": True, **data}
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", "充值码无效或已使用")
        except Exception:  # noqa: BLE001
            detail = "充值码无效或已使用"
        return {"ok": False, "error": str(detail)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"暂时无法连接充值服务：{exc}"}


def account(settings: Settings, token: str | None) -> dict:
    if not settings.billing_base_url:
        return {"configured": False, "active": False, "balance": 0}
    if not token:
        return {"configured": True, "active": False, "balance": 0}
    try:
        response = httpx.get(
            settings.billing_base_url.rstrip("/") + "/v1/account",
            headers={"Authorization": f"Bearer {token}"}, timeout=12,
        )
        response.raise_for_status()
        return {"configured": True, "active": True, **response.json()}
    except Exception:  # noqa: BLE001
        return {"configured": True, "active": True, "offline": True}
