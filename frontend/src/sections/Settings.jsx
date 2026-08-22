import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Card, Button, Spinner, Toggle, Field, ConfirmDialog } from '../components/ui'

export default function Settings({ status }) {
  const [cfg, setCfg] = useState(null)
  const [login, setLogin] = useState({ status: 'idle', has_state: false })
  const [billing, setBilling] = useState({ active: false, balance: 0 })
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirmLogout, setConfirmLogout] = useState(false)
  const timer = useRef(null)

  useEffect(() => {
    // 核心设置和登录状态先显示；额度服务慢或离线时不阻塞整个页面。
    api.config().then(setCfg)
    api.loginStatus().then(setLogin)
    api.billingStatus().then(setBilling).catch(() => {})
    return () => clearInterval(timer.current)
  }, [])

  const set = (key, value) => setCfg((current) => ({ ...current, [key]: value }))
  const save = async () => {
    setBusy(true)
    try {
      setCfg(await api.saveConfig(cfg)); setSaved(true)
      setTimeout(() => setSaved(false), 1800)
    } finally { setBusy(false) }
  }
  const startLogin = async () => {
    setLogin((current) => ({ ...current, status: 'starting', qr: null, message: '正在打开登录页面…' }))
    const started = await api.loginStart()
    if (started?.status === 'busy') setLogin((current) => ({ ...current, ...started }))
    clearInterval(timer.current)
    timer.current = setInterval(async () => {
      const next = await api.loginStatus(); setLogin(next)
      if (['success', 'expired', 'failed', 'idle', 'busy'].includes(next.status)) clearInterval(timer.current)
    }, 700)
  }
  const logout = async () => {
    setConfirmLogout(false); setBusy(true); clearInterval(timer.current)
    try { setLogin(await api.logout()) } finally { setBusy(false) }
  }
  const recharge = () => billing.checkout_url
    ? window.open(billing.checkout_url, '_blank', 'noreferrer')
    : window.alert('在线充值正在配置，请联系销售人员开通额度。')
  const loggingIn = ['starting', 'scanned'].includes(login.status) || (login.status === 'waiting' && !login.qr)

  if (!cfg) return <Spinner />
  return <section className="settings-simple">
    <div className="settings-head">
      <div><h1 className="page-title">使用设置</h1><p className="page-sub">完成登录并设置刷新时间，其余服务已经为你配置好。</p></div>
      <span className="managed-badge"><i className="ti ti-shield-check" /> 智能托管已开启</span>
    </div>

    <Card className="form-card billing-card premium-card">
      <div className="card-heading"><span className="card-icon green"><i className="ti ti-sparkles" /></span><div><div className="form-title">AI 智能分析</div><p>自动筛选符合要求的商品，无需设置接口或模型。</p></div></div>
      <div className="balance-row">
        <div className="balance-box"><span>剩余分析额度</span><b>{billing.offline ? '--' : Number(billing.balance || 0).toLocaleString('zh-CN')}</b><small>次</small></div>
        <div className="quota-copy"><b>{billing.active ? '服务正常' : '等待开通'}</b><span>额度不足时充值即可继续使用</span></div>
        <Button onClick={recharge}>立即充值</Button>
      </div>
    </Card>

    <Card className="form-card premium-card">
      <div className="card-heading"><span className="card-icon"><i className="ti ti-user-check" /></span><div><div className="form-title">账号登录</div><p>打开闲鱼官方页面，可选择扫码、短信或账号登录；登录信息仅保存在本机。</p></div></div>
      {loggingIn ? <div className="qr-wrap"><div className="spinner" /><div className="qr-tip">{login.message || '正在打开登录页面…'}</div></div>
        : login.qr ? <div className="qr-wrap"><img className="qr-img" src={login.qr} alt="登录二维码" /><div className="qr-tip">打开手机闲鱼扫一扫，然后确认登录</div></div>
        : <div className="login-row clean-login">
          <span className={login.has_state ? 'login-state on' : 'login-state'}>{login.has_state ? `✓ 已登录${login.account ? '：' + login.account : ''}` : '○ 尚未登录'}</span>
          {['expired', 'failed', 'busy'].includes(login.status) && <span className="test-err">{login.message}</span>}
          <div className="grow" />
          {login.has_state && <Button variant="ghost" onClick={() => setConfirmLogout(true)} disabled={busy}>退出账号</Button>}
          <Button onClick={startLogin} disabled={busy}>{login.has_state ? '重新登录' : '打开官方登录'}</Button>
        </div>}
    </Card>

    <Card className="form-card premium-card">
      <div className="card-heading"><span className="card-icon"><i className="ti ti-clock-bolt" /></span><div><div className="form-title">刷新与提醒</div><p>保留自定义分钟；数值越小更新越快，建议不要低于5分钟。</p></div></div>
      <div className="form-grid simple-grid">
        <Field label="推荐刷新（分钟）" hint="自动查找新商品"><input type="number" min="5" value={cfg.schedule_minutes} onChange={(e) => set('schedule_minutes', Math.max(5, Number(e.target.value)))} /></Field>
        <Field label="收藏刷新（分钟）" hint="检查降价和售出状态"><input type="number" min="5" value={cfg.favorites_minutes} onChange={(e) => set('favorites_minutes', Math.max(5, Number(e.target.value)))} /></Field>
        <Field label="接收提醒的邮箱" hint="只填写收件地址"><input type="email" value={cfg.notify_to || ''} onChange={(e) => set('notify_to', e.target.value)} placeholder="name@example.com" /></Field>
        <Field label="降价提醒金额（元）" hint="达到该金额时提醒"><input type="number" min="0" value={cfg.min_drop_abs} onChange={(e) => set('min_drop_abs', Number(e.target.value))} /></Field>
      </div>
      <div className="notify-options">
        <Toggle checked={cfg.notify_on_new} onChange={(v) => set('notify_on_new', v)} label="新推荐" />
        <Toggle checked={cfg.notify_on_drop} onChange={(v) => set('notify_on_drop', v)} label="商品降价" />
        <Toggle checked={cfg.notify_on_sold} onChange={(v) => set('notify_on_sold', v)} label="售出或下架" />
        <Toggle checked={cfg.notify_on_login} onChange={(v) => set('notify_on_login', v)} label="登录失效" />
      </div>
      <div className="form-row"><Toggle checked={!cfg.paused} onChange={(v) => set('paused', !v)} label="自动运行" /><div className="grow" />{saved && <span className="saved-hint">✓ 已保存</span>}<Button onClick={save} disabled={busy}>{busy ? '保存中…' : '保存设置'}</Button></div>
    </Card>

    <Card className="service-strip">
      <div><span className="service-dot on" /><b>智能筛选</b><small>已托管</small></div>
      <div><span className="service-dot on" /><b>安全访问</b><small>自动维护</small></div>
      <div><span className={cfg.notify_to ? 'service-dot on' : 'service-dot'} /><b>消息提醒</b><small>{cfg.notify_to ? '已开启' : '待填写邮箱'}</small></div>
      <div><span className={status?.running ? 'service-dot busy' : 'service-dot on'} /><b>运行状态</b><small>{status?.running ? '正在执行' : '准备就绪'}</small></div>
    </Card>
    <ConfirmDialog open={confirmLogout} danger title="退出账号" message="只退出当前账号，不会删除收藏、推荐和条件设置。再次登录即可恢复。" confirmText="确认退出" onConfirm={logout} onCancel={() => setConfirmLogout(false)} />
  </section>
}
