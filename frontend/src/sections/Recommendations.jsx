import { useEffect, useState } from 'react'
import { Link } from '../router'
import { api } from '../api'
import { Card, Button, Badge, Spinner, EmptyState, Thumb, TimeMeta, Toggle } from '../components/ui'
import { yuan, fmtDate, fmtDateTime, ago } from '../util'

export default function Recommendations({ refreshKey, onToast, dropsToday = 0 }) {
  const [items, setItems] = useState(null)
  const [cfg, setCfg] = useState(null)
  const [busy, setBusy] = useState({})
  const [muteOpen, setMuteOpen] = useState(null)
  const [onlyPassed, setOnlyPassed] = useState(true)
  const [sort, setSort] = useState('newest')

  const load = () => Promise.all([api.recommendations('new'), api.config()]).then(([xs, c]) => {
    setItems(xs)
    setCfg(c)
    if (!c.review_enabled) setOnlyPassed(false)
  })
  useEffect(() => {
    load()
  }, [refreshKey])

  const setAiEnabled = async (enabled) => {
    const next = { ...cfg, review_enabled: enabled, smtp_pass: null, review_api_token: null }
    const saved = await api.saveConfig(next)
    setCfg(saved)
    setOnlyPassed(enabled)
    onToast?.(enabled ? '已开启AI智能筛选' : '已关闭AI筛选，将显示所有候选商品')
  }

  const act = async (id, fn) => {
    setBusy((b) => ({ ...b, [id]: true }))
    try {
      const r = await fn(id)
      if (r && r.ok === false) {                 // 收藏没真成功 → 保留卡片 + 提示, 不再假装成功
        onToast?.('收藏没成功（可能遇到验证或网络波动），卡片已保留，可稍后重试')
        return
      }
      setItems((xs) => xs.filter((x) => x.item_id !== id))
    } finally {
      setBusy((b) => ({ ...b, [id]: false }))
    }
  }

  const mute = (id, days) => {
    setMuteOpen(null)
    act(id, () => api.mute(id, days))
  }

  const renderCard = (it) => {
    const failed = it.rec_ok === false
    return (
    <Card key={it.item_id} className={`rec${it.dead ? ' dead' : ''}${failed ? ' failed' : ''}`}>
      <Thumb url={it.pic_url} dead={it.dead} deadReason={it.dead_reason} />
      <div className="rec-body">
        <a className="rec-title" href={it.url} target="_blank" rel="noreferrer">
          {it.title}
        </a>
        <div className="rec-price">{yuan(it.price)}</div>
        <div className="rec-meta">
          {it.location && <span>{it.location}</span>}
          {it.condition && <span>{it.condition}</span>}
          {it.free_shipping && <Badge>包邮</Badge>}
        </div>
        {(it.browse_count != null || it.want_count != null || it.collect_count != null) && (
          <div className="rec-stats">
            {it.browse_count != null && <span title="浏览次数">👁 浏览 {it.browse_count}</span>}
            {it.want_count != null && <span title="想要次数">🙋 想要 {it.want_count}</span>}
            {it.collect_count != null && <span title="收藏次数">⭐ 收藏 {it.collect_count}</span>}
          </div>
        )}
        {it.reason && (
          <div className={`rec-reason${failed ? ' rejected' : ''}`}>
            <span className="rec-reason-tag">{failed ? '未通过' : 'AI'}</span>
            <span>{it.reason}</span>
          </div>
        )}
        <TimeMeta
          items={[
            ['上架', ago(it.publish_time)],
            ['推荐', fmtDateTime(it.rec_created_at)],
            ['调价', fmtDate(it.price_changed_at)],
          ]}
        />
        <div className="rec-actions">
          {!it.dead && (
            <Button disabled={busy[it.item_id]} onClick={() => act(it.item_id, api.approve)}>
              {busy[it.item_id] ? '收藏中…' : '收藏'}
            </Button>
          )}
          <Button
            variant="ghost"
            disabled={busy[it.item_id]}
            onClick={() => act(it.item_id, api.reject)}
          >
            {it.dead ? '移除' : '忽略'}
          </Button>
        </div>
        {!it.dead && (
          <div className="mute-row">
            <button
              className="mute-trigger"
              disabled={busy[it.item_id]}
              onClick={() => setMuteOpen(muteOpen === it.item_id ? null : it.item_id)}
            >
              近期不看 ▾
            </button>
            {muteOpen === it.item_id && (
              <div className="mute-menu">
                <button onClick={() => mute(it.item_id, 1)}>1 天内不看</button>
                <button onClick={() => mute(it.item_id, 7)}>7 天内不看</button>
                <button onClick={() => mute(it.item_id, 0)}>永远不看</button>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
    )
  }

  if (items === null || cfg === null) return <Spinner />

  const passedCount = items.filter((x) => x.rec_ok === true).length
  const filtered = onlyPassed ? items.filter((x) => x.rec_ok === true) : items
  const shown = [...filtered].sort((a, b) => {
    if (sort === 'price-asc') return Number(a.price || 0) - Number(b.price || 0)
    return String(b.rec_created_at || '').localeCompare(String(a.rec_created_at || ''))
  })

  // 按监控条件(watch)分组, 保持原有顺序(死链末尾 / 新推荐在前)
  const order = []
  const byWatch = {}
  for (const it of shown) {
    const k = it.watch_name || '未分组'
    if (!byWatch[k]) {
      byWatch[k] = []
      order.push(k)
    }
    byWatch[k].push(it)
  }

  return (
    <section>
      <h1 className="page-title">
        待审推荐 {shown.length > 0 && <span className="count">{shown.length}</span>}
        <Link className="drop-shortcut" to="/favorites">
          <i className="ti ti-trending-down" /> 今日降价 <b>{dropsToday}</b>
        </Link>
      </h1>
      <p className="page-sub">自动发现符合条件的新商品。AI精选只显示智能判断更符合要求的结果。</p>
      {items.length > 0 && (
        <div className="rec-toolbar">
          <div className="rec-filter">
            <button disabled={!cfg.review_enabled} className={`seg${onlyPassed ? ' on' : ''}`} onClick={() => setOnlyPassed(true)}>
              AI精选 <b>{passedCount}</b>
            </button>
            <button className={`seg${!onlyPassed ? ' on' : ''}`} onClick={() => setOnlyPassed(false)}>
              所有候选 <b>{items.length}</b>
            </button>
          </div>
          <div className="rec-tools">
            <Toggle checked={cfg.review_enabled} onChange={setAiEnabled} label="使用AI智能筛选" />
            <label className="sort-control" title="商品排序">
              <i className="ti ti-arrows-sort" />
              <select className="sort-select" value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="newest">最新发现</option>
                <option value="price-asc">价格从低到高</option>
              </select>
              <i className="ti ti-chevron-down" />
            </label>
          </div>
        </div>
      )}
      {shown.length === 0 ? (
        <EmptyState
          title={onlyPassed && items.length > 0 ? '暂无AI精选商品' : '暂无新推荐'}
          sub={
            onlyPassed && items.length > 0
              ? `还有 ${items.length} 条候选商品，可点击「所有候选」查看`
              : '定时任务会按你的条件自动发现新商品'
          }
        />
      ) : (
        order.map((name) => (
          <div key={name} className="rec-group">
            <div className="rec-group-head">
              <span className="rec-group-name">{name}</span>
              <span className="rec-group-count">{byWatch[name].length}</span>
            </div>
            <div className="grid">{byWatch[name].map(renderCard)}</div>
          </div>
        ))
      )}
    </section>
  )
}
