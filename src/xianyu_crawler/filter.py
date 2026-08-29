"""规则过滤: 判断商品是否满足某个 Watch 条件 (高置信匹配)。"""
from __future__ import annotations

import re

from .models import Item
from .config import Watch
from .regions import location_matches


_NON_PRODUCT_TERMS = (
    "求购", "收购", "回收", "租赁", "出租", "维修", "代购", "定金", "咨询", "聊天", "话点", "我想要",
    "包装盒", "空盒", "保护壳", "贴膜", "配件", "镜头", "转接环", "后背",
    "闪光灯", "取景器", "皮套", "说明书", "前盖", "后盖", "滤镜", "附件",
    "适用", "可用", "兼容", "联名", "KITH", "服装", "短袖", "卫衣", "帽子",
)

_ACCESSORY_SPEC = re.compile(r"(?:^|[^a-z0-9])(?:g|f)?\d{2,3}(?:\.\d+)?\s*(?:mm|/\d(?:\.\d+)?)", re.I)


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
    raw_haystack = title.lower().replace("contax", "康泰时").replace("康时泰", "康泰时")
    # 搜索词中的品牌、型号、规格必须全部命中。旧逻辑用了 any，导致
    # “康泰时 G1”只要出现“康泰时”就放行 T1/G2/镜头等不对应商品。
    for raw in keywords:
        tokens = [_norm(x) for x in re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", raw)
                  if len(_norm(x)) >= 2]
        def contains(token: str) -> bool:
            # 型号必须是完整字母数字词。旧的纯 substring 会把 “AEG 1”
            # 去空格后变成 aeg1，继而错误命中 g1。
            if re.fullmatch(r"[a-z]+\d+[a-z0-9]*", token, re.I):
                parts = re.findall(r"[a-z]+|\d+", token, re.I)
                pattern = r"(?<![a-z0-9])" + r"[\s._/+\-]*".join(map(re.escape, parts)) + r"(?![a-z0-9])"
                return re.search(pattern, raw_haystack, re.I) is not None
            return token in haystack
        if tokens and not all(contains(token) for token in tokens):
            return False
    query = "".join(wanted)
    if any(_norm(term) in haystack and _norm(term) not in query for term in _NON_PRODUCT_TERMS):
        return False
    # 镜头标题常只写“G45/2”“90/2.8”，没有“镜头”二字；这类兼容性文字
    # 不能因为后面出现“G1/G2可用”就被当成 G1 相机机身。
    if _ACCESSORY_SPEC.search(title) and not _ACCESSORY_SPEC.search(query):
        return False
    return True


def matches(item: Item, watch: Watch) -> bool:
    # 原生接口也会返回扩展推荐；仍须要求品牌/型号全部命中。否则搜索
    # “康泰时 G1”会混入 U4R、G2、镜头和其他配件。
    if not keyword_matches(item.title, watch.keywords):
        return False
    if watch.price_min is not None and item.price < watch.price_min:
        return False
    if watch.price_max is not None and item.price > watch.price_max:
        return False
    # 原生地区筛选必须生效；若卡片给出了可判定的省/市/区而明确属于
    # 其他城市，则拒绝入库。字段缺失时保留，避免误删平台未返回地址的商品。
    if not location_matches(item.location, watch.province, watch.city, watch.district):
        return False
    # 成色为 best-effort 提取(可能 None); 未知不过滤, 只在"已知且不符"时排除
    if (watch.condition and item.condition is not None
            and _norm_condition(item.condition) not in {_norm_condition(x) for x in watch.condition}):
        return False
    if watch.free_shipping is not None and item.free_shipping != watch.free_shipping:
        return False
    # seller_min_credit: 信用分需在 Item.raw 中, v1 暂以存在即通过; 留待解析补字段
    return True
