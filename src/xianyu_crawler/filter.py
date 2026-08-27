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
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())
    # 闲鱼网页会把常见错序品牌词自动纠正，但直接请求搜索接口不会。
    # 匹配阶段也统一成平台常用写法，避免“康时泰 G1”无法命中“康泰时 G1”。
    return value.replace("康时泰", "康泰时").replace("contax", "康泰时")


def _norm_condition(text: str) -> str:
    chinese = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
               "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
    value = _norm(text)
    for old, new in chinese.items():
        value = value.replace(old, new)
    return value.replace("成新", "新")


def keyword_matches(title: str, keywords: list[str]) -> bool:
    """至少命中搜索条件的核心词，排除求购、聊天等非商品帖。"""
    wanted = [_norm(k) for k in keywords if _norm(k)]
    if not wanted:
        return True
    haystack = _norm(title)
    # 搜索词中的品牌、型号、规格必须全部命中。旧逻辑用了 any，导致
    # “康泰时 G1”只要出现“康泰时”就放行 T1/G2/镜头等不对应商品。
    for raw in keywords:
        tokens = [_norm(x) for x in re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", raw)
                  if len(_norm(x)) >= 2]
        if tokens and not all(token in haystack for token in tokens):
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
    # 城市/区县由搜索页原生“区域”控件筛选。卡片经常只返回省份（如浙江），
    # 不能再拿这个残缺字段做二次判断，否则杭州结果会被误删。
    # 成色为 best-effort 提取(可能 None); 未知不过滤, 只在"已知且不符"时排除
    if (watch.condition and item.condition is not None
            and _norm_condition(item.condition) not in {_norm_condition(x) for x in watch.condition}):
        return False
    if watch.free_shipping is not None and item.free_shipping != watch.free_shipping:
        return False
    # seller_min_credit: 信用分需在 Item.raw 中, v1 暂以存在即通过; 留待解析补字段
    return True
