"""通用 JSON 解析助手。

- `items_from_json` / `node_to_item`: 防御式遍历(供 discover 评估"商品可能性")。
- `to_price` / `guess_condition`: search / favorites 显式解析器共用的字段工具。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import quote

from .models import Item


def to_dt_ms(v: object) -> datetime | None:
    """毫秒时间戳(闲鱼 publishTime, 如 "1781241796000")→ 朴素 UTC datetime。"""
    try:
        ms = int(str(v).strip())
    except (ValueError, TypeError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)

_ID_KEYS = ("itemId", "item_id", "id")
_TITLE_KEYS = ("title", "name")
_PRICE_KEYS = ("price", "soldPrice", "priceText")
_LOC_KEYS = ("area", "location", "city")
_NICK_KEYS = ("userNick", "nick", "sellerNick")

_COND_RE = re.compile(r"(全新|几乎全新|准新|[一二三四五六七八九十]成新|\d成新|\d{1,3}新)")


def to_price(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    # 当前 PC 搜索接口的 exContent.price 经常是富文本分段：
    # [{"text":"当前价"},{"text":"¥"},{"text":"2,999"}]。
    # 旧版直接拒绝 list/dict，导致整页商品全部因“无价格”被丢弃。
    if isinstance(v, list):
        parts = []
        for part in v:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("value") or ""))
            elif part is not None:
                parts.append(str(part))
        v = "".join(parts)
    elif isinstance(v, dict):
        v = v.get("text") or v.get("value") or v.get("price")
        if v is None:
            return None
    try:
        text = str(v).replace("当前价", "").replace("¥", "").replace("￥", "").replace(",", "").strip()
        multiplier = 10000 if text.endswith("万") else 1
        if multiplier != 1:
            text = text[:-1].strip()
        return float(text) * multiplier
    except (ValueError, TypeError):
        return None


def guess_condition(title: str | None) -> str | None:
    """从标题里 best-effort 猜成色(全新/99新/9成新...); 猜不到返回 None。"""
    if not title:
        return None
    m = _COND_RE.search(title)
    return m.group(1) if m else None


def _first(node: dict, keys: tuple[str, ...]) -> object:
    for k in keys:
        if k in node and node[k] not in (None, ""):
            return node[k]
    return None


def walk_dicts(obj: object) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def node_to_item(node: dict) -> Item | None:
    item_id = _first(node, _ID_KEYS)
    title = _first(node, _TITLE_KEYS)
    price = to_price(_first(node, _PRICE_KEYS))
    if not (item_id and title) or price is None:
        return None
    loc = _first(node, _LOC_KEYS)
    nick = _first(node, _NICK_KEYS)
    return Item(
        item_id=str(item_id),
        title=str(title),
        price=price,
        url=f"https://www.goofish.com/item?id={quote(str(item_id))}",
        location=str(loc) if isinstance(loc, str) else None,
        seller_nick=str(nick) if isinstance(nick, str) else None,
        raw=node,
    )


def items_from_json(raw: dict) -> list[Item]:
    seen: set[str] = set()
    out: list[Item] = []
    for node in walk_dicts(raw):
        it = node_to_item(node)
        if it and it.item_id not in seen:
            seen.add(it.item_id)
            out.append(it)
    return out
