import { useEffect, useState } from 'react'
import { api } from '../api'
import { Card, Badge, Spinner, EmptyState, Thumb, TimeMeta } from '../components/ui'
import { yuan, fmtDate, ago } from '../util'

export default function Drops({ refreshKey }) {
  const [items, setItems] = useState(null)
  const [sort, setSort] = useState('drop')

  useEffect(() => {
    api.favorites().then(setItems)
  }, [refreshKey])

  if (items === null) return <Spinner />

  const sorted = [...items].sort((a, b) => {
    if (sort === 'price-asc') return Number(a.price || 0) - Number(b.price || 0)
    if (sort === 'price-desc') return Number(b.price || 0) - Number(a.price || 0)
    return Number(b.reduce_price || 0) - Number(a.reduce_price || 0)
  })

  return (
    <section>
      <h1 className="page-title">
        收藏监控 {items.length > 0 && <span className="count">{items.length}</span>}
      </h1>
      <p className="page-sub">
        绿色商品表示检测到价格下降，点击商品即可查看详情。
      </p>
      {items.length > 0 && <div className="list-toolbar">
        <span>排序</span>
        <select className="sort-select" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="drop">降价金额最多</option>
          <option value="price-asc">价格从低到高</option>
          <option value="price-desc">价格从高到低</option>
        </select>
      </div>}
      {items.length === 0 ? (
        <EmptyState title="还没有收藏" sub="在「推荐」里点收藏后，这里会盯着它们降价" />
      ) : (
        <div className="grid">
          {sorted.map((it) => (
            <Card key={it.item_id} className={`rec${it.dead ? ' dead' : ''}${it.reduce_price > 0 ? ' price-dropped' : ''}`}>
              <Thumb url={it.pic_url} dead={it.dead} deadReason={it.dead_reason} />
              <div className="rec-body">
                <a className="rec-title" href={it.url} target="_blank" rel="noreferrer">
                  {it.title}
                </a>
                <div className="rec-price">{yuan(it.price)}</div>
                {it.dead ? (
                  <Badge tone="dead">{it.dead_reason || '已下架'} · 别再打开</Badge>
                ) : (
                  it.reduce_price > 0 && (
                    <Badge tone="drop">
                      收藏后降 ¥{Math.round(it.reduce_price).toLocaleString('zh-CN')}
                    </Badge>
                  )
                )}
                <div className="rec-meta">
                  {it.location && <span>{it.location}</span>}
                  {it.condition && <span>{it.condition}</span>}
                  {it.free_shipping && <Badge>包邮</Badge>}
                  {it.seller_nick && <span>{it.seller_nick}</span>}
                </div>
                <TimeMeta
                  items={[
                    ['上架', ago(it.publish_time)],
                    ['收藏', fmtDate(it.favorited_at)],
                    ['调价', fmtDate(it.price_changed_at)],
                    ['入库', fmtDate(it.first_seen_at)],
                  ]}
                />
              </div>
            </Card>
          ))}
        </div>
      )}
    </section>
  )
}
