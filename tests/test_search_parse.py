"""search 显式解析回归 (合成 sample, 结构同真实 mtop 响应)。"""
import json
from pathlib import Path

import pytest

from xianyu_crawler.search import parse_search_json, normalize_search_query, _native_condition


def test_search_query_applies_same_correction_as_goofish_web():
    assert normalize_search_query("康时泰 G1") == "康泰时 G1"


def test_native_condition_is_read_from_card_tags_not_only_title():
    card = {"tags": [{"text": "轻微使用痕迹"}], "title": "康泰时 G1"}
    assert _native_condition(card, "康泰时 G1") == "轻微使用痕迹"

FIXTURE = Path(__file__).parent / "fixtures" / "search.sample.json"


@pytest.mark.skipif(not FIXTURE.exists(), reason="缺 search.sample.json")
def test_parse_search_sample():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    items = parse_search_json(raw)
    assert len(items) == 1
    it = items[0]
    assert it.item_id == "111"
    assert it.title.startswith("测试")
    assert it.price == 1234.0            # 用 soldPrice, 非样式串
    assert it.location == "上海"
    assert it.free_shipping is True
    assert it.condition == "99新"
    assert it.url == "https://www.goofish.com/item?id=111"
