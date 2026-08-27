"""搜索: 跑搜索页 → 拦截 mtop 搜索接口 JSON → 翻页加载 → 解析为 Item。

watch.keywords 是**一个**搜索词的若干词块, 用空格拼成一条 query 搜一次(不是逐词分搜)。
接口: mtop.taobao.idlemtopsearch.pc.search
商品: data.resultList[].data.item.main.exContent (+ detailParams / clickParam.args)
分页: 点击网页 ``1/50`` 右侧下一页按钮，并校验每页商品 ID 确实变化。
"""
from __future__ import annotations

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


def parse_search_json(raw: dict) -> list[Item]:
    out: list[Item] = []
    seen: set[str] = set()
    result_list = (((raw or {}).get("data") or {}).get("resultList")) or []
    for el in result_list:
        main = (((el or {}).get("data") or {}).get("item") or {}).get("main") or {}
        ex = main.get("exContent") or {}
        dp = ex.get("detailParams") or {}
        args = (main.get("clickParam") or {}).get("args") or {}
        iid = ex.get("itemId") or dp.get("itemId") or args.get("item_id")
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
    # 闲鱼会灰度调整搜索卡片层级。显式结构完全没命中时，再用防御式递归
    # 解析常见 itemId/title/price 节点，避免网页搜得到而客户端得到 0 条。
    if not out:
        return items_from_json(raw)
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
        if f"{SEARCH_API}/" in resp.url:
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
        # 不再固定空等 4 秒：接口一返回就继续，慢网最多等 3.5 秒。
        for _ in range(50):
            if captured:
                break
            if cancelled and cancelled():
                return []
            page.wait_for_timeout(100)
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
                if advanced:
                    break
            if not advanced:             # 页码未变化或只返回重复第一页 → 停
                break
            n = len(captured)
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
    return out
