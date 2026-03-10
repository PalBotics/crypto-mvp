import useHealth from '../../hooks/useHealth'
import useRunSummary from '../../hooks/useRunSummary'
import StatusDot from '../common/StatusDot'
import TimeAgo from '../common/TimeAgo'

function formatSnapshotAge(seconds) {
  if (seconds === null || seconds === undefined) {
    return '—'
  }

  const total = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(total / 60)
  const secs = total % 60

  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60)
    return `${hours}h ${minutes % 60}m ago`
  }

  return `${minutes}m ${secs}s ago`
}

function snapshotAgeClass(seconds) {
  if (seconds === null || seconds === undefined) return 'text-text-dim'
  if (seconds <= 90) return 'text-green'
  if (seconds <= 180) return 'text-yellow'
  return 'text-red'
}

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
        <StatusDot status={apiStatus} label="Collector" />
        <span className={`font-mono text-[10px] ${snapshotAgeClass(health.data?.last_snapshot_age_seconds)}`}>
          {formatSnapshotAge(health.data?.last_snapshot_age_seconds)}
        </span>
      </div>

      <div className="w-px h-4 bg-border" />

      <div className="flex items-center gap-2">
        <span className="text-text-secondary text-xs font-medium">last update</span>
        <TimeAgo timestamp={health.lastUpdated} staleAfter={120} />
      </div>
    </div>
  )
}
