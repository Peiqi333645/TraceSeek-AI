import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api } from './api'
import { yuan, fmtDateTime } from './util'
import Recommendations from './sections/Recommendations'
import Drops from './sections/Drops'
import Watches from './sections/Watches'
import Settings from './sections/Settings'

const NAV = [
  ['/recommendations', '推荐', 'ti-sparkles', 'pending'],
  ['/favorites', '收藏', 'ti-bookmark', 'favorites'],
  ['/watches', '条件', 'ti-target', 'watches'],
  ['/settings', '设置', 'ti-settings', null],
]

// 实时事件按类型分 tab(全部 + 各事件类型)
const EVENT_TABS = [
  { key: 'all', label: '全部', types: null },
  { key: 'new_recommendation', label: '新推荐', types: ['new_recommendation'] },
  { key: 'price_drop', label: '降价', types: ['price_drop'] },
  { key: 'sold', label: '售出', types: ['sold'] },
]

const ZERO = { pending: 0, passed: 0, watches: 0, favorites: 0, dead: 0, drops_today: 0 }

function EventRow({ e }) {
  const p = e.payload || {}
  let warn = false
  let icon = 'ti-bell'
  let main = e.type
  let sub = ''
  if (e.type === 'price_drop') {
    warn = true
    icon = 'ti-trending-down'
    main = (
      <>
        <b>降价 ¥{Math.round(p.drop_abs || 0).toLocaleString('zh-CN')}</b> · {p.title || ''}
      </>
    )
    sub = p.prev_price ? `${yuan(p.prev_price)} → ${yuan(p.curr_price)}` : p.curr_price ? yuan(p.curr_price) : ''
  } else if (e.type === 'new_recommendation') {
    icon = 'ti-sparkles'
    main = (
      <>
        发现新推荐 · <b>{p.title || ''}</b>
      </>
    )
    sub = p.watch ? `条件 ${p.watch}` : p.price ? yuan(p.price) : ''
  } else if (e.type === 'sold') {
    warn = true
    icon = 'ti-circle-x'
    main = (
      <>
        已售出 / 下架 · <b>{p.title || ''}</b>
      </>
    )
    sub = p.reason || ''
  } else if (e.type === 'favorited') {
    icon = 'ti-bookmark'
    main = (
      <>
        已收藏 · <b>{p.title || ''}</b>
      </>
    )
    sub = '加入收藏监控'
  }
  const open = () => p.url && window.open(p.url, '_blank', 'noreferrer')
  return (
    <div className={'ev' + (warn ? ' warn' : '')} onClick={open}>
      <div className="ic">
        <i className={'ti ' + icon} />
      </div>
      <div>
        <div className="tx">{main}</div>
        <div className="et">
          {fmtDateTime(e.created_at)}
          {sub && ` · ${sub}`}
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('xy-side') === '1')
  const [status, setStatus] = useState(null)
  const [stats, setStats] = useState(ZERO)
  const [events, setEvents] = useState(null)
  const [login, setLogin] = useState({ has_state: false, authenticated: false, status: 'idle' })
  const [toast, setToast] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [railOpen, setRailOpen] = useState(() => localStorage.getItem('xy-rail') !== '0')
  const [eventTab, setEventTab] = useState('all')
  const [watchList, setWatchList] = useState([])
  const [runMenu, setRunMenu] = useState(false)
  const wasRunning = useRef(false)

  const toggleSide = () => {
    setCollapsed((c) => {
      localStorage.setItem('xy-side', c ? '0' : '1')
      return !c
    })
  }
  const toggleRail = () => {
    setRailOpen((o) => {
      localStorage.setItem('xy-rail', o ? '0' : '1')
      return !o
    })
  }

  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(null), 4500)
  }

  const poll = async () => {
    try {
      const lg = await api.loginStatus()
      setLogin(lg)
      if (!lg.authenticated) {
        setStatus(null)
        setStats(ZERO)
        setEvents([])
        setWatchList([])
        wasRunning.current = false
        return
      }
      const [st, sg, ev] = await Promise.all([api.status(), api.stats(), api.events()])
      setStatus(st)
      setStats(sg)
      setEvents(ev)
      if (wasRunning.current && !st.running) {
        setRefreshKey((k) => k + 1)
        if (st.last?.error) showToast(`抓取出错：${st.last.error}`)
        else if (st.last)
          showToast(`本轮完成：新推荐 ${st.last.recommendations ?? 0} · 降价 ${st.last.drops ?? 0}`)
      }
      wasRunning.current = st.running
    } catch {
      /* 服务未就绪, 忽略 */
    }
  }

  useEffect(() => {
    poll()
    const t = setInterval(poll, 2500)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (login.authenticated) api.watches().then(setWatchList).catch(() => {})
  }, [refreshKey, login.authenticated])

  const run = async (watch) => {
    if (!login.authenticated) {
      showToast('请先登录闲鱼账号')
      return
    }
    setRunMenu(false)
    wasRunning.current = true
    setStatus((current) => ({ ...(current || {}), running: true }))
    await api.run(watch)
    showToast(watch ? `已触发「${watch}」抓取…` : '已触发全部抓取，约 30–60 秒，完成后自动刷新…')
    poll()
  }

  const running = status?.running
  const loggedIn = !!login.authenticated

  const startLogin = async () => {
    try {
      const next = await api.loginStart()
      setLogin((current) => ({ ...current, ...next }))
      if (next.message) showToast(next.message)
      poll()
    } catch {
      showToast('登录窗口打开失败，请重试')
    }
  }

  const activeTab = EVENT_TABS.find((t) => t.key === eventTab) || EVENT_TABS[0]
  const shownEvents =
    events === null ? null : activeTab.types ? events.filter((e) => activeTab.types.includes(e.type)) : events

  return (
    <div id="app" data-s="premium" data-auth={loggedIn ? '1' : '0'} data-collapsed={collapsed ? '1' : '0'} data-rail={railOpen ? '1' : '0'}>
      {/* 顶栏 */}
      <div className="top">
        <div className="logo">
          <img className="brand-icon" src="/brand-icon.png" alt="" />
          寻迹AI助手
        </div>
        <div className="grow" />
        <div className="live">
          <span className={'pulse' + (running ? ' on' : '')} />
          {running ? '正在更新…' : loggedIn ? '运行正常' : '请先登录'}
        </div>
        <button
          className={'icon-btn' + (railOpen ? ' on' : '')}
          title={railOpen ? '收起实时事件栏' : '展开实时事件栏'}
          onClick={toggleRail}
        >
          <i className="ti ti-bell" />
        </button>
        <div className="run-wrap">
          <button className="run" disabled={running || !loggedIn} onClick={() => setRunMenu((o) => !o)}>
            <i className="ti ti-player-play" />
            立即运行
            <i className="ti ti-chevron-down" style={{ fontSize: 14 }} />
          </button>
          {runMenu && (
            <>
              <div className="menu-backdrop" onClick={() => setRunMenu(false)} />
              <div className="run-menu">
                <button onClick={() => run(null)}>
                  <i className="ti ti-player-play" />
                  运行全部条件
                </button>
                {watchList.length > 0 && <div className="run-sep" />}
                {watchList.map((w) => (
                  <button key={w.id} onClick={() => run(w.name)} title={(w.keywords || []).join(' ')}>
                    <i className="ti ti-target" />
                    {w.name}
                    {w.enabled === false && <span className="run-off">已停用</span>}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
      {running && <div className="run-progress"><span /></div>}

      {/* 侧栏 */}
      {loggedIn && <div className="side">
        {NAV.map(([path, label, icon, key]) => (
          <NavLink key={path} to={path} className={({ isActive }) => 'nav' + (isActive ? ' active' : '')}>
            <i className={'ti ' + icon} />
            <span className="label">{label}</span>
            {key && <span className="cnt">{stats[key]}</span>}
          </NavLink>
        ))}
        <div className="sp" />
        <button className="collapse" onClick={toggleSide}>
          <i className={'ti ' + (collapsed ? 'ti-layout-sidebar-left-expand' : 'ti-layout-sidebar-left-collapse')} />
          <span className="label">收起侧栏</span>
        </button>
        <Link
          to="/settings"
          className="acct"
          title={login.account ? `已登录：${login.account}` : '已登录'}
        >
          <span className="av">
            {login.account ? login.account[0].toUpperCase() : <i className="ti ti-user" />}
            {login.avatar && <img src={login.avatar} alt="" onError={(e) => e.currentTarget.remove()} />}
          </span>
          <span className="who">{login.account || '已登录'}</span>
          <span className="dot on" />
        </Link>
      </div>}

      {/* 主区 */}
      <div className="main">
        {!loggedIn ? (
          <div className="login-welcome">
            <img className="welcome-icon" src="/brand-icon.png" alt="寻迹AI助手" />
            <h1>欢迎使用寻迹AI助手</h1>
            <p>登录闲鱼账号后，才能使用推荐、收藏监控和条件设置。</p>
            <div className="login-methods" aria-label="支持的登录方式">
              <span><i className="ti ti-scan" /> 扫码登录</span>
              <span><i className="ti ti-message" /> 短信登录</span>
              <span><i className="ti ti-user" /> 账号登录</span>
            </div>
            {['starting', 'waiting', 'scanned'].includes(login.status) ? (
              <div className="login-opening"><span className="spinner" />{login.message || '请在弹出的闲鱼官方窗口完成登录…'}</div>
            ) : (
              <button className="welcome-login" onClick={startLogin} disabled={['starting', 'scanned'].includes(login.status)}>
                <i className="ti ti-login" />
                打开闲鱼官方登录
              </button>
            )}
            {['expired', 'failed', 'busy'].includes(login.status) && <div className="login-error">{login.message}</div>}
            <small>退出账号后，本机数据会安全保留；再次登录即可恢复。</small>
          </div>
        ) : <Routes>
          <Route path="/" element={<Navigate to="/recommendations" replace />} />
          <Route
            path="/recommendations"
            element={<Recommendations refreshKey={refreshKey} onToast={showToast} dropsToday={stats.drops_today} />}
          />
          <Route path="/favorites" element={<Drops refreshKey={refreshKey} />} />
          <Route path="/watches" element={<Watches />} />
          <Route path="/settings" element={<Settings status={status} />} />
          <Route path="*" element={<Navigate to="/recommendations" replace />} />
        </Routes>}
      </div>

      {/* 右栏 · 实时事件(可收起 + 按类型分 tab) */}
      {loggedIn && <div className="rail">
        <div className="rt">
          <i className="ti ti-activity" />
          实时事件
          <button className="rail-x" title="收起" onClick={toggleRail}>
            <i className="ti ti-chevron-right" />
          </button>
        </div>
        <div className="rail-tabs">
          {EVENT_TABS.map((t) => {
            const n = (events || []).filter((e) => !t.types || t.types.includes(e.type)).length
            return (
              <button
                key={t.key}
                className={'rtab' + (eventTab === t.key ? ' on' : '')}
                onClick={() => setEventTab(t.key)}
              >
                {t.label}
                {n > 0 && <b>{n}</b>}
              </button>
            )
          })}
        </div>
        <div className="rail-list">
          {shownEvents === null ? null : shownEvents.length === 0 ? (
            <div className="rail-empty">
              {(events?.length ?? 0) === 0 ? '暂无事件，运行一轮后这里会有动态' : '该类暂无事件'}
            </div>
          ) : (
            shownEvents.map((e, idx) => <EventRow key={`${e.item_id}-${e.created_at}-${idx}`} e={e} />)
          )}
        </div>
      </div>}

      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
