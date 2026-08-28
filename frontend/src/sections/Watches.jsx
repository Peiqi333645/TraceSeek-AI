import { useEffect, useState } from 'react'
import { api } from '../api'
import { Card, Button, Badge, Spinner, EmptyState, Toggle, Field } from '../components/ui'
import { splitCsv } from '../util'
import REGION_TREE from '../data/china-regions.json'

const CONDITION_OPTIONS = [
  '全新', '几乎全新', '轻微使用痕迹',
  '明显使用痕迹', '仅拆封未使用', '无原包装',
  '官翻机', '包装脏污/变形/破损', '轻微划痕/脏污',
]

const cleanProvince = (name = '') => name
  .replace(/特别行政区$/, '')
  .replace(/(?:壮族|回族|维吾尔)自治区$/, '')
  .replace(/自治区$/, '')
  .replace(/[省市]$/, '')
const cleanCity = (name = '') => name.replace(/市$/, '')
const usable = (node) => node?.n && !['市辖区', '县'].includes(node.n)
const provinceValue = (node) => cleanProvince(node?.n)

// 直辖市在行政区划数据中没有“市”这一层，界面仍按闲鱼的省→市→区三级
// 展示：第二级使用直辖市自身，第三步再列出各区县。
const cityNodes = (province) => {
  const children = (province?.d || []).filter(usable)
  if (!children.length) return []
  if (children.some((node) => Array.isArray(node.d))) return children.filter((node) => Array.isArray(node.d))
  return [{ c: `${province.c}-city`, n: province.n, d: children }]
}
const cityValue = (node) => cleanCity(node?.n)
const findProvince = (value) => REGION_TREE.find((node) => provinceValue(node) === cleanProvince(value))
const findCity = (province, value) => cityNodes(province).find((node) => cityValue(node) === cleanCity(value))

const blank = () => ({
  id: null,
  name: '',
  keywordsText: '',
  price_min: '',
  price_max: '',
  province: '',
  city: '',
  district: '',
  condition: [],
  requirement: '',
  free_shipping: false,
  enabled: true,
})

