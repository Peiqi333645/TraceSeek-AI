"""打开闲鱼官方登录窗口，允许用户选择扫码、短信或账号方式。

登录成功后只保存浏览器会话，不读取或保存用户密码。复用 runner 全局浏览器锁
(与抓取串行)。
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

# 前端轮询读这里: status=idle|starting|waiting|success|expired|failed|busy
STATE: dict = {"status": "idle", "qr": None, "message": "", "at": None}
_LOGIN_GENERATION = 0


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
    f = Settings().data_dir / "storage_state.json"
    if not f.exists():
        return False
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
    except Exception:
        return False
    names = {str(c.get("name", "")) for c in cookies}
    # 淘宝/闲鱼常见登录 Cookie。命中任意一个只代表有已保存会话，真正有效性
    # 仍由每轮抓取访问首页验证。
    return bool(names & {"cookie2", "unb", "tracknick", "lgc", "_tb_token_", "munb"})


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
    if STATE["status"] in ("starting", "waiting"):
        return {"status": STATE["status"]}
    if not runner._LOCK.acquire(blocking=False):
        return {"status": "busy", "message": "正在抓取，请稍后再试"}
    global _LOGIN_GENERATION
    _LOGIN_GENERATION += 1
    generation = _LOGIN_GENERATION
    STATE.update(status="starting", qr=None, message="正在打开闲鱼官方登录窗口…", at=_now())
    threading.Thread(target=_run, args=(generation,), daemon=True).start()
    return {"status": "starting"}


def _logged_in(url: str) -> bool:
    u = url.lower()
    return "login" not in u and "passport" not in u and "sign" not in u


# 二维码被手机扫过、等待手机端点「确认」时, passport iframe 里会出现这些字样
_SCAN_HINTS = ("扫描成功", "扫码成功", "请在手机", "确认登录", "登录确认", "已扫描", "请确认")


def _is_scanned(frame) -> bool:
    """iframe 文案出现"扫码成功/请在手机确认"→ 判定已扫码(给前端"登录中"反馈)。"""
    try:
        txt = frame.inner_text("body", timeout=800)
    except Exception:
        return False
    return any(h in txt for h in _SCAN_HINTS)


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
    account.clear()
    STATE.update(status="idle", qr=None, message="已退出登录", at=_now())
    return status()


def _run(generation: int) -> None:
    runner.STATE["running"] = True
    state_path = str(Settings().data_dir / "storage_state.json")
    prof = pick_profile()
    try:
        with sync_playwright() as p:
            # 可见的官方登录页会展示当前可用的扫码、短信和账号方式。
            # 具体选项由闲鱼官方决定，软件不接触用户密码。
            browser = p.chromium.launch(headless=False)
            ctx = browser.new_context(
                locale="zh-CN", user_agent=prof["user_agent"], viewport=prof["viewport"])
            page = ctx.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(700)
            STATE.update(status="waiting", message="请在弹出的闲鱼官方窗口选择登录方式")
            deadline = time.time() + _TIMEOUT_S
            ok = False
            scanned = False
            while time.time() < deadline:
                if generation != _LOGIN_GENERATION:
                    STATE.update(status="idle", qr=None, message="已退出登录", at=_now())
                    return
                if _logged_in(page.url):
                    ok = True
                    break
                frame = next((f for f in page.frames
                              if "mini_login" in f.url or "passport" in f.url), None)
                if not scanned and frame is not None and _is_scanned(frame):
                    scanned = True                     # 已扫码, 等手机端确认 → 给前端"登录中"
                    STATE.update(status="scanned", qr=None,
                                 message="扫码成功，请在手机点「确认登录」…")
                if not scanned and frame is not None:
                    try:                               # 截二维码(passport iframe 里的 canvas)
                        png = frame.locator("canvas").first.screenshot(timeout=3000)
                        STATE["qr"] = "data:image/png;base64," + base64.b64encode(png).decode()
                    except Exception:
                        pass                           # 二维码暂不可用/刷新中, 下轮再试
                page.wait_for_timeout(500)             # 更快反馈扫码与确认状态
            if ok:
                if generation != _LOGIN_GENERATION:
                    return
                Path(state_path).parent.mkdir(parents=True, exist_ok=True)
                ctx.storage_state(path=state_path)
                STATE.update(status="success", qr=None, message="登录成功，已保存登录态", at=_now())
            else:
                STATE.update(status="expired", qr=None, message="二维码超时，请重试", at=_now())
            browser.close()
    except Exception as e:  # noqa: BLE001 - 后台作业, 记录不抛
        STATE.update(status="failed", qr=None, message=f"登录出错: {e}", at=_now())
    finally:
        runner.STATE["running"] = False
        runner._LOCK.release()
