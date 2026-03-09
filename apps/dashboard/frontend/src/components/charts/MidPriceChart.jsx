import { useMemo } from 'react'
import { useTicks, useOrderBooks } from '../../hooks/useMarket'
import ChartContainer from './ChartContainer'
import { LoadingState, ErrorState } from '../common/Loading'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  CartesianGrid,
} from 'recharts'

export default function MidPriceChart() {
  const ticks = useTicks()
  const orderBooks = useOrderBooks()

  const chartData = useMemo(() => {
    return (ticks.data ?? [])
      .map((item) => ({
        time: new Date(item.event_ts).toLocaleTimeString(),
        mid: parseFloat(item.mid_price),
        bid: parseFloat(item.bid_price),
        ask: parseFloat(item.ask_price),
      }))
      .reverse()
  }, [ticks.data])

  const latestOrderBookMid = useMemo(() => {
    const latest = orderBooks.data?.[0]
    if (!latest || latest.mid_price === null || latest.mid_price === undefined) {
      return null
    }

    const value = parseFloat(latest.mid_price)
    return Number.isNaN(value) ? null : value
  }, [orderBooks.data])

  if (ticks.loading && ticks.data.length === 0) {
    return (
      <ChartContainer title="Mid Price" lastUpdated={ticks.lastUpdated} height="260px" loading={ticks.loading}>
        <LoadingState rows={5} height="100%" />
      </ChartContainer>
    )
  }

  if (ticks.error && ticks.data.length === 0) {
    return (
      <ChartContainer title="Mid Price" lastUpdated={ticks.lastUpdated} height="260px" loading={ticks.loading}>
        <ErrorState message={ticks.error} onRetry={ticks.refetch} height="100%" />
      </ChartContainer>
    )
  }

  return (
    <ChartContainer title="Mid Price" lastUpdated={ticks.lastUpdated} height="260px" loading={ticks.loading}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
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
            width={70}
            tickFormatter={(v) => '$' + v.toLocaleString()}
            domain={['auto', 'auto']}
          />
          <Tooltip
            contentStyle={{ background: '#181b24', border: '1px solid #222632', borderRadius: '2px', fontSize: '11px' }}
            labelStyle={{ color: '#8b90a0' }}
            formatter={(value) => ['$' + value.toFixed(2)]}
          />
          {latestOrderBookMid !== null && <ReferenceLine y={latestOrderBookMid} stroke="#334155" strokeDasharray="2 2" />}
          <Line dataKey="mid" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="Mid" />
          <Line dataKey="bid" stroke="#22c55e" strokeWidth={1} dot={false} strokeDasharray="3 3" name="Bid" />
          <Line dataKey="ask" stroke="#ef4444" strokeWidth={1} dot={false} strokeDasharray="3 3" name="Ask" />
        </LineChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}
