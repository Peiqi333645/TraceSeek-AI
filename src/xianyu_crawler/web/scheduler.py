"""进程内定时调度(APScheduler): 三个独立任务。

- crawl (schedule_minutes, 默认 15): 推荐抓取 + 死链核活 + 通知。
- favorites (favorites_minutes, 默认 10): 收藏刷新 + 降价通知。
- deep_search (秒级可配): 每轮向后搜索连续 5 页。

防重入: 每个 job max_instances=1 + coalesce; runner 还有全局锁兜底(两任务共用一把锁,
不会并发开浏览器)。暂停由各 runner 函数内部检查 AppConfig.paused 实现。
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import runner

_scheduler: BackgroundScheduler | None = None
_CRAWL_JOB = "crawl"
_FAV_JOB = "favorites"
_DEEP_JOB = "deep_search"


def start(crawl_minutes: float, favorites_minutes: float,
          deep_enabled: bool = False, deep_interval_seconds: float = 300) -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(runner.crawl, IntervalTrigger(minutes=max(0.5, crawl_minutes)),
                       id=_CRAWL_JOB, max_instances=1, coalesce=True)
    _scheduler.add_job(runner.refresh_favorites, IntervalTrigger(minutes=max(0.5, favorites_minutes)),
                       id=_FAV_JOB, max_instances=1, coalesce=True)
    _scheduler.add_job(runner.deep_search,
                       IntervalTrigger(seconds=max(1.0, deep_interval_seconds)),
                       id=_DEEP_JOB, max_instances=1, coalesce=True)
    _scheduler.start()
    if not deep_enabled:
        _scheduler.pause_job(_DEEP_JOB)


def reschedule(crawl_minutes: float, favorites_minutes: float,
               deep_enabled: bool = False, deep_interval_seconds: float = 300) -> None:
    if _scheduler is None:
        return
    _scheduler.reschedule_job(_CRAWL_JOB, trigger=IntervalTrigger(minutes=max(0.5, crawl_minutes)))
    _scheduler.reschedule_job(_FAV_JOB, trigger=IntervalTrigger(minutes=max(0.5, favorites_minutes)))
    _scheduler.reschedule_job(
        _DEEP_JOB, trigger=IntervalTrigger(seconds=max(1.0, deep_interval_seconds)))
    if deep_enabled:
        _scheduler.resume_job(_DEEP_JOB)
    else:
        _scheduler.pause_job(_DEEP_JOB)


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def is_running() -> bool:
    return _scheduler is not None and _scheduler.running
