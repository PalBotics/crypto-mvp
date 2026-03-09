import { useMemo } from 'react'
import useFills from '../../hooks/useFills'
import ChartContainer from './ChartContainer'
import { LoadingState, ErrorState } from '../common/Loading'
import { toLocalTime } from '../../utils/format'
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
} from 'recharts'

export default function PnLChart() {
  const fills = useFills(500)

  const chartData = useMemo(() => {
    const sorted = [...fills.data].sort(
      (a, b) => new Date(a.fill_ts).getTime() - new Date(b.fill_ts).getTime()
    )

    let runningTotal = 0

    return sorted.map((fill) => {
      const fee = parseFloat(fill.fee_amount)
      const contribution = Number.isNaN(fee) ? 0 : -fee
      runningTotal += contribution

      return {
        time: toLocalTime(fill.fill_ts),
        pnl: runningTotal,
      }
    })
  }, [fills.data])

  if (fills.loading && fills.data.length === 0) {
    return (
      <ChartContainer
        title="Cumulative PnL (fees)"
        lastUpdated={fills.lastUpdated}
        height="260px"
        loading={fills.loading}
      >
        <LoadingState rows={5} height="100%" />
      </ChartContainer>
    )
  }

  if (fills.error && fills.data.length === 0) {
    return (
      <ChartContainer
        title="Cumulative PnL (fees)"
        lastUpdated={fills.lastUpdated}
        height="260px"
        loading={fills.loading}
      >
        <ErrorState message={fills.error} onRetry={fills.refetch} height="100%" />
      </ChartContainer>
    )
  }

  if (chartData.length === 0) {
    return (
      <ChartContainer
        title="Cumulative PnL (fees)"
        lastUpdated={fills.lastUpdated}
        height="260px"
        loading={fills.loading}
      >
        <div className="text-text-dim font-mono text-xs text-center py-4">No fill data yet</div>
      </ChartContainer>
    )
  }

  return (
    <ChartContainer
      title="Cumulative PnL (fees)"
      lastUpdated={fills.lastUpdated}
      height="260px"
      loading={fills.loading}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.0} />
            </linearGradient>
          </defs>

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
            tickFormatter={(v) => '$' + v.toFixed(4)}
          />
          <ReferenceLine y={0} stroke="#222632" strokeWidth={1} />
          <Tooltip
            contentStyle={{ background: '#181b24', border: '1px solid #222632', borderRadius: '2px', fontSize: '11px' }}
            formatter={(value) => ['$' + value.toFixed(4), 'PnL']}
          />
          <Area
            dataKey="pnl"
            stroke="#3b82f6"
            strokeWidth={1.5}
            fill="url(#pnlGradient)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
