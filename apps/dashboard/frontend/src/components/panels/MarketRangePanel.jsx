import { useMemo, useState } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from 'recharts'

import useMarketRange from '../../hooks/useMarketRange'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatUSD } from '../../utils/format'

const HOUR_OPTIONS = [1, 2, 4, 8, 24]

function toPrice(value) {
  const parsed = parseFloat(value)
  return Number.isNaN(parsed) ? null : parsed
}

function timeLabel(isoTs) {
  const date = new Date(isoTs)
  if (Number.isNaN(date.getTime())) {
    return '—'
  }

  return date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function yDomain(values) {
  if (values.length === 0) {
    return ['auto', 'auto']
  }

  const low = Math.min(...values)
  const high = Math.max(...values)
  const span = Math.max(high - low, 1)
  const padding = span * 0.06
  return [low - padding, high + padding]
}

export default function MarketRangePanel({ buyQuote = null, sellQuote = null }) {
  const [hours, setHours] = useState(2)
  const marketRange = useMarketRange(hours)

  const chartData = useMemo(() => {
    const snapshots = marketRange.data?.snapshots ?? []
    return snapshots
      .map((item) => {
        const mid = toPrice(item.mid)
        if (mid === null) {
          return null
        }

        return {
          ts: item.ts,
          time: timeLabel(item.ts),
          mid,
        }
      })
      .filter(Boolean)
  }, [marketRange.data])

  const midValues = useMemo(() => chartData.map((item) => item.mid), [chartData])
  const domain = useMemo(() => yDomain(midValues), [midValues])

  const buyLine = toPrice(buyQuote?.limit_price)
  const sellLine = toPrice(sellQuote?.limit_price)

  return (
    <div className="card p-3 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <span className="label">Market Range</span>
        <div className="flex items-center gap-1.5">
          {HOUR_OPTIONS.map((option) => {
            const active = option === hours
            return (
              <button
                key={option}
                type="button"
                onClick={() => setHours(option)}
                className={`px-2 py-1 rounded-sm text-[10px] font-mono border transition-colors duration-150 ${
                  active
                    ? 'border-blue/45 text-blue bg-blue/15'
                    : 'border-border text-text-secondary hover:text-text-primary hover:border-blue/30'
                }`}
              >
                {option}H
              </button>
            )
          })}
        </div>
      </div>

      {marketRange.loading && !marketRange.data && <LoadingState rows={5} height="260px" />}
      {marketRange.error && !marketRange.data && <ErrorState message={marketRange.error} onRetry={marketRange.refetch} />}

      {marketRange.data && (
        <>
          <div className="grid grid-cols-2 xl:grid-cols-5 gap-2">
            <div className="bg-surface border border-border rounded-sm p-2">
              <div className="label">Low</div>
              <div className="font-mono text-sm text-green">${formatUSD(marketRange.data.low)}</div>
            </div>
            <div className="bg-surface border border-border rounded-sm p-2">
              <div className="label">High</div>
              <div className="font-mono text-sm text-red">${formatUSD(marketRange.data.high)}</div>
            </div>
            <div className="bg-surface border border-border rounded-sm p-2">
              <div className="label">Range $</div>
              <div className="font-mono text-sm">${formatUSD(marketRange.data.range_usd)}</div>
            </div>
            <div className="bg-surface border border-border rounded-sm p-2">
              <div className="label">Range bps</div>
              <div className="font-mono text-sm">{formatUSD(marketRange.data.range_bps)}</div>
            </div>
            <div className="bg-surface border border-border rounded-sm p-2 xl:col-span-1 col-span-2">
              <div className="label">Current Mid</div>
              <div className="font-mono text-lg text-blue">${formatUSD(marketRange.data.current_mid)}</div>
            </div>
          </div>

          <div className="h-64">
            {chartData.length === 0 ? (
              <div className="text-text-dim font-mono text-xs h-full flex items-center justify-center">No market snapshots in selected range</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#222632" />
                  <XAxis
                    dataKey="time"
                    tick={{ fill: '#555a6a', fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fill: '#555a6a', fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    width={78}
                    tickFormatter={(value) => `$${Number(value).toLocaleString()}`}
                    domain={domain}
                  />
                  <Tooltip
                    contentStyle={{ background: '#181b24', border: '1px solid #222632', borderRadius: '2px', fontSize: '11px' }}
                    labelFormatter={(_, payload) => payload?.[0]?.payload?.ts ? new Date(payload[0].payload.ts).toLocaleString() : '—'}
                    formatter={(value) => [`$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 'Mid']}
                  />
                  {buyLine !== null && (
                    <ReferenceLine y={buyLine} stroke="#3b82f6" strokeDasharray="6 4" ifOverflow="extendDomain" />
                  )}
                  {sellLine !== null && (
                    <ReferenceLine y={sellLine} stroke="#f97316" strokeDasharray="6 4" ifOverflow="extendDomain" />
                  )}
                  <Line dataKey="mid" stroke="#6366f1" strokeWidth={1.8} dot={false} name="Mid" />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </>
      )}
    </div>
  )
}
