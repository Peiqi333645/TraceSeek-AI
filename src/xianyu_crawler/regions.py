"""闲鱼地区条件标准化（界面名称，不使用容易变化的内部区域代码）。"""
from __future__ import annotations


_CITY_TO_PROVINCE = {
    "北京": "北京", "上海": "上海", "天津": "天津", "重庆": "重庆",
    "杭州": "浙江", "宁波": "浙江", "温州": "浙江", "嘉兴": "浙江", "湖州": "浙江",
    "绍兴": "浙江", "金华": "浙江", "衢州": "浙江", "舟山": "浙江", "台州": "浙江", "丽水": "浙江",
    "广州": "广东", "深圳": "广东", "南京": "江苏", "苏州": "江苏", "成都": "四川",
    "武汉": "湖北", "长沙": "湖南", "郑州": "河南", "西安": "陕西", "济南": "山东",
    "青岛": "山东", "福州": "福建", "厦门": "福建", "合肥": "安徽", "南昌": "江西",
    "沈阳": "辽宁", "长春": "吉林", "哈尔滨": "黑龙江", "石家庄": "河北", "太原": "山西",
    "昆明": "云南", "贵阳": "贵州", "南宁": "广西", "海口": "海南", "兰州": "甘肃",
    "西宁": "青海", "银川": "宁夏", "呼和浩特": "内蒙古", "乌鲁木齐": "新疆", "拉萨": "西藏",
}

_HANGZHOU_DISTRICTS = {
    "上城区", "拱墅区", "西湖区", "滨江区", "萧山区", "余杭区", "临平区",
    "钱塘区", "富阳区", "临安区", "桐庐县", "淳安县", "建德市",
}

try:
    from .region_index import CITY_TO_PROVINCE as _ALL_CITY_TO_PROVINCE
    from .region_index import DISTRICT_TO_REGIONS as _DISTRICT_TO_REGIONS
except ImportError:  # 兼容旧安装包局部覆盖
    _ALL_CITY_TO_PROVINCE = _CITY_TO_PROVINCE
    _DISTRICT_TO_REGIONS = {}


def normalize_region(province: str | None, city: str | None,
                     district: str | None) -> tuple[str, str, str]:
    """去掉省市后缀，并为明确可识别的市/区补齐上级地区。"""
    p = (province or "").strip()
    for suffix in ("特别行政区", "壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "省", "市"):
        if p.endswith(suffix):
            p = p.removesuffix(suffix)
            break
    c = (city or "").strip().removesuffix("市")
    d = (district or "").strip()
    if not c and d in _HANGZHOU_DISTRICTS:
        c = "杭州"
    if not p and c:
        p = _ALL_CITY_TO_PROVINCE.get(c, _CITY_TO_PROVINCE.get(c, ""))
    return p, c, d


def _strip(value: str | None) -> str:
    text = (value or "").strip()
    for suffix in ("特别行政区", "壮族自治区", "回族自治区", "维吾尔自治区",
                   "自治区", "省", "市"):
        if text.endswith(suffix):
            return text.removesuffix(suffix)
    return text


def location_matches(location: str | None, province: str | None, city: str | None,
                     district: str | None) -> bool:
    """卡片地址明确冲突时返回 False；地址缺失或无法判定时不误删。"""
    if not location:
        return True
    wanted_p, wanted_c, wanted_d = normalize_region(province, city, district)
    if not any((wanted_p, wanted_c, wanted_d)):
        return True
    loc = _strip(location)
    if wanted_d:
        return loc == _strip(wanted_d) or wanted_d in location
    if loc in _DISTRICT_TO_REGIONS:
        actual_p, actual_c = _DISTRICT_TO_REGIONS[loc]
        if wanted_c and actual_c != wanted_c:
            return False
        if wanted_p and actual_p != wanted_p:
            return False
        return True
    if loc in _ALL_CITY_TO_PROVINCE:
        if wanted_c and loc != wanted_c:
            return False
        return not wanted_p or _ALL_CITY_TO_PROVINCE[loc] == wanted_p
    # 只返回省份时仍可确认省级冲突，但不能据此排除省内某个城市。
    known_provinces = set(_ALL_CITY_TO_PROVINCE.values())
    if loc in known_provinces:
        return not wanted_p or loc == wanted_p
    return True
