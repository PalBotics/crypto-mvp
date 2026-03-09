import RiskEventsTable from '../components/panels/RiskEventsTable'
import useHealth from '../hooks/useHealth'
import useRunSummary from '../hooks/useRunSummary'
import StatusDot from '../components/common/StatusDot'
import LoadingState, { ErrorState } from '../components/common/Loading'
import { toLocalTime } from '../utils/format'

export default function Health() {
  const health = useHealth()
  const summary = useRunSummary()

  const healthStatus =
    health.data?.status === 'ok' ? 'ok' : health.error ? 'error' : health.loading ? 'stale' : 'stale'

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="card p-3 flex flex-col gap-2">
          <span className="label">API Health</span>
          <StatusDot status={healthStatus} label={healthStatus} />

          <div className="flex justify-between items-center">
            <span className="label">Last response</span>
            <span className="font-mono text-xs text-text-secondary">{toLocalTime(health.lastUpdated)}</span>
          </div>
        </div>

        <div className="card p-3 flex flex-col gap-2">
          <span className="label">Run Summary</span>

          {summary.loading && <LoadingState rows={3} />}

          {summary.error && <ErrorState message={summary.error} onRetry={summary.refetch} />}

          {!summary.loading && !summary.error && summary.data && (
            <>
              <div className="flex justify-between items-center">
                <span className="label">Open Positions</span>
                <span className="font-mono text-xs text-text-primary">{summary.data.open_position_count}</span>
              </div>

              <div className="flex justify-between items-center">
                <span className="label">Total Fills</span>
                <span className="font-mono text-xs text-text-primary">{summary.data.total_fills}</span>
              </div>

              <div className="flex justify-between items-center">
                <span className="label">Risk Events</span>
                <span className="font-mono text-xs text-text-primary">{summary.data.total_risk_events}</span>
              </div>

              <div className="flex justify-between items-center">
                <span className="label">Net PnL</span>
                <span className="font-mono text-xs text-text-primary">{summary.data.net_pnl}</span>
              </div>
            </>
          )}
        </div>
      </div>

      <RiskEventsTable />
    </div>
  )
}