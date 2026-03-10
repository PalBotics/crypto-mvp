import { useMemo, useState } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts'

import useMarketRange from '../../hooks/useMarketRange'
import useQuoteHistory from '../../hooks/useQuoteHistory'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatUSD } from '../../utils/format'
import MetricCard from '../common/MetricCard'

const HOUR_OPTIONS = [1, 2, 4, 8, 24]
const MATCH_WINDOW_MS = 90 * 1000

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

function twapDriftColor(driftBps) {
  const abs = Math.abs(driftBps)
  if (abs <= 20) return 'green'
  if (abs <= 60) return 'yellow'
  return 'red'
}

export default function MarketRangePanel() {
  const [hours, setHours] = useState(2)
  const marketRange = useMarketRange(hours)
  const quoteHistory = useQuoteHistory(hours)

  const marketRangeData = useMemo(() => {
    return (marketRange.data?.snapshots ?? [])
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

  const quoteHistoryData = useMemo(() => {
    return (quoteHistory.data ?? [])
      .map((item) => ({
        ts: item.ts,
        mid: toPrice(item.mid_price),
        twap: toPrice(item.twap),
        bid: toPrice(item.bid_quote),
        ask: toPrice(item.ask_quote),
      }))
      .filter((item) => item.mid !== null && item.twap !== null)
  }, [quoteHistory.data])

  const mergedChartData = useMemo(() => {
    if (marketRangeData.length === 0) {
      return []
    }

    return marketRangeData.map((basePoint) => {
      const baseMs = Date.parse(basePoint.ts)
      let best = null
      let bestDiff = Number.POSITIVE_INFINITY

      if (!Number.isNaN(baseMs)) {
        for (const quotePoint of quoteHistoryData) {
          const quoteMs = Date.parse(quotePoint.ts)
          if (Number.isNaN(quoteMs)) {
            continue
          }

          const diff = Math.abs(quoteMs - baseMs)
          if (diff <= MATCH_WINDOW_MS && diff < bestDiff) {
            best = quotePoint
            bestDiff = diff
          }
        }
      }

      return {
        ...basePoint,
        twap: best?.twap,
        bid: best?.bid,
        ask: best?.ask,
      }
    })
  }, [marketRangeData, quoteHistoryData])

  const quoteDomain = useMemo(() => {
    const values = mergedChartData
      .flatMap((item) => [item.mid, item.twap, item.bid, item.ask])
      .filter((v) => v !== null && v !== undefined)
    return yDomain(values)
  }, [mergedChartData])

  const latestQuoteSnapshot = quoteHistoryData.length > 0 ? quoteHistoryData[quoteHistoryData.length - 1] : null
  const twapDriftBps = latestQuoteSnapshot && latestQuoteSnapshot.twap !== 0
    ? ((latestQuoteSnapshot.mid - latestQuoteSnapshot.twap) / latestQuoteSnapshot.twap) * 10000
    : null
  const twapDriftText = twapDriftBps === null
    ? '—'
    : `${twapDriftBps >= 0 ? '+' : ''}${twapDriftBps.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} bps`

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
          <div className="grid grid-cols-2 xl:grid-cols-6 gap-2">
            <MetricCard label="Low" value={`$${formatUSD(marketRange.data.low)}`} color="green" size="sm" />
            <MetricCard label="High" value={`$${formatUSD(marketRange.data.high)}`} color="red" size="sm" />
            <MetricCard label="Range $" value={`$${formatUSD(marketRange.data.range_usd)}`} size="sm" />
            <MetricCard label="Range bps" value={formatUSD(marketRange.data.range_bps)} size="sm" />
            <MetricCard label="Current Mid" value={`$${formatUSD(marketRange.data.current_mid)}`} color="blue" size="sm" />
            <MetricCard label="TWAP Drift" value={twapDriftText} color={twapDriftBps === null ? 'default' : twapDriftColor(twapDriftBps)} size="sm" />
          </div>

          <div className="h-64">
            <div className="label mb-2">Price, TWAP & Quotes</div>
            {marketRange.loading && marketRangeData.length === 0 ? (
              <LoadingState rows={4} height="100%" />
            ) : marketRange.error && marketRangeData.length === 0 ? (
              <ErrorState message={marketRange.error} onRetry={marketRange.refetch} height="100%" />
            ) : mergedChartData.length === 0 ? (
              <div className="text-text-dim font-mono text-xs h-full flex items-center justify-center">No market snapshots in selected range</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={mergedChartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
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
                    domain={quoteDomain}
                  />
                  <Tooltip
                    contentStyle={{ background: '#181b24', border: '1px solid #222632', borderRadius: '2px', fontSize: '11px' }}
                    labelFormatter={(_, payload) => payload?.[0]?.payload?.ts ? new Date(payload[0].payload.ts).toLocaleString() : '—'}
                    formatter={(value, name) => [
                      `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                      name,
                    ]}
                  />
                  <Legend verticalAlign="top" height={24} wrapperStyle={{ fontSize: '11px' }} />
                  <Line dataKey="mid" stroke="#6366f1" strokeWidth={1.8} dot={false} name="Mid" />
                  <Line dataKey="twap" stroke="#eab308" strokeWidth={1.6} dot={false} name="TWAP" />
                  <Line dataKey="bid" stroke="#3b82f6" strokeWidth={1.3} strokeDasharray="4 2" dot={false} name="Bid" connectNulls />
                  <Line dataKey="ask" stroke="#f97316" strokeWidth={1.3} strokeDasharray="4 2" dot={false} name="Ask" connectNulls />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </>
      )}
    </div>
  )
}
