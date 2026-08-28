"""搜索: 跑搜索页 → 拦截 mtop 搜索接口 JSON → 翻页加载 → 解析为 Item。

watch.keywords 是**一个**搜索词的若干词块, 用空格拼成一条 query 搜一次(不是逐词分搜)。
接口: mtop.taobao.idlemtopsearch.pc.search
商品: data.resultList[].data.item.main.exContent (+ detailParams / clickParam.args)
分页: 点击网页 ``1/50`` 右侧下一页按钮，并校验每页商品 ID 确实变化。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from urllib.parse import quote

from .config import Watch
from .models import Item
from .parsing import to_price, guess_condition, to_dt_ms, items_from_json
from .regions import normalize_region
SEARCH_URL = "https://www.goofish.com/search"
SEARCH_API = "mtop.taobao.idlemtopsearch.pc.search"
MTOP_URL = f"https://h5api.m.goofish.com/h5/{SEARCH_API}/1.0/"
MTOP_APP_KEY = "34839810"
CONDITION_LABELS = (
    "包装脏污/变形/破损", "轻微划痕/脏污", "轻微使用痕迹", "明显使用痕迹",
    "仅拆封未使用", "几乎全新", "无原包装", "官翻机", "全新",
)


def normalize_search_query(query: str) -> str:
    """补齐网页端具备、直接接口搜索不具备的少量确定性纠错。"""
    return query.replace("康时泰", "康泰时")


def build_search_payload(query: str, watch: Watch, page_number: int) -> dict:
    """构造与闲鱼 PC 搜索页相同的筛选请求体。

    价格走 ``propValueStr.searchFilter``，地区走
    ``extraFilterValue.divisionList``；不再通过不稳定的页面 DOM 点击筛选。
    """
    search_filters: list[str] = []
    if watch.price_min is not None or watch.price_max is not None:
        low = 0 if watch.price_min is None else watch.price_min
        high = 99999999 if watch.price_max is None else watch.price_max
        search_filters.append(f"priceRange:{low:g},{high:g}")
    province, city, district = normalize_region(watch.province, watch.city, watch.district)
    place = province or city or district
    extra = "{}"
    if place:
        division_list = []
        if province or city:
            division_list.append({"province": province, "city": city})
        extra = json.dumps({
            # 闲鱼 PC 搜索把省/市放在 divisionList，区县只使用顶层 area。
            # 不发送平台不识别的自定义区县字段。
            "divisionList": division_list,
            "excludeMultiPlacesSellers": "0",
        }, ensure_ascii=False, separators=(",", ":"))
    return {
        "pageNumber": int(page_number),
        "keyword": query,
        "fromFilter": bool(search_filters or place),
        "rowsPerPage": 30,
        # 与截图中的“综合”排序一致，不擅自改成最新发布。
        "sortValue": "",
        "sortField": "",
        "customDistance": "",
        "gps": "",
        "propValueStr": {"searchFilter": ";".join(search_filters) + (";" if search_filters else "")},
        "customGps": "",
        "province": province,
        "city": city,
        "area": district,
        "searchReqFromPage": "xyHome",
        "searchTabType": "SEARCH_TAB_MAIN",
        "forceUseInputKeyword": False,
        "plateform": "pc",
        "mainTab": True,
        "supportFlexFilter": True,
        "smartUIFilter": True,
        "extraFilterValue": extra,
        "userPositionJson": "{}",
    }


def _cookie_value(ctx, name: str) -> str:
    for cookie in ctx.cookies("https://www.goofish.com"):
        if cookie.get("name") == name and cookie.get("value"):
            return str(cookie["value"])
    return ""


def _native_search_request(ctx, payload: dict) -> dict:
    """使用当前登录态直接调用闲鱼 PC 搜索接口，返回原始 JSON。"""
    token_cookie = _cookie_value(ctx, "_m_h5_tk")
    if not token_cookie:
        raise RuntimeError("闲鱼搜索令牌缺失，请重新登录后再运行")
    token = token_cookie.split("_", 1)[0]
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    stamp = int(time.time() * 1000)
    sign = hashlib.md5(
        f"{token}&{stamp}&{MTOP_APP_KEY}&{data}".encode("utf-8")
    ).hexdigest()
    params = {
        "jsv": "2.7.2", "appKey": MTOP_APP_KEY, "t": str(stamp), "sign": sign,
        "v": "1.0", "type": "originaljson", "accountSite": "xianyu",
        "dataType": "json", "timeout": "20000", "api": SEARCH_API,
        "sessionOption": "AutoLoginOnly", "spm_cnt": "a21ybx.search.0.0",
    }
    response = ctx.request.post(
        MTOP_URL, params=params, form={"data": data},
        headers={"Referer": "https://www.goofish.com/search"}, timeout=20000)
    raw = response.json()
    ret = raw.get("ret") or []
    if not any(str(value).startswith("SUCCESS") for value in ret):
        raise RuntimeError(f"闲鱼原生搜索接口返回失败：{' / '.join(map(str, ret)) or response.status}")
    return raw


def _page_native_search_request(page, ctx, payload: dict) -> dict:
    """优先调用闲鱼页面自己的 mtop 封装，由网页按当前登录态完成签名。"""
    try:
        raw = page.evaluate(r"""async ({api, payload}) => {
          const mtop = window.lib && window.lib.mtop;
          if (!mtop || typeof mtop.request !== 'function') return null;
          return await mtop.request({
            api, v: '1.0', data: payload, type: 'POST', dataType: 'json',
            needLogin: false, needLoginPC: false,
            sessionOption: 'AutoLoginOnly', ecode: 0
          });
        }""", {"api": SEARCH_API, "payload": payload})
        if isinstance(raw, dict):
            ret = raw.get("ret") or []
            if any(str(value).startswith("SUCCESS") for value in ret):
                return raw
    except Exception:
        pass
    # 部分桌面 WebView 不暴露 window.lib，使用相同请求体走 H5 签名兜底。
    return _native_search_request(ctx, payload)


def _native_condition(node: object, title: str) -> str | None:
    """从搜索卡片的标签字段读取闲鱼原生9档成色，标题仅作为兜底。"""
    strings: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    strings.append(title)
    for label in CONDITION_LABELS:
        if any(label in value for value in strings):
            return label
    return guess_condition(title)


def _has_next_page(raw: dict) -> bool | None:
    info = (((raw or {}).get("data") or {}).get("resultInfo")) or {}
    if "hasNextPage" not in info:
        return None
    return bool(info.get("hasNextPage"))


def _reported_total(raw: dict) -> int | None:
    """读取闲鱼响应报告的总商品数（字段灰度兼容）。"""
    data = (raw or {}).get("data") or {}
    info = data.get("resultInfo") or {}
    for value in (info.get("totalCount"), info.get("totalResults"),
                  data.get("totalCount"), data.get("totalResults")):
        try:
            number = int(str(value))
        except (TypeError, ValueError):
            continue
        if number >= 0:
            return number
    return None


def _click_next_page(page) -> bool:
    """点击闲鱼 PC 搜索页真实的下一页按钮。

    2026 版搜索页使用 ``1/50`` 两侧按钮分页，滚动到底部不会再请求下一页。
    优先使用可访问属性，灰度页面缺少属性时再根据页码文字定位右侧按钮。
    """
    return bool(page.evaluate(r"""() => {
      const visible = el => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const labelled = [...document.querySelectorAll('button,[role="button"]')].find(el => {
        const label = `${el.getAttribute('aria-label') || ''} ${el.title || ''}`;
        return visible(el) && !el.disabled && /下一页|next/i.test(label);
      });
      if (labelled) { labelled.click(); return true; }

      const marker = [...document.querySelectorAll('span,div,p')].find(el =>
        visible(el) && /^\s*\d+\s*\/\s*\d+\s*$/.test(el.textContent || '') &&
        el.children.length <= 1
      );
      if (!marker) return false;
      const mr = marker.getBoundingClientRect();
      let root = marker.parentElement;
      for (let depth = 0; root && depth < 5; depth++, root = root.parentElement) {
        const candidates = [...root.querySelectorAll('button,[role="button"]')]
          .filter(el => visible(el) && !el.disabled &&
            el.getBoundingClientRect().left >= mr.right - 4)
          .sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
        if (candidates.length) { candidates[0].click(); return true; }
      }
      return false;
    }"""))


def _click_exact_text(page, text: str) -> bool:
    """点击页面上最小的可见精确文本节点，供闲鱼原生地区面板使用。"""
    return bool(page.evaluate(r"""target => {
      const norm = value => (value || '').replace(/\s+/g, ' ').trim();
      const visible = el => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const nodes = [...document.querySelectorAll('button,[role="button"],li,a,span,div')]
        .filter(el => visible(el) && norm(el.textContent) === norm(target))
        .sort((a, b) => {
          const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
          const ap = /^(BUTTON|A|LI)$/.test(a.tagName) || a.getAttribute('role') === 'button' ? 0 : 1;
          const bp = /^(BUTTON|A|LI)$/.test(b.tagName) || b.getAttribute('role') === 'button' ? 0 : 1;
          return ap - bp || ar.width * ar.height - br.width * br.height;
        });
      if (!nodes.length) return false;
      nodes[0].click();
      return true;
    }""", text))


def _click_location_text(page, text: str) -> bool:
    """地区名称兼容“杭州/杭州市”“上城/上城区”等常见写法。"""
    value = text.strip()
    variants = [value]
    for suffix in ("特别行政区", "自治区", "自治州", "地区", "城市", "市", "区", "县"):
        if value.endswith(suffix) and len(value) > len(suffix):
            variants.append(value[:-len(suffix)])
    for candidate in dict.fromkeys(variants):
        if _click_exact_text(page, candidate):
            return True
    return False


def _dom_item_ids(page) -> frozenset[str]:
    """读取当前页面卡片 ID；接口被缓存/复用时作为真实页面变化信号。"""
    try:
        values = page.evaluate(r"""() => [...document.querySelectorAll('a[href*="item"][href*="id="]')]
          .map(a => { try { return new URL(a.href, location.href).searchParams.get('id') || ''; }
                      catch (_) { return ''; } }).filter(Boolean)""") or []
        return frozenset(str(value) for value in values)
    except Exception:
        return frozenset()


def _wait_for_new_page(page, captured: list[dict], before: int, cancelled=None,
                       timeout_steps: int = 50,
                       before_dom: frozenset[str] | None = None) -> bool:
    for _ in range(timeout_steps):
        if cancelled and cancelled():
            return False
        page.wait_for_timeout(100)
        if len(captured) > before:
            return True
        current_dom = _dom_item_ids(page)
        if current_dom and (before_dom is None or current_dom != before_dom):
            return True
    return False


def _click_filter_apply(page) -> bool:
    """点击筛选面板底部的“查看N件宝贝/确定/应用筛选”。"""
    return bool(page.evaluate(r"""() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
      };
      const nodes = [...document.querySelectorAll('button,[role="button"],a')].filter(el => {
        const text = (el.textContent || '').replace(/\s+/g, '').trim();
        return visible(el) && (/查看\d*件?宝贝/.test(text) || /^(确定|应用筛选|查看全部)$/.test(text));
      });
      if (!nodes.length) return false;
      nodes[0].click();
      return true;
    }"""))


def _apply_native_price(page, watch: Watch, captured: list[dict],
                        captured_ids: list[frozenset[str]], cancelled=None) -> bool:
    """在闲鱼页面填写原生最低/最高价，让分页基于价格筛选后的结果。"""
    if watch.price_min is None and watch.price_max is None:
        return True
    previous = list(captured)
    previous_ids = list(captured_ids)
    previous_dom = _dom_item_ids(page)
    # 必须在操作前清空；旧版操作后清空，网络快时会把刚返回的新结果删掉。
    captured.clear()
    captured_ids.clear()
    changed = page.evaluate(r"""values => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
      };
      let inputs = [...document.querySelectorAll('input')].filter(el => visible(el) && (
        el.type === 'number' || /最低|最高|价格|¥|￥/.test(el.placeholder || '')
      ));
      if (inputs.length < 2) return false;
      inputs = inputs.slice(0, 2);
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      [values.min, values.max].forEach((value, index) => {
        if (value === null || value === undefined) return;
        setter.call(inputs[index], String(value));
        inputs[index].dispatchEvent(new Event('input', { bubbles: true }));
        inputs[index].dispatchEvent(new Event('change', { bubbles: true }));
      });
      inputs[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
      inputs[1].dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
      inputs[1].blur();
      return true;
    }""", {"min": watch.price_min, "max": watch.price_max})
    if not changed:
        captured[:] = previous
        captured_ids[:] = previous_ids
        return False
    if (_wait_for_new_page(page, captured, 0, cancelled, timeout_steps=50,
                           before_dom=previous_dom)
            or (_click_filter_apply(page)
                and _wait_for_new_page(page, captured, 0, cancelled,
                                       before_dom=previous_dom))):
        return True
    captured[:] = previous
    captured_ids[:] = previous_ids
    return False


def _apply_native_conditions(page, watch: Watch, captured: list[dict],
                             captured_ids: list[frozenset[str]], cancelled=None) -> bool:
    """尽量使用闲鱼原生成色筛选；页面版本不支持时仍由本地精确过滤兜底。"""
    if not watch.condition:
        return True
    previous = list(captured)
    previous_ids = list(captured_ids)
    previous_dom = _dom_item_ids(page)
    if not _click_exact_text(page, "筛选"):
        return False
    page.wait_for_timeout(250)
    captured.clear()
    captured_ids.clear()
    clicked = False
    for label in watch.condition:
        clicked = _click_exact_text(page, label) or clicked
    if not clicked:
        return False
    applied = _click_filter_apply(page)
    if applied and _wait_for_new_page(page, captured, 0, cancelled,
                                      before_dom=previous_dom):
        return True
    captured[:] = previous
    captured_ids[:] = previous_ids
    return False


def _apply_native_location(page, watch: Watch, captured: list[dict],
                           captured_ids: list[frozenset[str]], cancelled=None) -> bool:
    """使用闲鱼网页自身的区域筛选，支持城市和区县。

    只有最终地区选择产生了新的搜索结果才返回成功；避免设置杭州却继续展示全国结果。
    """
    province, city, district = normalize_region(watch.province, watch.city, watch.district)
    if not province and not city and not district:
        return True
    if not _click_exact_text(page, "区域"):
        return False
    page.wait_for_timeout(250)
    previous_dom = _dom_item_ids(page)
    captured.clear()
    captured_ids.clear()
    if province and not _click_location_text(page, province):
        return False
    if province:
        page.wait_for_timeout(150)
        # 省份点击可能产生一次中间请求，不能把“浙江全省”当成“杭州”。
        captured.clear()
        captured_ids.clear()
        previous_dom = _dom_item_ids(page)
    target = city or district
    if not _click_location_text(page, target):
        return False
    city_applied = _wait_for_new_page(page, captured, 0, cancelled, timeout_steps=50,
                                      before_dom=previous_dom)
    if district:
        # 城市选择后面板可能保持打开，也可能收起；两种页面都兼容。
        captured.clear()
        captured_ids.clear()
        previous_dom = _dom_item_ids(page)
        if not _click_location_text(page, district):
            if not _click_exact_text(page, "区域"):
                return False
            page.wait_for_timeout(200)
            if not _click_location_text(page, district):
                return False
        if (_wait_for_new_page(page, captured, 0, cancelled, timeout_steps=50,
                               before_dom=previous_dom)
                or (_click_filter_apply(page)
                    and _wait_for_new_page(page, captured, 0, cancelled,
                                           before_dom=previous_dom))):
            return True
        return False
    if city_applied:
        return True
    return bool(_click_filter_apply(page)
                and _wait_for_new_page(page, captured, 0, cancelled,
                                       before_dom=previous_dom))


def parse_search_json(raw: dict) -> list[Item]:
    out: list[Item] = []
    seen: set[str] = set()
    result_list = (((raw or {}).get("data") or {}).get("resultList")) or []
    for el in result_list:
        main = (((el or {}).get("data") or {}).get("item") or {}).get("main") or {}
        ex = main.get("exContent") or {}
        dp = ex.get("detailParams") or {}
        args = (main.get("clickParam") or {}).get("args") or {}
        target_url = str(main.get("targetUrl") or "")
        target_id = None
        if target_url:
            matched_id = re.search(r"(?:[?&]|%3F|%26)id(?:=|%3D)(\d+)", target_url, re.I)
            target_id = matched_id.group(1) if matched_id else None
        iid = ex.get("itemId") or dp.get("itemId") or args.get("item_id") or target_id
        title = ex.get("title") or dp.get("title")
        # 不同搜索卡片的价格字段并不统一；to_price 同时支持 "¥2.89万"。
        price = to_price(dp.get("soldPrice") or args.get("price") or args.get("displayPrice")
                         or ex.get("price") or dp.get("price") or ex.get("priceText"))
        if not iid or not title or price is None or str(iid) in seen:
            continue
        seen.add(str(iid))
        tag = str(args.get("tag") or "").lower()
        tagname = str(args.get("tagname") or "")
        area = ex.get("area")
        nick = ex.get("userNickName") or dp.get("userNick")
        sid = args.get("seller_id")
        pic = ex.get("picUrl")
        out.append(Item(
            item_id=str(iid),
            title=str(title),
            price=price,
            url=f"https://www.goofish.com/item?id={iid}",
            location=str(area) if isinstance(area, str) else None,
            seller_nick=str(nick) if nick else None,
            seller_id=str(sid) if sid else None,
            free_shipping=("freeship" in tag) or ("包邮" in tagname),
            condition=_native_condition(main, str(title)),
            pic_url=str(pic) if isinstance(pic, str) else None,
            publish_time=to_dt_ms(args.get("publishTime")),
            raw=main if isinstance(main, dict) else None,
        ))
    # 闲鱼会在同一页混用多种卡片结构。旧实现只要命中一条旧结构，就完全
    # 跳过新结构，造成网页几十条、程序只读到 1--4 条。始终合并递归解析结果。
    for item in items_from_json(raw):
        if item.item_id not in seen:
            seen.add(item.item_id)
            out.append(item)
    return out


def _items_from_dom(page) -> list[Item]:
    """接口结构灰度变化时，从当前网页已经渲染出的商品卡片兜底读取。

    这不是用页面按钮模拟筛选；只读取用户在闲鱼网页上本来就能看到的卡片，
    因此接口字段改名时也不会把整页误判为 0 件。
    """
    rows = page.evaluate(r"""() => {
      const out = [];
      const seen = new Set();
      for (const a of document.querySelectorAll('a[href*="/item?"][href*="id="]')) {
        let href = a.href || '';
        let id = '';
        try { id = new URL(href, location.href).searchParams.get('id') || ''; } catch (_) {}
        if (!id || seen.has(id)) continue;
        const root = a.closest('article,li,[class*="card"],[class*="item"]') || a;
        const text = (root.innerText || a.innerText || '').replace(/\s+/g, ' ').trim();
        const img = root.querySelector('img') || a.querySelector('img');
        const title = (a.getAttribute('title') || img?.alt || text || '').trim();
        const image = img?.src || img?.getAttribute('data-src') || null;
        out.push({id, href, text, title, image});
        seen.add(id);
      }
      return out;
    }""") or []
    out: list[Item] = []
    for row in rows:
        text = str(row.get("text") or "")
        # 卡片常把整数/小数拆成多个节点，innerText 合并后仍可稳定识别。
        m = re.search(r"[¥￥]\s*([0-9][0-9,.]*(?:\s*万)?)", text)
        if not m:
            continue
        price = to_price(m.group(1).replace(" ", ""))
        if price is None:
            continue
        title = str(row.get("title") or text)
        # title 属性缺失时，去掉价格之后的统计文案，至少保留完整卡片正文供关键词判断。
        if title == text:
            title = re.split(r"[¥￥]\s*[0-9]", text, maxsplit=1)[0].strip() or text
        out.append(Item(item_id=str(row["id"]), title=title, price=price,
                        url=str(row.get("href") or f"https://www.goofish.com/item?id={row['id']}"),
                        condition=_native_condition(row, title),
                        pic_url=str(row["image"]) if row.get("image") else None,
                        raw=row))
    return out


def search(ctx, watch: Watch, max_pages: int = 3, search_url: str = SEARCH_URL,
           start_page: int = 1, progress=None, cancelled=None) -> list[Item]:
    """在闲鱼已登录页面环境中调用原生 mtop 搜索，筛选和分页均由服务端执行。"""
    page = ctx.new_page()
    out: list[Item] = []
    seen: set[str] = set()
    try:
        query = " ".join(k.strip() for k in watch.keywords if k.strip())  # 多词块拼一条 query
        query = normalize_search_query(query)
        page.goto(f"{search_url}?q={quote(query)}", wait_until="domcontentloaded", timeout=15000)
        # 等待页面初始化登录态与 mtop 库；不要求搜索页一定重新发起首屏请求。
        for _ in range(100):
            if cancelled and cancelled():
                return []
            ready = bool(_cookie_value(ctx, "_m_h5_tk"))
            try:
                ready = ready or bool(page.evaluate(
                    "() => !!(window.lib && window.lib.mtop && window.lib.mtop.request)"))
            except Exception:
                pass
            if ready:
                break
            page.wait_for_timeout(100)
        start_page = max(1, int(start_page))
        max_pages = max(1, int(max_pages))
        for done, page_no in enumerate(
                range(start_page, start_page + max_pages), start=1):
            if cancelled and cancelled():
                break
            raw = _page_native_search_request(
                page, ctx, build_search_payload(query, watch, page_no))
            page_items = parse_search_json(raw)
            reported_total = _reported_total(raw)
            # 对于不足一页的搜索（如用户实测杭州 11 件），解析数必须与闲鱼报告
            # 的总数完全相等；否则宁可明确报错，也不能静默交付“只显示几件”。
            if page_no == 1 and reported_total is not None and reported_total <= 30:
                parsed_ids = {item.item_id for item in page_items}
                if len(parsed_ids) != reported_total:
                    raise RuntimeError(
                        f"闲鱼返回 {reported_total} 件，但软件只完整解析 {len(parsed_ids)} 件；"
                        "本轮已停止入库，避免显示不完整结果")
            for item in page_items:
                if item.item_id in seen:
                    continue
                seen.add(item.item_id)
                # 标记来源供诊断使用；规则层仍会剔除闲鱼“扩展推荐”里的错型号
                # 和配件，但不再用缺失的城市字段误删候选。
                item.raw = {**(item.raw or {}), "_xianyu_native_search": True}
                out.append(item)
            if progress:
                progress(done, max_pages)
            if done >= max_pages or _has_next_page(raw) is False:
                break
    finally:
        page.close()
    return out
