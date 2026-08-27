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


def test_mixed_old_and_new_card_shapes_are_merged():
    """命中旧卡片不能导致同页新结构卡片被整体跳过。"""
    raw = {
        "data": {
            "resultList": [{"data": {"item": {"main": {
                "exContent": {"itemId": "old", "title": "康泰时 G1 老结构",
                              "detailParams": {"soldPrice": "2300"}}
            }}}}],
            "grayCardPayload": {
                "itemId": "new", "title": "康泰时 G1 新结构", "priceText": "2999"
            },
        }
    }
    items = parse_search_json(raw)
    assert {item.item_id for item in items} == {"old", "new"}


def test_current_rich_text_price_and_target_url_are_parsed():
    raw = {"data": {"resultList": [{"data": {"item": {"main": {
        "targetUrl": "fleamarket://item?id=987654321",
        "exContent": {
            "title": "康泰时 G1 绿标机身",
            "price": [{"text": "当前价"}, {"text": "¥"}, {"text": "2,999"}],
            "area": "杭州",
        },
    }}}}]}}
    items = parse_search_json(raw)
    assert len(items) == 1
    assert items[0].item_id == "987654321"
    assert items[0].price == 2999
