import { useState } from 'react'
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
  const [resetLoading, setResetLoading] = useState(false)
  const [resetSuccess, setResetSuccess] = useState('')
  const [resetError, setResetError] = useState('')

  const apiStatus = health.data?.status ?? '—'
  const apiStatusClass =
    health.data?.status === 'ok' ? 'text-green font-mono text-xs' : 'text-red font-mono text-xs'

  async function handleResetPaperTrader() {
    const confirmed = window.confirm(
      'Are you sure? This will permanently delete all fills, positions, and risk events for paper_mm. This cannot be undone.'
    )
    if (!confirmed) {
      return
    }

    setResetLoading(true)
    setResetSuccess('')
    setResetError('')

    try {
      const response = await fetch('/api/runs/paper_mm/reset', {
        method: 'POST',
      })

      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        throw new Error(body.detail ?? 'Reset failed')
      }

      setResetSuccess('Reset complete. All trading history cleared.')
      summary.refetch()
      health.refetch()
    } catch (err) {
      setResetError(err instanceof Error ? err.message : String(err))
    } finally {
      setResetLoading(false)
    }
  }

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

      <div className="card p-4 flex flex-col gap-3 border border-red/50 bg-red/10">
        <span className="label text-red">Danger Zone</span>
        <div className="flex flex-col gap-1">
          <span className="font-mono text-xs text-text-primary">Reset Paper Trader</span>
          <span className="font-mono text-xs text-text-secondary">
            Clears all fills, positions, and risk events for the paper_mm account. Deposits are
            preserved. This cannot be undone.
          </span>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleResetPaperTrader}
            disabled={resetLoading}
            className="px-3 py-1 rounded-sm text-xs font-mono border border-red/60 text-red bg-red/20 hover:bg-red/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {resetLoading ? 'Resetting...' : 'Reset'}
          </button>
          {resetSuccess && <span className="text-green font-mono text-xs">{resetSuccess}</span>}
          {resetError && <span className="text-red font-mono text-xs">{resetError}</span>}
        </div>
      </div>
    </div>
  )
}