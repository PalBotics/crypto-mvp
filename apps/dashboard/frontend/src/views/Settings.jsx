import useHealth from '../hooks/useHealth'
import useRunSummary from '../hooks/useRunSummary'
import LoadingState, { ErrorState } from '../components/common/Loading'
import { formatUSD } from '../utils/format'
import DepositPanel from '../components/panels/DepositPanel'

function InfoRow({ label, value, valueClassName = 'font-mono text-xs text-text-primary' }) {
  return (
    <div className="flex justify-between items-center py-1 border-b border-border/50">
      <span className="label">{label}</span>
      <span className={valueClassName}>{value}</span>
    </div>
  )
}

export default function Settings() {
  const health = useHealth()
  const summary = useRunSummary()

  const apiStatus = health.data?.status ?? '—'
  const apiStatusClass =
    health.data?.status === 'ok' ? 'text-green font-mono text-xs' : 'text-red font-mono text-xs'

  return (
    <div className="flex flex-col gap-4">
      <div className="card p-4 flex flex-col gap-3">
        <span className="label">System Info</span>
        <InfoRow label="Strategy" value="market_making" />
        <InfoRow label="Exchange" value="kraken_futures" />
        <InfoRow label="Symbol" value="XBTUSD" />
        <InfoRow label="Account" value="paper_mm" />
        <InfoRow label="Mode" value="paper trading" />
        <InfoRow label="API Status" value={apiStatus} valueClassName={apiStatusClass} />
      </div>

      <DepositPanel />

      <div className="card p-4 flex flex-col gap-3">
        <span className="label">Run Statistics</span>

        {summary.loading && <LoadingState rows={4} />}

        {summary.error && <ErrorState message={summary.error} onRetry={summary.refetch} />}

        {!summary.loading && !summary.error && summary.data && (
          <>
            <InfoRow label="Account Name" value={summary.data.account_name} />
            <InfoRow label="Open Positions" value={String(summary.data.open_position_count)} />
            <InfoRow label="Total Fills" value={String(summary.data.total_fills)} />
            <InfoRow label="Risk Events" value={String(summary.data.total_risk_events)} />
            <InfoRow label="Realized PnL" value={formatUSD(summary.data.realized_pnl)} />
            <InfoRow label="Unrealized PnL" value={formatUSD(summary.data.unrealized_pnl)} />
            <InfoRow label="Net PnL" value={formatUSD(summary.data.net_pnl)} />
          </>
        )}
      </div>

      <div className="card p-4 flex flex-col gap-3">
        <span className="label">About</span>
        <InfoRow label="Version" value="0.1.0" />
        <InfoRow label="Backend" value="http://localhost:8000" />
        <InfoRow label="Frontend" value="Vite + React + Tailwind + Recharts" />
        <InfoRow label="Dashboard" value="crypto-mvp dashboard" />
      </div>
    </div>
  )
}