export default function Watches({ onChanged }) {
  const [list, setList] = useState(null)
  const [form, setForm] = useState(blank())

  const load = async () => {
    const next = await api.watches()
    setList(next)
    return next
  }
  useEffect(() => {
    load()
  }, [])

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))
  const selectedProvince = findProvince(form.province)
  const cities = cityNodes(selectedProvince)
  const selectedCity = findCity(selectedProvince, form.city)
  const districts = (selectedCity?.d || []).filter(usable)

  const save = async () => {
    if (!form.name.trim() || !form.keywordsText.trim()) return
    const body = {
      name: form.name.trim(),
      keywords: splitCsv(form.keywordsText),
      price_min: form.price_min === '' ? null : Number(form.price_min),
      price_max: form.price_max === '' ? null : Number(form.price_max),
      province: form.province.trim() || null,
      city: form.city.trim() || null,
      district: form.district.trim() || null,
      condition: form.condition.length ? form.condition : null,
      requirement: form.requirement.trim() || null,
      free_shipping: form.free_shipping || null,
      enabled: form.enabled,
    }
    if (form.id) await api.updateWatch(form.id, body)
    else await api.createWatch(body)
    setForm(blank())
    const next = await load()
    onChanged?.(next)
  }

  const edit = (w) =>
    setForm({
      id: w.id,
      name: w.name,
      keywordsText: (w.keywords || []).join(', '),
      price_min: w.price_min ?? '',
      price_max: w.price_max ?? '',
      province: w.province ?? '',
      city: w.city ?? '',
      district: w.district ?? '',
      condition: (w.condition || []).filter((v) => CONDITION_OPTIONS.includes(v)),
      requirement: w.requirement ?? '',
      free_shipping: !!w.free_shipping,
      enabled: w.enabled,
    })

  const toggleEnabled = async (w) => {
    await api.updateWatch(w.id, {
      name: w.name,
      keywords: w.keywords,
      price_min: w.price_min,
      price_max: w.price_max,
      province: w.province,
      city: w.city,
      district: w.district,
      condition: w.condition,
      requirement: w.requirement,
      free_shipping: w.free_shipping,
      enabled: !w.enabled,
    })
    const next = await load()
    onChanged?.(next)
  }

  const remove = async (id) => {
    await api.deleteWatch(id)
    const next = await load()
    onChanged?.(next)
  }

  if (list === null) return <Spinner />

  return (
    <section>
      <h1 className="page-title">监控条件</h1>
      <p className="page-sub">关键词与价格范围等，定时按这些条件搜索并推荐。</p>

      <Card className="form-card">
        <div className="form-title">{form.id ? '编辑条件' : '新增条件'}</div>
        <div className="form-grid">
          <Field label="名称">
            <input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="iPhone15Pro" />
          </Field>
          <Field label="搜索词" hint="整体作为一条搜索词去搜（空格分隔），不是逐词分搜">
            <input
              value={form.keywordsText}
              onChange={(e) => set('keywordsText', e.target.value)}
              placeholder="MacBook Pro M1 Pro 16寸 32G 1T"
            />
          </Field>
          <Field label="最低价">
            <input type="number" value={form.price_min} onChange={(e) => set('price_min', e.target.value)} />
          </Field>
          <Field label="最高价">
            <input type="number" value={form.price_max} onChange={(e) => set('price_max', e.target.value)} />
          </Field>
          <Field label="省份（可选）" hint="第一步：选择省份">
            <select value={form.province} onChange={(e) => {
              setForm((f) => ({ ...f, province: e.target.value, city: '', district: '' }))
            }}>
              <option value="">不限省份</option>
              {REGION_TREE.filter(usable).map((node) => (
                <option key={node.c} value={provinceValue(node)}>{provinceValue(node)}</option>
              ))}
            </select>
          </Field>
          <Field label="城市（可选）" hint={form.province ? '第二步：只显示该省的城市' : '请先选择省份'}>
            <select
              value={form.city}
              disabled={!form.province}
              onChange={(e) => setForm((f) => ({ ...f, city: e.target.value, district: '' }))}
            >
              <option value="">不限城市</option>
              {cities.map((node) => (
                <option key={node.c} value={cityValue(node)}>{cityValue(node)}</option>
              ))}
            </select>
          </Field>
          <Field label="区县（可选）" hint={form.city ? '第三步：只显示该市的区县' : '请先选择城市'}>
            <select value={form.district} disabled={!form.city} onChange={(e) => set('district', e.target.value)}>
              <option value="">不限区县</option>
              {districts.map((node) => <option key={node.c} value={node.n}>{node.n}</option>)}
            </select>
          </Field>
          <Field label="成色（可多选）" hint="采用闲鱼原生9档描述；不选择表示不限成色">
            <div className="condition-picker">
              {CONDITION_OPTIONS.map((option) => {
                const selected = form.condition.includes(option)
                return (
                  <button
                    key={option}
                    type="button"
                    className={`condition-chip${selected ? ' selected' : ''}`}
                    aria-pressed={selected}
                    onClick={() => set('condition', selected
                      ? form.condition.filter((v) => v !== option)
                      : [...form.condition, option])}
                  >
                    {option}
                  </button>
                )
              })}
            </div>
          </Field>
        </div>
        <div className="req-field">
          <Field
            label="AI 审核要求（自然语言，可选）"
            hint="定时搜索命中后，交给大模型按这段要求二次筛选；不符合的不会进推荐。"
          >
            <textarea
              className="req-input"
              rows={3}
              value={form.requirement}
              onChange={(e) => set('requirement', e.target.value)}
              placeholder="例：只要 14 寸 M5 Pro 国行本机，48G 以上，成色 95 新以上，价格不超过 19000，排除 16 寸 / Max 芯片 / 未拆封全新 / 配件 / 维修"
            />
          </Field>
        </div>
        <div className="form-row">
          <Toggle checked={form.free_shipping} onChange={(v) => set('free_shipping', v)} label="仅包邮" />
          <Toggle checked={form.enabled} onChange={(v) => set('enabled', v)} label="启用" />
          <div className="grow" />
          {form.id && (
            <Button variant="ghost" onClick={() => setForm(blank())}>
              取消
            </Button>
          )}
          <Button onClick={save}>{form.id ? '保存' : '添加'}</Button>
        </div>
      </Card>

      {list.length === 0 ? (
        <EmptyState title="还没有监控条件" sub="在上面添加一个，定时任务就会开始找货" />
      ) : (
        <div className="watch-list">
          {list.map((w) => (
            <Card key={w.id} className="watch-row">
              <div className="watch-main">
                <div className="watch-name">
                  {w.name}
                  {!w.enabled && <span className="muted-tag">已停用</span>}
                </div>
                <div className="watch-kw">{(w.keywords || []).join(' · ')}</div>
                <div className="rec-meta">
                  {(w.price_min || w.price_max) && (
                    <span>
                      ¥{w.price_min ?? 0} – {w.price_max ?? '∞'}
                    </span>
                  )}
                  {w.province && <span>{w.province}</span>}
                  {w.city && <span>{w.city}</span>}
                  {w.district && <span>{w.district}</span>}
                  {w.free_shipping && <Badge>包邮</Badge>}
                  {(w.condition || []).map((c) => (
                    <span key={c}>{c}</span>
                  ))}
                </div>
                {w.requirement && (
                  <div className="watch-req">
                    <span className="watch-req-tag">AI</span>
                    {w.requirement}
                  </div>
                )}
              </div>
              <div className="watch-actions">
                <Toggle checked={w.enabled} onChange={() => toggleEnabled(w)} />
                <Button variant="ghost" className="btn-sm" onClick={() => edit(w)}>
                  编辑
                </Button>
                <Button variant="ghost" className="btn-sm btn-danger" onClick={() => remove(w.id)}>
                  删除
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </section>
  )
}
