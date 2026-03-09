import { useMemo } from 'react'
import useFills from '../../hooks/useFills'
import ChartContainer from './ChartContainer'
import { LoadingState, ErrorState } from '../common/Loading'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  Cell,
} from 'recharts'

function formatHourLabel(date) {
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  const hh = String(date.getHours()).padStart(2, '0')
  return `${mm}/${dd} ${hh}:00`
}

export default function FillRateChart() {
  const fills = useFills(200)

  const chartData = useMemo(() => {
    const buckets = new Map()

    for (const fill of fills.data ?? []) {
      const ts = new Date(fill.fill_ts)
      if (Number.isNaN(ts.getTime())) {
        continue
      }

      const bucketStart = new Date(ts)
      bucketStart.setMinutes(0, 0, 0)

      const key = bucketStart.getTime()
      const current = buckets.get(key) ?? {
        hour: formatHourLabel(bucketStart),
        buy: 0,
        sell: 0,
        _ts: key,
      }

      if (String(fill.side).toUpperCase() === 'BUY') {
        current.buy += 1
      } else if (String(fill.side).toUpperCase() === 'SELL') {
        current.sell += 1
      }

      buckets.set(key, current)
    }

    return [...buckets.values()]
      .sort((a, b) => a._ts - b._ts)
      .slice(-24)
      .map(({ _ts, ...row }) => row)
  }, [fills.data])

  if (fills.loading && fills.data.length === 0) {
    return (
      <ChartContainer
        title="Fill Rate (per hour)"
        lastUpdated={fills.lastUpdated}
        height="200px"
        loading={fills.loading}
      >
        <LoadingState rows={4} height="100%" />
      </ChartContainer>
    )
  }

  if (fills.error && fills.data.length === 0) {
    return (
      <ChartContainer
        title="Fill Rate (per hour)"
        lastUpdated={fills.lastUpdated}
        height="200px"
        loading={fills.loading}
      >
        <ErrorState message={fills.error} onRetry={fills.refetch} height="100%" />
      </ChartContainer>
    )
  }

  if (chartData.length === 0) {
    return (
      <ChartContainer
        title="Fill Rate (per hour)"
        lastUpdated={fills.lastUpdated}
        height="200px"
        loading={fills.loading}
      >
        <div className="text-text-dim font-mono text-xs text-center py-4">No fill data</div>
      </ChartContainer>
    )
  }

  return (
    <ChartContainer
      title="Fill Rate (per hour)"
      lastUpdated={fills.lastUpdated}
      height="200px"
      loading={fills.loading}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <XAxis
            dataKey="hour"
            tick={{ fill: '#555a6a', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: '#555a6a', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            width={30}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={{ background: '#181b24', border: '1px solid #222632', borderRadius: '2px', fontSize: '11px' }}
          />
          <Legend wrapperStyle={{ fontSize: '11px', color: '#8b90a0' }} />
          <Bar dataKey="buy" name="Buy" fill="#3b82f6" radius={[2, 2, 0, 0]}>
            {chartData.map((entry, index) => (
              <Cell key={`buy-${entry.hour}-${index}`} fill="#3b82f6" />
            ))}
          </Bar>
          <Bar dataKey="sell" name="Sell" fill="#f97316" radius={[2, 2, 0, 0]}>
            {chartData.map((entry, index) => (
              <Cell key={`sell-${entry.hour}-${index}`} fill="#f97316" />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
