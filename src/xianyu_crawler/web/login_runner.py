"""在后台打开闲鱼登录页，把官方二维码显示到软件内供手机扫码。

登录成功后只保存浏览器会话。复用 runner 全局浏览器锁(与抓取串行)。
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from ..anti_detect import pick_profile
from ..config import Settings
from . import account, runner          # account: 头像缓存; runner: 复用全局浏览器锁 + STATE

LOGIN_URL = "https://www.goofish.com/login"
_TIMEOUT_S = 180               # 二维码等待上限
_QR_READY_TIMEOUT_S = 30       # 登录页打开后，最多等待二维码渲染的时间

# 前端轮询读这里: status=idle|starting|waiting|success|expired|failed|busy
STATE: dict = {"status": "idle", "qr": None, "message": "", "at": None}
_LOGIN_GENERATION = 0

# 只有这些账号级 Cookie 才能证明手机端已经完成确认登录。
# `_tb_token_` 等游客访问也会生成，不能用来判断登录成功。
# cookie2 在新版登录页的访客状态下也可能出现，不能证明账号已登录。
# 只使用明确包含账号身份的 Cookie，避免未扫码就被误判为成功。
_ACCOUNT_COOKIE_NAMES = {"unb", "tracknick", "lgc", "munb"}
_LOGGED_OUT_FILE = ".logged_out"


def _logged_out_path() -> Path:
    return Settings().data_dir / _LOGGED_OUT_FILE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _account() -> str | None:
    """从登录态 cookie 取闲鱼昵称(tracknick)显示在"已登录"处。只取昵称, 不含邮箱等隐私。"""
    f = Settings().data_dir / "storage_state.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    cks = {c.get("name"): c.get("value", "") for c in data.get("cookies", [])}
    raw = cks.get("tracknick") or cks.get("lgc") or cks.get("dnk") or cks.get("nick")
    if not raw:
        return None
    try:
        v = urllib.parse.unquote(urllib.parse.unquote(raw))
        if "\\u" in v:                          # 中文昵称为 \uXXXX 转义
            v = v.encode("latin-1", "ignore").decode("unicode_escape")
        return v or None
    except Exception:
        return raw or None


def has_session() -> bool:
    """本地是否保存了可用于闲鱼会话的 Cookie。

    不能只判断 storage_state.json 是否存在：未登录浏览器也能生成空状态文件，
    那会让前端误以为已经登录。
    """
    # 用户明确点过“退出账号”后，即使某个尚未结束的旧浏览器线程意外把
    # Cookie 文件写了回来，也必须保持未登录，直到下一次扫码真正成功。
    if _logged_out_path().exists():
        return False
    f = Settings().data_dir / "storage_state.json"
    if not f.exists():
        return False
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
    except Exception:
        return False
    names = {str(c.get("name", "")) for c in cookies}
    # 淘宝/闲鱼账号级 Cookie。真正有效性仍由每轮抓取访问首页验证。
    return bool(names & _ACCOUNT_COOKIE_NAMES)


def status() -> dict:
    """给前端: 登录流程状态 + 是否已有登录态 + 闲鱼昵称。"""
    authenticated = has_session()
    return {
        "status": STATE["status"],
        "qr": STATE["qr"],
        "message": STATE["message"],
        "has_state": authenticated,
        "authenticated": authenticated,
        "account": _account(),
        "avatar": account.avatar(),
    }


def start() -> dict:
    """启动扫码登录流程(后台线程)。已在进行中/抓取占用则不重入。"""
    if STATE["status"] in ("starting", "waiting", "scanned"):
        return {"status": STATE["status"]}
    if not runner._LOCK.acquire(blocking=False):
        return {"status": "busy", "message": "正在抓取，请稍后再试"}
    global _LOGIN_GENERATION
    _LOGIN_GENERATION += 1
    generation = _LOGIN_GENERATION
    # 明确退出后的重新登录必须从全新的无 Cookie 浏览器上下文开始。
    # 收藏、推荐和条件设置存放在数据库中，不会受此操作影响。
    if _logged_out_path().exists():
        try:
            (Settings().data_dir / "storage_state.json").unlink()
        except FileNotFoundError:
            pass
    STATE.update(status="starting", qr=None, message="正在生成登录二维码…", at=_now())
    threading.Thread(target=_run, args=(generation,), daemon=True).start()
    return {"status": "starting"}


def _logged_in(url: str) -> bool:
    u = url.lower()
    return "login" not in u and "passport" not in u and "sign" not in u


def _has_account_cookie(ctx) -> bool:
    """手机确认后页面可能不跳转；直接检查浏览器上下文中的账号 Cookie。"""
    try:
        names = {str(cookie.get("name", "")) for cookie in ctx.cookies()}
    except Exception:
        return False
    return bool(names & _ACCOUNT_COOKIE_NAMES)


# 二维码被手机扫过、等待手机端点「确认」时, passport iframe 里会出现这些字样
_SCAN_HINTS = ("扫描成功", "扫码成功", "请在手机", "确认登录", "登录确认", "已扫描", "请确认")


def _is_scanned(frame) -> bool:
    """iframe 文案出现"扫码成功/请在手机确认"→ 判定已扫码(给前端"登录中"反馈)。"""
    try:
        txt = frame.inner_text("body", timeout=800)
    except Exception:
        return False
    return any(h in txt for h in _SCAN_HINTS)


_QR_SELECTORS = (
    "[class*='qrcode' i] canvas",
    "[class*='qr-code' i] canvas",
    "[class*='qrcode' i] img",
    "[class*='qr-code' i] img",
    "img[alt*='二维码']",
    "img[alt*='扫码']",
    "img[src*='qrcode' i]",
    "img[src*='qrCode' i]",
    "canvas",
)


def _capture_qr(page) -> str | None:
    """从主页和所有 iframe 中捕获二维码。

    登录页会改变 iframe URL 和二维码标签，不能只依赖某个
    passport iframe 中的 canvas。
    """
    for frame in page.frames:
        for selector in _QR_SELECTORS:
            try:
                locators = frame.locator(selector)
                for index in range(min(locators.count(), 6)):
                    node = locators.nth(index)
                    if not node.is_visible(timeout=250):
                        continue
                    box = node.bounding_box(timeout=500)
                    if not box:
                        continue
                    width, height = float(box["width"]), float(box["height"])
                    if min(width, height) < 100 or max(width, height) > 520:
                        continue
                    if abs(width - height) > max(width, height) * 0.35:
                        continue
                    png = node.screenshot(type="png", timeout=2500)
                    return "data:image/png;base64," + base64.b64encode(png).decode()
            except Exception:
                continue
    return None


def _clear_browser_login(ctx, page) -> None:
    """清掉本轮浏览器里可能继承/自动恢复的旧账号凭据。"""
    try:
        ctx.clear_cookies()
    except Exception:
        pass
    try:
        page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    except Exception:
        pass


def logout() -> dict:
    """退出登录 / 换号: 删除 storage_state.json 并重置流程状态。"""
    global _LOGIN_GENERATION
    _LOGIN_GENERATION += 1       # 立即作废仍在运行的旧扫码线程，禁止它重新写入登录态
    f = Settings().data_dir / "storage_state.json"
    marker = Settings().data_dir / ".logout_marker"
    try:
        f.unlink()
    except FileNotFoundError:
        pass
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_now(), encoding="utf-8")
    # 权威的“用户已退出”标志。它能阻止任何残留/并发会话让软件自动登录。
    _logged_out_path().write_text(_now(), encoding="utf-8")
    account.clear()
    STATE.update(status="idle", qr=None, message="已退出登录", at=_now())
    return status()


def _run(generation: int) -> None:
    runner.STATE["running"] = True
    state_path = str(Settings().data_dir / "storage_state.json")
    prof = pick_profile()
    try:
        with sync_playwright() as p:
            # 浏览器仅在后台运行，用户无需安装或打开 Chrome。
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                locale="zh-CN", user_agent=prof["user_agent"], viewport=prof["viewport"])
            page = ctx.new_page()
            # 扫码窗口永远从无账号状态开始，不能继承上一位用户。
            _clear_browser_login(ctx, page)
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(700)
            STATE.update(status="waiting", message="正在读取官方登录二维码…")
            deadline = time.time() + _TIMEOUT_S
            qr_deadline = time.time() + _QR_READY_TIMEOUT_S
            ok = False
            scanned = False
            qr_was_shown = False
            stale_session_resets = 0
            while time.time() < deadline:
                if generation != _LOGIN_GENERATION:
                    STATE.update(status="idle", qr=None, message="已退出登录", at=_now())
                    return
                # 新版登录页在手机确认后可能仍停留在 /login。此时账号 Cookie
                # 已写入浏览器上下文，必须同时检测 Cookie，不能只等待 URL 跳转。
                # 登录页本身也可能提前写入 cookie2 等访客 Cookie。在二维码尚未
                # 展示前，不能用 Cookie 判断旧账号，否则会反复清理并误报失败。
                # 此阶段只在页面真的离开登录地址时，才视为旧账号自动恢复。
                auto_restored_old_account = _logged_in(page.url)
                # 安全约束：本轮没有先展示二维码，就不能把旧账号自动跳转
                # 当成登录成功。清掉旧会话并重新回到登录页。
                if auto_restored_old_account and not qr_was_shown:
                    stale_session_resets += 1
                    _clear_browser_login(ctx, page)
                    STATE.update(status="starting", qr=None,
                                 message="已清除上一个账号，正在生成新二维码…")
                    page.goto(
                        f"{LOGIN_URL}?forceLogin=true&_={int(time.time() * 1000)}",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    page.wait_for_timeout(700)
                    qr_deadline = time.time() + _QR_READY_TIMEOUT_S
                    if stale_session_resets >= 3:
                        STATE.update(status="failed", qr=None,
                                     message="旧账号会话未能清除，请退出软件后重试",
                                     at=_now())
                        return
                    continue
                # 二维码已经展示后，才允许通过账号 Cookie 判断手机确认成功。
                if qr_was_shown and (_logged_in(page.url) or _has_account_cookie(ctx)):
                    ok = True
                    break
                scanned_frame = next((f for f in page.frames if _is_scanned(f)), None)
                if not scanned and scanned_frame is not None:
                    scanned = True                     # 已扫码, 等手机端确认 → 给前端"登录中"
                    STATE.update(status="scanned", qr=None,
                                 message="扫码成功，请在手机点「确认登录」…")
                if not scanned and not STATE.get("qr"):
                    qr = _capture_qr(page)
                    if qr:
                        qr_was_shown = True
                        STATE.update(status="waiting", qr=qr,
                                     message="请使用手机闲鱼 App 扫码登录")
                    elif time.time() >= qr_deadline:
                        STATE.update(
                            status="failed",
                            qr=None,
                            message="未能读取登录二维码，请检查网络后点击重试",
                            at=_now(),
                        )
                        return
                page.wait_for_timeout(500)             # 更快反馈扫码与确认状态
            if ok:
                if generation != _LOGIN_GENERATION:
                    return
                Path(state_path).parent.mkdir(parents=True, exist_ok=True)
                ctx.storage_state(path=state_path)
                # 只有本轮全新扫码成功后，才允许恢复为已登录状态。
                try:
                    _logged_out_path().unlink()
                except FileNotFoundError:
                    pass
                STATE.update(status="success", qr=None, message="登录成功，已保存登录态", at=_now())
            else:
                STATE.update(status="expired", qr=None, message="二维码超时，请重试", at=_now())
            browser.close()
    except Exception as e:  # noqa: BLE001 - 后台作业, 记录不抛
        STATE.update(status="failed", qr=None, message=f"登录出错: {e}", at=_now())
    finally:
        runner.STATE["running"] = False
        runner._LOCK.release()
