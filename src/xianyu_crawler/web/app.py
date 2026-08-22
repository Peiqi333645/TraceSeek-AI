"""FastAPI 控制台后端。"""
import json
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import runtime, runner, dto, login_runner
from .. import service, notifier, review, billing
from ..config import Settings
from ..storage import repo

app = FastAPI(title="寻迹AI助手")

# 打包(PyInstaller)后静态资源在 _MEIPASS 下; 开发期就在包目录旁
if getattr(sys, "frozen", False):
    _STATIC_DIR = Path(getattr(sys, "_MEIPASS", ".")) / "xianyu_crawler" / "web" / "static"
else:
    _STATIC_DIR = Path(__file__).parent / "static"


def get_db():
    s = runtime.session()
    try:
        yield s
    finally:
        s.close()


def require_login() -> None:
    """所有业务操作的后端门禁；不能只依赖前端隐藏按钮。"""
    if not login_runner.has_session():
        raise HTTPException(401, "请先登录闲鱼账号")


# ---------- watches ----------
@app.get("/api/watches", response_model=list[dto.WatchOut])
def api_list_watches(_: None = Depends(require_login), s: Session = Depends(get_db)):
    return [dto.watchrow_to_out(w) for w in repo.list_watches(s)]


@app.post("/api/watches", response_model=dto.WatchOut)
def api_create_watch(body: dto.WatchIn, _: None = Depends(require_login), s: Session = Depends(get_db)):
    return dto.watchrow_to_out(repo.add_watch(s, **dto.watchin_to_fields(body)))


@app.put("/api/watches/{wid}", response_model=dto.WatchOut)
def api_update_watch(wid: int, body: dto.WatchIn, _: None = Depends(require_login), s: Session = Depends(get_db)):
    row = repo.update_watch(s, wid, **dto.watchin_to_fields(body))
    if row is None:
        raise HTTPException(404, "watch not found")
    return dto.watchrow_to_out(row)


@app.delete("/api/watches/{wid}")
def api_delete_watch(wid: int, _: None = Depends(require_login), s: Session = Depends(get_db)):
    repo.delete_watch(s, wid)
    return {"ok": True}


# ---------- config ----------
@app.get("/api/config", response_model=dto.ConfigOut)
def api_get_config(_: None = Depends(require_login), s: Session = Depends(get_db)):
    return dto.config_to_out(repo.get_config(s))


