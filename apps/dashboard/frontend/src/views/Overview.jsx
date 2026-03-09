import useRunSummary from '../hooks/useRunSummary'
import useHealth from '../hooks/useHealth'
import { formatUSD } from '../utils/format'

export default function Overview() {
  const health = useHealth()
  const summary = useRunSummary()

  console.log('health:', health)
  console.log('summary:', summary)

  return (
    <div className="text-text-secondary font-mono text-xs">
      <h2>Data Layer Smoke Test</h2>
      <div>health.loading: {String(health.loading)}</div>
      <div>health.error: {health.error ?? '—'}</div>
      <div>health.status: {health.data?.status ?? '—'}</div>
      <div>summary.loading: {String(summary.loading)}</div>
      <div>summary.error: {summary.error ?? '—'}</div>
      <div>summary.net_pnl: {formatUSD(summary.data?.net_pnl)}</div>
      <div>summary.total_fills: {summary.data?.total_fills ?? '—'}</div>
    </div>
  )
}