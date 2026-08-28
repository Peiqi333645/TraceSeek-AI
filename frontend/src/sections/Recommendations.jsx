import { useEffect, useState } from 'react'
import { Link } from '../router'
import { api } from '../api'
import { Card, Button, Badge, Spinner, EmptyState, Thumb, TimeMeta, Toggle } from '../components/ui'
import { yuan, fmtDate, fmtDateTime, ago } from '../util'

export default function Recommendations({ refreshKey, onToast, dropsToday = 0 }) {
  const [items, setItems] = useState(null)
  const [cfg, setCfg] = useState(null)
  const [watches, setWatches] = useState([])
  const [busy, setBusy] = useState({})
  const [muteOpen, setMuteOpen] = useState(null)
  // 默认展示闲鱼原生搜索得到的全部候选；AI 精选只能由用户主动切换，
  // 不能让“闲鱼返回 11 件”在推荐页看起来只剩寥寥几件。
  const [onlyPassed, setOnlyPassed] = useState(false)
  const [sort, setSort] = useState('newest')
  const [activeWatch, setActiveWatch] = useState(null)

  const load = () => Promise.all([api.recommendations('new'), api.config(), api.watches()]).then(([xs, c, ws]) => {
    setItems(xs)
    setCfg(c)
    setWatches(ws)
    if (!c.review_enabled) setOnlyPassed(false)
  })
  useEffect(() => {
    load()
  }, [refreshKey])

  const setAiEnabled = async (enabled) => {
    const next = { ...cfg, review_enabled: enabled, smtp_pass: null, review_api_token: null }
    const saved = await api.saveConfig(next)
    setCfg(saved)
    if (!enabled) setOnlyPassed(false)
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

  const enabledNames = new Set(watches.filter((w) => w.enabled).map((w) => w.name))
  const currentItems = items.filter((x) => enabledNames.has(x.watch_name))
  const passedCount = currentItems.filter((x) => x.rec_ok === true).length
  const filtered = onlyPassed ? currentItems.filter((x) => x.rec_ok === true) : currentItems
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
  const selectedWatch = order.includes(activeWatch) ? activeWatch : order[0]
  const selectedItems = selectedWatch ? byWatch[selectedWatch] : []

  return (
    <section>
      <h1 className="page-title">
        待审推荐 {shown.length > 0 && <span className="count">{shown.length}</span>}
        <Link className="drop-shortcut" to="/favorites">
          <i className="ti ti-trending-down" /> 今日降价 <b>{dropsToday}</b>
        </Link>
      </h1>
      <p className="page-sub">自动发现符合条件的新商品。AI精选只显示智能判断更符合要求的结果。</p>
      {currentItems.length > 0 && (
        <div className="rec-toolbar">
          <div className="rec-filter">
            <button disabled={!cfg.review_enabled} className={`seg${onlyPassed ? ' on' : ''}`} onClick={() => setOnlyPassed(true)}>
              AI精选 <b>{passedCount}</b>
            </button>
            <button className={`seg${!onlyPassed ? ' on' : ''}`} onClick={() => setOnlyPassed(false)}>
              所有候选 <b>{currentItems.length}</b>
            </button>
          </div>
          <div className="rec-tools">
            <Toggle checked={cfg.review_enabled} onChange={setAiEnabled} label="使用AI智能筛选" />
            <div className="sort-switch" role="group" aria-label="商品排序">
              <button className={sort === 'newest' ? 'on' : ''} onClick={() => setSort('newest')}><i className="ti ti-sparkles" />最新发现</button>
              <button className={sort === 'price-asc' ? 'on' : ''} onClick={() => setSort('price-asc')}><i className="ti ti-sort-ascending" />价格最低</button>
            </div>
          </div>
        </div>
      )}
      {shown.length === 0 ? (
        <EmptyState
          title={onlyPassed && currentItems.length > 0 ? '暂无AI精选商品' : '暂无新推荐'}
          sub={
            onlyPassed && currentItems.length > 0
              ? `还有 ${currentItems.length} 条候选商品，可点击「所有候选」查看`
              : '定时任务会按你的条件自动发现新商品'
          }
        />
      ) : (
        <div className="rec-group">
          <div className="watch-tabs" role="tablist" aria-label="商品分类">
            {order.map((name) => <button key={name} role="tab" aria-selected={selectedWatch === name} className={selectedWatch === name ? 'on' : ''} onClick={() => setActiveWatch(name)}>{name}<b>{byWatch[name].length}</b></button>)}
          </div>
          <div className="grid">{selectedItems.map(renderCard)}</div>
        </div>
      )}
    </section>
  )
}
