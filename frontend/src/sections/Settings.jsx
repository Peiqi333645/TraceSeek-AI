import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Card, Button, Spinner, Toggle, Field, ConfirmDialog } from '../components/ui'

export default function Settings({ status }) {
  const [cfg, setCfg] = useState(null)
  const [login, setLogin] = useState({ status: 'idle', has_state: false })
  const [apiToken, setApiToken] = useState('')
  const [aiResult, setAiResult] = useState(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirmLogout, setConfirmLogout] = useState(false)
  const timer = useRef(null)

  useEffect(() => {
    api.config().then(setCfg)
    api.loginStatus().then(setLogin)
    return () => clearInterval(timer.current)
  }, [])

  const set = (key, value) => setCfg((current) => ({ ...current, [key]: value }))
  const normalizedConfig = () => ({
    ...cfg,
    schedule_minutes: Math.max(0.5, Number(cfg.schedule_minutes) || 5),
    favorites_minutes: Math.max(0.5, Number(cfg.favorites_minutes) || 5),
    search_max_pages: Math.min(10, Math.max(1, Number(cfg.search_max_pages) || 5)),
    deep_search_interval_seconds: Math.max(1, Number(cfg.deep_search_interval_seconds) || 300),
  })
  const save = async () => {
    setBusy(true)
    try {
      const body = normalizedConfig()
      if (apiToken.trim()) body.review_api_token = apiToken.trim()
      setCfg(await api.saveConfig(body)); setApiToken(''); setSaved(true)
      setTimeout(() => setSaved(false), 1800)
    } finally { setBusy(false) }
  }
  const saveAndTestAi = async () => {
    setBusy(true); setAiResult(null)
    try {
      const body = normalizedConfig()
      if (apiToken.trim()) body.review_api_token = apiToken.trim()
      const next = await api.saveConfig(body)
      setCfg(next); setApiToken('')
      const result = await api.testReview()
      setAiResult(result?.ok ? { ok: true, text: '连接成功，可以使用 AI 辅助审核。' } : { ok: false, text: result?.error || '连接失败，请检查接口地址、模型和密钥。' })
    } catch (error) {
      setAiResult({ ok: false, text: error?.message || '连接失败，请稍后重试。' })
    } finally { setBusy(false) }
  }
  const chooseProvider = (provider) => {
    const presets = {
      deepseek: ['https://api.deepseek.com/v1', 'deepseek-chat'],
      qwen: ['https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus'],
      doubao: ['https://ark.cn-beijing.volces.com/api/v3', ''],
    }
    if (presets[provider]) {
      setCfg((current) => ({ ...current, review_base_url: presets[provider][0], review_model: presets[provider][1] }))
    }
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
  const loggingIn = ['starting', 'scanned'].includes(login.status) || (login.status === 'waiting' && !login.qr)

  if (!cfg) return <Spinner />
  return <section className="settings-simple">
    <div className="settings-head">
      <div><h1 className="page-title">使用设置</h1><p className="page-sub">完成账号登录、刷新提醒和可选的 AI 设置即可使用。</p></div>
      <span className="managed-badge"><i className="ti ti-shield-check" /> 访问节奏保护已开启</span>
    </div>

    <Card className="form-card ai-config-card premium-card">
      <div className="card-heading"><span className="card-icon green"><i className="ti ti-sparkles" /></span><div><div className="form-title">AI 辅助审核（可选）</div><p>使用您自己的 DeepSeek、豆包、通义千问或兼容接口；不开启也能正常监控。</p></div></div>
      <div className="form-row ai-enable-row">
        <Toggle checked={cfg.review_enabled} onChange={(v) => set('review_enabled', v)} label="启用 AI 辅助审核" />
        <span className="grow" />
        <span className={cfg.review_token_set ? 'login-state on' : 'login-state'}>{cfg.review_token_set ? '✓ 已保存密钥' : '○ 尚未填写密钥'}</span>
      </div>
      {cfg.review_enabled && <>
        <div className="provider-row">
          <span>快速选择：</span>
          <Button variant="ghost" onClick={() => chooseProvider('deepseek')}>DeepSeek</Button>
          <Button variant="ghost" onClick={() => chooseProvider('doubao')}>豆包</Button>
          <Button variant="ghost" onClick={() => chooseProvider('qwen')}>通义千问</Button>
        </div>
        <div className="form-grid simple-grid ai-api-grid">
          <Field label="API 接口地址" hint="从模型服务商控制台复制"><input value={cfg.review_base_url || ''} onChange={(e) => set('review_base_url', e.target.value)} placeholder="https://.../v1" /></Field>
          <Field label="模型名称" hint="豆包请填写推理接入点 ID"><input value={cfg.review_model || ''} onChange={(e) => set('review_model', e.target.value)} placeholder="例如 deepseek-chat" /></Field>
          <Field label="API 密钥" hint={cfg.review_token_set ? '留空表示继续使用已保存的密钥' : '密钥仅保存在本机'}><input type="password" value={apiToken} onChange={(e) => setApiToken(e.target.value)} placeholder={cfg.review_token_set ? '已保存，无需重复填写' : '请输入 API Key'} /></Field>
        </div>
        <div className="form-row">
          {aiResult && <span className={aiResult.ok ? 'saved-hint' : 'test-err'}>{aiResult.ok ? '✓ ' : '✕ '}{aiResult.text}</span>}
          <div className="grow" />
          <Button onClick={saveAndTestAi} disabled={busy}>{busy ? '正在测试…' : '保存并测试连接'}</Button>
        </div>
      </>}
    </Card>

    <Card className="form-card premium-card">
      <div className="card-heading"><span className="card-icon"><i className="ti ti-user-check" /></span><div><div className="form-title">账号登录</div><p>使用手机闲鱼扫码登录，登录信息仅保存在本机。</p></div></div>
      {loggingIn ? <div className="qr-wrap"><div className="spinner" /><div className="qr-tip">{login.message || '正在打开登录页面…'}</div></div>
        : login.qr ? <div className="qr-wrap"><img className="qr-img" src={login.qr} alt="登录二维码" /><div className="qr-tip">打开手机闲鱼扫一扫，然后确认登录</div></div>
        : <div className="login-row clean-login">
          <span className={login.has_state ? 'login-state on' : 'login-state'}>{login.has_state ? `✓ 已登录${login.account ? '：' + login.account : ''}` : '○ 尚未登录'}</span>
          {['expired', 'failed', 'busy'].includes(login.status) && <span className="test-err">{login.message}</span>}
          <div className="grow" />
          {login.has_state && <Button variant="ghost" onClick={() => setConfirmLogout(true)} disabled={busy}>退出账号</Button>}
          <Button onClick={startLogin} disabled={busy}>{login.has_state ? '重新登录' : '扫码登录'}</Button>
        </div>}
    </Card>

    <Card className="form-card premium-card">
      <div className="card-heading"><span className="card-icon"><i className="ti ti-clock-bolt" /></span><div><div className="form-title">刷新与提醒</div><p>保留自定义分钟；数值越小更新越快，建议不要低于5分钟。</p></div></div>
      <div className="form-grid simple-grid">
        <Field label="推荐刷新（分钟）" hint="可填 0.5 起；建议不低于 5 分钟"><input type="number" min="0.5" step="0.5" value={cfg.schedule_minutes} onChange={(e) => set('schedule_minutes', e.target.value)} /></Field>
        <Field label="收藏刷新（分钟）" hint="可填 0.5 起；建议不低于 5 分钟"><input type="number" min="0.5" step="0.5" value={cfg.favorites_minutes} onChange={(e) => set('favorites_minutes', e.target.value)} /></Field>
        <Field label="每次搜索页数" hint="建议 5 页；页数越多，商品越多但耗时越长"><input type="number" min="1" max="10" step="1" value={cfg.search_max_pages} onChange={(e) => set('search_max_pages', e.target.value)} /></Field>
        <Field label="深度轮换间隔（秒）" hint="允许 1 秒起；建议至少 300 秒，过快可能触发验证或访问限制"><input type="number" min="1" step="1" value={cfg.deep_search_interval_seconds} onChange={(e) => set('deep_search_interval_seconds', e.target.value)} /></Field>
        <Field label="接收提醒的邮箱" hint="只填写收件地址"><input type="email" value={cfg.notify_to || ''} onChange={(e) => set('notify_to', e.target.value)} placeholder="name@example.com" /></Field>
        <Field label="降价提醒金额（元）" hint="达到该金额时提醒"><input type="number" min="0" value={cfg.min_drop_abs} onChange={(e) => set('min_drop_abs', Number(e.target.value))} /></Field>
      </div>
      <div className="form-row">
        <Toggle checked={cfg.deep_search_enabled} onChange={(v) => set('deep_search_enabled', v)} label="启用深度轮换搜索" />
        <span className="field-hint">普通刷新检查第 1–5 页；深度轮换依次检查 6–10、11–15…46–50 页，完成后回到 6–10 页重新检查新变化。</span>
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
      <div><span className={cfg.review_enabled ? 'service-dot on' : 'service-dot'} /><b>AI 辅助</b><small>{cfg.review_enabled ? '已开启' : '未开启'}</small></div>
      <div><span className="service-dot on" /><b>访问节奏保护</b><small>自动开启</small></div>
      <div><span className={cfg.notify_to ? 'service-dot on' : 'service-dot'} /><b>消息提醒</b><small>{cfg.notify_to ? '已开启' : '待填写邮箱'}</small></div>
      <div><span className={status?.running ? 'service-dot busy' : 'service-dot on'} /><b>运行状态</b><small>{status?.running ? '正在执行' : '准备就绪'}</small></div>
    </Card>
    <ConfirmDialog open={confirmLogout} danger title="退出账号" message="只退出当前账号，不会删除收藏、推荐和条件设置。再次登录即可恢复。" confirmText="确认退出" onConfirm={logout} onCancel={() => setConfirmLogout(false)} />
  </section>
}
