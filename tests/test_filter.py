from xianyu_crawler.models import Item
from xianyu_crawler.config import Watch
from xianyu_crawler.filter import matches


def W(**kw):
    return Watch(name="w", keywords=["x"]).model_copy(update=kw)


def I(**kw):
    return Item(item_id="1", title="t", url="u", price=1000.0,
                location="上海市", condition="99新", free_shipping=True).model_copy(update=kw)


def test_price_within_range():
    assert matches(I(price=1000), W(price_min=500, price_max=2000)) is True


def test_price_below_min():
    assert matches(I(price=400), W(price_min=500)) is False


def test_price_above_max():
    assert matches(I(price=3000), W(price_max=2000)) is False


def test_city_is_not_guessed_from_incomplete_card_location():
    assert matches(I(location="上海市浦东"), W(city="上海")) is True
    # 地区由闲鱼原生区域控件执行；卡片地址只显示省份/城市时不再二次误删。
    assert matches(I(location="北京市"), W(city="上海")) is True


def test_missing_city_metadata_does_not_drop_item():
    assert matches(I(title="康时泰 G1 九成新", location=None),
                   W(keywords=["康时泰 G1"], city="杭州")) is True


def test_common_brand_typo_matches_correct_listing_title():
    assert matches(I(title="康泰时 G1 相机 九成新"),
                   W(keywords=["康时泰 G1"])) is True


def test_all_keyword_tokens_are_required_and_english_brand_alias_matches():
    watch = W(keywords=["康泰时 G1"])
    assert matches(I(title="CONTAX G1 绿标机身"), watch) is True
    assert matches(I(title="康泰时 T1 旁轴相机"), watch) is False
    assert matches(I(title="康泰时 G2 机身"), watch) is False


def test_condition_in_list():
    assert matches(I(condition="95新"), W(condition=["99新", "95新"])) is True
    assert matches(I(condition="8成新"), W(condition=["99新"])) is False


def test_unknown_condition_passes():
    # 成色未知(None)时不应被成色过滤排除
    assert matches(I(condition=None), W(condition=["99新"])) is True


def test_condition_chinese_and_number_are_equivalent():
    assert matches(I(condition="九成新"), W(condition=["9新"])) is True


def test_free_shipping_required():
    assert matches(I(free_shipping=False), W(free_shipping=True)) is False


def test_none_criteria_ignored():
    assert matches(I(location=None, condition=None), W()) is True


def test_keyword_relevance_rejects_unrelated_listing():
    watch = W(keywords=["MacBook"])
    assert matches(I(title="MacBook Pro 14寸 M1 Pro"), watch) is True
    assert matches(I(title="烟台日落 感兴趣的话点我想要聊吧"), watch) is False


def test_non_product_post_is_rejected():
    watch = W(keywords=["MacBook"])
    assert matches(I(title="回收 MacBook 高价咨询"), watch) is False


def test_native_search_still_requires_exact_model_relevance():
    watch = W(keywords=["康泰时 G1"], price_min=2000, price_max=4000, city="杭州")
    item = I(title="CONTAX 旁轴绿标机身", price=2999, location="浙江",
             raw={"_xianyu_native_search": True})
    assert matches(item, watch) is False
