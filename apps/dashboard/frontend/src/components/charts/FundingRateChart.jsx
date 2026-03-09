import { useMemo } from 'react'
import { useFundingRates } from '../../hooks/useMarket'
import ChartContainer from './ChartContainer'
import { LoadingState, ErrorState } from '../common/Loading'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  Cell,
} from 'recharts'

export default function FundingRateChart() {
  const funding = useFundingRates()

  const chartData = useMemo(() => {
    return (funding.data ?? [])
      .map((item) => {
        const rate = parseFloat(item.funding_rate)

        return {
          time: new Date(item.event_ts).toLocaleTimeString(),
          rate,
          color: rate >= 0 ? '#22c55e' : '#ef4444',
        }
      })
      .reverse()
  }, [funding.data])

  if (funding.loading && funding.data.length === 0) {
    return (
      <ChartContainer
        title="Funding Rate"
        lastUpdated={funding.lastUpdated}
        height="180px"
        loading={funding.loading}
      >
        <LoadingState rows={3} height="100%" />
      </ChartContainer>
    )
  }

  if (funding.error && funding.data.length === 0) {
    return (
      <ChartContainer
        title="Funding Rate"
        lastUpdated={funding.lastUpdated}
        height="180px"
        loading={funding.loading}
      >
        <ErrorState message={funding.error} onRetry={funding.refetch} height="100%" />
      </ChartContainer>
    )
  }

  return (
    <ChartContainer
      title="Funding Rate"
      lastUpdated={funding.lastUpdated}
      height="180px"
      loading={funding.loading}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
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
            tickFormatter={(v) => v.toFixed(6)}
          />
          <ReferenceLine y={0} stroke="#222632" strokeWidth={1} />
          <Tooltip
            contentStyle={{ background: '#181b24', border: '1px solid #222632', borderRadius: '2px', fontSize: '11px' }}
            formatter={(value) => [value.toFixed(6), 'Rate']}
          />
          <Bar dataKey="rate" radius={[2, 2, 0, 0]}>
            {chartData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
