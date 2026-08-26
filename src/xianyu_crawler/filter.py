"""规则过滤: 判断商品是否满足某个 Watch 条件 (高置信匹配)。"""
from __future__ import annotations

import re

from .models import Item
from .config import Watch


_NON_PRODUCT_TERMS = (
    "求购", "收购", "回收", "租赁", "出租", "维修", "代购", "定金", "咨询", "聊天", "话点", "我想要",
    "包装盒", "空盒", "保护壳", "贴膜", "配件",
)


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def keyword_matches(title: str, keywords: list[str]) -> bool:
    """至少命中搜索条件的核心词，排除求购、聊天等非商品帖。"""
    wanted = [_norm(k) for k in keywords if _norm(k)]
    if not wanted:
        return True
    haystack = _norm(title)
    # 逗号分隔的关键词视为必须出现的条件；带空格的词块拆成规格词。
    for raw in keywords:
        tokens = [_norm(x) for x in re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", raw)
                  if len(_norm(x)) >= 2]
        if tokens and not any(token in haystack for token in tokens):
            return False
    query = "".join(wanted)
    if any(term in title and term not in query for term in _NON_PRODUCT_TERMS):
        return False
    return True


def matches(item: Item, watch: Watch) -> bool:
    if not keyword_matches(item.title, watch.keywords):
        return False
    if watch.price_min is not None and item.price < watch.price_min:
        return False
    if watch.price_max is not None and item.price > watch.price_max:
        return False
    if watch.city and (not item.location or watch.city not in item.location):
        return False
    # 成色为 best-effort 提取(可能 None); 未知不过滤, 只在"已知且不符"时排除
    if watch.condition and item.condition is not None and item.condition not in watch.condition:
        return False
    if watch.free_shipping is not None and item.free_shipping != watch.free_shipping:
        return False
    # seller_min_credit: 信用分需在 Item.raw 中, v1 暂以存在即通过; 留待解析补字段
    return True
