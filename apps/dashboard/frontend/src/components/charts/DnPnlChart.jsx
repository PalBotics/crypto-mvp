import { useMemo } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
} from 'recharts'
import useApi from '../../hooks/useApi'
import ChartContainer from './ChartContainer'
import { toLocalTime } from '../../utils/format'
import { buildDnTradesFromFills, enrichDnTrades } from '../../utils/dnTrades'
import { LoadingState, ErrorState } from '../common/Loading'

const POLL_MS = 60000

function toFiniteNumber(value, fallback = 0) {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

export default function DnPnlChart({ account = 'paper_dn' }) {
  const fills = useApi(`/api/runs/${account}/fills?limit=100`, { interval: POLL_MS })
  const pnl = useApi(`/api/runs/${account}/pnl`, { interval: POLL_MS })

  const chartData = useMemo(() => {
    try {
      const fillsRows = Array.isArray(fills.data) ? fills.data : []
      const enriched = enrichDnTrades(buildDnTradesFromFills(fillsRows), pnl.data)
      const trades = (Array.isArray(enriched) ? enriched : []).filter((t) => !t.isActive && t.exitTime)

      return trades.map((trade) => {
        const cumulative = toFiniteNumber(trade.cumulativeNet)
        return {
          time: toLocalTime(trade.exitTime.toISOString()),
          tradePnl: toFiniteNumber(trade.netPnl),
          cumulativePnl: cumulative,
          positive: cumulative >= 0 ? cumulative : null,
          negative: cumulative < 0 ? cumulative : null,
        }
      })
    } catch {
      return []
    }
  }, [fills.data, pnl.data])

  if ((fills.loading || pnl.loading) && chartData.length === 0) {
    return (
      <ChartContainer title="Cumulative PnL" lastUpdated={fills.lastUpdated || pnl.lastUpdated} height="260px" loading={fills.loading || pnl.loading}>
        <LoadingState rows={5} height="100%" />
      </ChartContainer>
    )
  }

  if ((fills.error || pnl.error) && chartData.length === 0) {
    return (
      <ChartContainer title="Cumulative PnL" lastUpdated={fills.lastUpdated || pnl.lastUpdated} height="260px" loading={fills.loading || pnl.loading}>
        <ErrorState message={fills.error || pnl.error} onRetry={() => { fills.refetch(); pnl.refetch() }} height="100%" />
      </ChartContainer>
    )
  }

  if (chartData.length < 2) {
    return (
      <ChartContainer title="Cumulative PnL" lastUpdated={fills.lastUpdated || pnl.lastUpdated} height="260px" loading={fills.loading || pnl.loading}>
        <div className="text-text-dim font-mono text-xs text-center py-6">Not enough trade history</div>
      </ChartContainer>
    )
  }

  return (
    <ChartContainer title="Cumulative PnL" lastUpdated={fills.lastUpdated || pnl.lastUpdated} height="260px" loading={fills.loading || pnl.loading}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
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
            width={70}
            tickFormatter={(v) => `$${toFiniteNumber(v).toFixed(2)}`}
          />
          <ReferenceLine y={0} stroke="#555a6a" strokeDasharray="4 4" />
          <Tooltip
            contentStyle={{ background: '#181b24', border: '1px solid #222632', borderRadius: '2px', fontSize: '11px' }}
            formatter={(value, name) => {
              const label = name === 'tradePnl' ? 'Trade PnL' : 'Cumulative PnL'
              return [`$${toFiniteNumber(value).toFixed(2)}`, label]
            }}
          />
          <Line type="monotone" dataKey="positive" stroke="#3B6D11" strokeWidth={2} dot={false} connectNulls />
          <Line type="monotone" dataKey="negative" stroke="#A32D2D" strokeWidth={2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
