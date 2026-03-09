import useHealth from '../../hooks/useHealth'
import useRunSummary from '../../hooks/useRunSummary'
import StatusDot from '../common/StatusDot'
import TimeAgo from '../common/TimeAgo'

export default function SystemStatusBar() {
  const health = useHealth()
  const summary = useRunSummary()

  const apiStatus =
    health.data?.status === 'ok' ? 'ok' : health.error ? 'error' : health.loading ? 'stale' : 'stale'

  const dbStatus =
    health.data?.status === 'ok' ? 'ok' : health.error ? 'error' : health.loading ? 'stale' : 'stale'

  const paperTraderStatus = summary.data && !summary.error ? 'ok' : summary.error ? 'error' : summary.loading ? 'stale' : 'stale'

  return (
    <div className="bg-surface border border-border border-b border-border rounded-sm px-4 py-2 flex items-center gap-6">
      <div className="flex items-center gap-2">
        <StatusDot status={apiStatus} label="API" />
      </div>

      <div className="w-px h-4 bg-border" />

      <div className="flex items-center gap-2">
        <StatusDot status={paperTraderStatus} label="Paper Trader" />
      </div>

      <div className="w-px h-4 bg-border" />

      <div className="flex items-center gap-2">
        <StatusDot status={dbStatus} label="DB" />
      </div>

      <div className="w-px h-4 bg-border" />

      <div className="flex items-center gap-2">
        <span className="text-text-secondary text-xs font-medium">last update</span>
        <TimeAgo timestamp={health.lastUpdated} staleAfter={120} />
      </div>
    </div>
  )
}
