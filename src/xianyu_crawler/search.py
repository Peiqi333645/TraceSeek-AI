"""搜索: 跑搜索页 → 拦截 mtop 搜索接口 JSON → 翻页加载 → 解析为 Item。

watch.keywords 是**一个**搜索词的若干词块, 用空格拼成一条 query 搜一次(不是逐词分搜)。
接口: mtop.taobao.idlemtopsearch.pc.search
商品: data.resultList[].data.item.main.exContent (+ detailParams / clickParam.args)
分页: 点击网页 ``1/50`` 右侧下一页按钮，并校验每页商品 ID 确实变化。
"""
from __future__ import annotations

import re
from urllib.parse import quote

from .config import Watch
from .models import Item
from .parsing import to_price, guess_condition, to_dt_ms, items_from_json
SEARCH_URL = "https://www.goofish.com/search"
SEARCH_API = "mtop.taobao.idlemtopsearch.pc.search"
CONDITION_LABELS = (
    "包装脏污/变形/破损", "轻微划痕/脏污", "轻微使用痕迹", "明显使用痕迹",
    "仅拆封未使用", "几乎全新", "无原包装", "官翻机", "全新",
)


def normalize_search_query(query: str) -> str:
    """补齐网页端具备、直接接口搜索不具备的少量确定性纠错。"""
    return query.replace("康时泰", "康泰时")


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


def _wait_for_new_page(page, captured: list[dict], before: int, cancelled=None,
                       timeout_steps: int = 50) -> bool:
    for _ in range(timeout_steps):
        if cancelled and cancelled():
            return False
        page.wait_for_timeout(100)
        if len(captured) > before:
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
        return False
    captured.clear()
    captured_ids.clear()
    if (_wait_for_new_page(page, captured, 0, cancelled, timeout_steps=15)
            or (_click_filter_apply(page)
                and _wait_for_new_page(page, captured, 0, cancelled))):
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
    if not _click_exact_text(page, "筛选"):
        return False
    page.wait_for_timeout(250)
    clicked = False
    for label in watch.condition:
        clicked = _click_exact_text(page, label) or clicked
    if not clicked:
        return False
    captured.clear()
    captured_ids.clear()
    applied = _click_filter_apply(page)
    if applied and _wait_for_new_page(page, captured, 0, cancelled):
        return True
    captured[:] = previous
    captured_ids[:] = previous_ids
    return False