@app.put("/api/config", response_model=dto.ConfigOut)
def api_put_config(body: dto.ConfigIn, _: None = Depends(require_login), s: Session = Depends(get_db)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    cfg = repo.update_config(s, **fields)
    try:
        from . import scheduler
        scheduler.reschedule(cfg.schedule_minutes, cfg.favorites_minutes)
    except Exception:
        pass
    return dto.config_to_out(cfg)


@app.get("/api/billing/status")
def api_billing_status(_: None = Depends(require_login), s: Session = Depends(get_db)):
    cfg = repo.get_config(s)
    return billing.account(Settings(), cfg.billing_access_token)


@app.post("/api/billing/activate")
def api_billing_activate(body: dto.ActivationIn, _: None = Depends(require_login), s: Session = Depends(get_db)):
    result = billing.activate(Settings(), body.code)
    if result.get("ok"):
        token = str(result.pop("access_token"))
        account = str(result.get("account") or "")
        base = Settings().billing_base_url
        repo.update_config(
            s, billing_access_token=token, billing_account=account,
            review_base_url=base.rstrip("/") + "/v1" if base else None,
            review_api_token=token,
            review_model=str(result.get("model") or "smart-review"),
        )
    return result


@app.post("/api/test-email")
async def api_test_email(_: None = Depends(require_login), s: Session = Depends(get_db)):
    """用当前(已保存的)配置发一封测试邮件; 返回成功或错误原因。"""
    settings = service.effective_settings(repo.get_config(s))
    try:
        await run_in_threadpool(notifier.send_test, settings)
        return {"ok": True, "to": settings.notify_to}
    except Exception as e:  # noqa: BLE001 - 把失败原因回显给控制台
        return {"ok": False, "error": str(e)}


@app.post("/api/test-review")
async def api_test_review(_: None = Depends(require_login), s: Session = Depends(get_db)):
    """用当前(已保存的)配置 + 真实「AI 审核要求」做一次真实审核; 回显成功或错误原因。"""
    settings = service.effective_settings(repo.get_config(s))
    reqs = [w.requirement for w in repo.list_watches(s) if w.requirement]
    requirement = max(reqs, key=len) if reqs else None   # 用最长的要求, 最能压出推理模型的坑
    return await run_in_threadpool(review.test_review, settings, requirement)


# ---------- recommendations ----------
@app.get("/api/recommendations", response_model=list[dto.RecommendationOut])
def api_list_recs(status: str = "new", _: None = Depends(require_login), s: Session = Depends(get_db)):
    return [dto.itemrow_to_rec(r) for r in repo.list_recommendations(s, status)]


@app.post("/api/recommendations/review")
def api_rereview(_: None = Depends(require_login), s: Session = Depends(get_db)):
    """一键 AI 审核: 用当前 LLM 配置对已入库的待审推荐重新审核(补审之前没跑通的), 不重新抓取。

    同步 def → FastAPI 在线程池里跑, LLM 调用阻塞该 worker, 与 session 同线程, 安全。
    """
    settings = service.effective_settings(repo.get_config(s))
    return service.rereview_pending(s, settings)


@app.post("/api/recommendations/{item_id}/approve")
async def api_approve(item_id: str, _: None = Depends(require_login)):
    ok = await run_in_threadpool(runner.approve, item_id)
    return {"ok": ok}


@app.post("/api/recommendations/{item_id}/reject")
def api_reject(item_id: str, _: None = Depends(require_login), s: Session = Depends(get_db)):
    repo.set_rec_status(s, item_id, "rejected")
    return {"ok": True}


@app.post("/api/recommendations/{item_id}/mute")
def api_mute(item_id: str, days: int = 7, _: None = Depends(require_login), s: Session = Depends(get_db)):
    """近期不看: days=1/7 暂时隐藏(到期重现), days=0 永久不看。"""
    service.mute_recommendation(s, item_id, days)
    return {"ok": True}


# ---------- favorites + drops ----------
@app.get("/api/favorites", response_model=list[dto.FavoriteOut])
def api_favorites(_: None = Depends(require_login), s: Session = Depends(get_db)):
    return [dto.itemrow_to_fav(r) for r in repo.list_favorites(s)]


@app.get("/api/stats")
def api_stats(_: None = Depends(require_login), s: Session = Depends(get_db)):
    return repo.stats(s)


@app.get("/api/events")
def api_events(_: None = Depends(require_login), s: Session = Depends(get_db)):
    return [
        {"item_id": e.item_id, "type": e.type, "payload": json.loads(e.payload),
         "created_at": dto._iso(e.created_at)}   # 标 UTC, 前端才能转本地时区(与其它时间一致)
        for e in repo.recent_events(s)
    ]


# ---------- 扫码登录 ----------
@app.post("/api/login/start")
def api_login_start():
    """启动图形化扫码登录(后台开浏览器取二维码)。"""
    return login_runner.start()


@app.get("/api/login/status")
def api_login_status():
    """前端轮询: 登录状态 + 当前二维码(base64) + 是否已有登录态。"""
    return login_runner.status()


@app.post("/api/login/logout")
def api_login_logout():
    """退出登录 / 换号: 清除本地登录态。"""
    return login_runner.logout()


# ---------- run + status ----------
@app.post("/api/run")
def api_run(watch: str | None = None, _: None = Depends(require_login)):
    """watch=None → 全量; watch=条件名 → 只跑该条件。"""
    threading.Thread(target=runner.crawl, args=(watch,), daemon=True).start()
    return {"status": "queued", "scope": watch or "all"}


@app.get("/api/status")
def api_status(_: None = Depends(require_login), s: Session = Depends(get_db)):
    cfg = repo.get_config(s)
    return {
        "running": runner.STATE["running"],
        "last": runner.STATE["last"],
        "paused": cfg.paused,
        "schedule_minutes": cfg.schedule_minutes,
    }


# ---------- static SPA (前端构建产物, C4) ----------
if _STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        index = _STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(404)