def _apply_native_location(page, watch: Watch, captured: list[dict],
                           captured_ids: list[frozenset[str]], cancelled=None) -> bool:
    """使用闲鱼网页自身的区域筛选，支持城市和区县。

    只有最终地区选择产生了新的搜索结果才返回成功；避免设置杭州却继续展示全国结果。
    """
    city = (watch.city or "").strip()
    district = (watch.district or "").strip()
    if not city and not district:
        return True
    if not _click_exact_text(page, "区域"):
        return False
    page.wait_for_timeout(250)
    captured.clear()
    captured_ids.clear()
    target = city or district
    if not _click_location_text(page, target):
        return False
    city_applied = _wait_for_new_page(page, captured, 0, cancelled, timeout_steps=8)
    if district:
        # 城市选择后面板可能保持打开，也可能收起；两种页面都兼容。
        captured.clear()
        captured_ids.clear()
        if not _click_location_text(page, district):
            if not _click_exact_text(page, "区域"):
                return False
            page.wait_for_timeout(200)
            if not _click_location_text(page, district):
                return False
        if (_wait_for_new_page(page, captured, 0, cancelled, timeout_steps=8)
                or (_click_filter_apply(page)
                    and _wait_for_new_page(page, captured, 0, cancelled))):
            return True
        return False
    if city_applied:
        return True
    return bool(_click_filter_apply(page)
                and _wait_for_new_page(page, captured, 0, cancelled))


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
    """搜索连续页面。

    ``start_page=1, max_pages=5`` 读取 1–5 页；``start_page=6`` 读取 6–10 页。
    闲鱼网页使用滚动懒加载，因此深页仍需从顶部滚动到目标页，但只解析目标区间。
    """
    captured: list[dict] = []
    captured_ids: list[frozenset[str]] = []
    page = ctx.new_page()

    def _on_response(resp) -> None:
        # 不要求 API 名后必须紧跟斜杠：闲鱼灰度域名/版本曾出现 /1.0/ 与 ? 两种形式。
        if SEARCH_API in resp.url.lower():
            try:
                raw = resp.json()
                ids = frozenset(it.item_id for it in parse_search_json(raw))
                # 同一页可能因组件刷新重复请求。只有包含商品且商品集合发生变化的
                # 响应才算成功翻到新页，避免把第一页重复计算成 2–5 页。
                if ids and (not captured_ids or ids != captured_ids[-1]):
                    captured.append(raw)
                    captured_ids.append(ids)
            except Exception:
                pass

    page.on("response", _on_response)
    try:
        query = " ".join(k.strip() for k in watch.keywords if k.strip())  # 多词块拼一条 query
        query = normalize_search_query(query)
        page.goto(f"{search_url}?q={quote(query)}", wait_until="domcontentloaded", timeout=15000)
        # 等到接口或页面商品卡片真正出现。旧版只等 5 秒，慢网会直接得到空列表。
        for _ in range(150):
            if captured:
                break
            if cancelled and cancelled():
                return []
            page.wait_for_timeout(100)
        # 不能再依赖“区域/筛选”按钮的 DOM 结构。按钮改版时旧代码会抛异常并
        # 丢弃已经抓到的全部结果，甚至用户清空地区后仍可能卡在旧面板状态。
        # 先可靠收集关键词结果，价格和成色统一由 filter.matches 处理；地区字段
        # 缢失时保留候选，不把真实商品误删。
        dom_pages: list[list[Item]] = [_items_from_dom(page)]
        n = len(captured)
        start_page = max(1, int(start_page))
        max_pages = max(1, int(max_pages))
        end_page = start_page + max_pages - 1
        if progress:
            progress(1, end_page)
        for page_no in range(2, end_page + 1):
            if cancelled and cancelled():
                break
            # 灰度接口有时不返回 hasNextPage；缺字段时仍尝试点击网页分页按钮。
            if captured and _has_next_page(captured[-1]) is False:
                break
            # 新版网页必须点击“下一页”，滚动不会翻页。最多重试一次；并以新的
            # 商品 ID 集合为成功标准，而不是只看网络请求数量。
            advanced = False
            before_dom_ids = frozenset(it.item_id for it in dom_pages[-1])
            next_dom: list[Item] = []
            for _attempt in range(2):
                if not _click_next_page(page):
                    break
                for _step in range(50):
                    if cancelled and cancelled():
                        break
                    page.wait_for_timeout(100)
                    if len(captured) > n:
                        advanced = True
                        break
                    # 即使搜索接口结构暂时无法解析，也用网页卡片 ID 确认翻页成功。
                    if _step % 5 == 4:
                        candidate_dom = _items_from_dom(page)
                        candidate_ids = frozenset(it.item_id for it in candidate_dom)
                        if candidate_ids and candidate_ids != before_dom_ids:
                            next_dom = candidate_dom
                            advanced = True
                            break
                if advanced:
                    break
            if not advanced:             # 页码未变化或只返回重复第一页 → 停
                break
            n = len(captured)
            dom_pages.append(next_dom or _items_from_dom(page))
            if progress:
                progress(page_no, end_page)
    finally:
        page.close()

    out: list[Item] = []
    seen: set[str] = set()
    for raw in captured[start_page - 1:start_page - 1 + max_pages]:
        for it in parse_search_json(raw):
            if it.item_id not in seen:
                seen.add(it.item_id)
                out.append(it)
    # API 解析与 DOM 兜底取并集，不能因为 API 只识别出少数旧卡片就丢掉网页卡片。
    for page_items in dom_pages[start_page - 1:start_page - 1 + max_pages]:
        for it in page_items:
            if it.item_id not in seen:
                seen.add(it.item_id)
                out.append(it)
    return out
