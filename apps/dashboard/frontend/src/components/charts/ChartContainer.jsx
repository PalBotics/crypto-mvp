import { Spinner } from '../common/Loading'
import TimeAgo from '../common/TimeAgo'

export default function ChartContainer({ title, children, loading = false, lastUpdated = null, height = '220px', actions, staleAfter = 120 }) {
  const isStale = lastUpdated
    ? (Date.now() - Date.parse(lastUpdated)) / 1000 > staleAfter
    : false

  return (
    <div className={`card flex flex-col ${isStale ? 'border-yellow/30' : ''}`}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <span className="text-text-secondary text-xs font-medium tracking-wide">{title}</span>
        <div className="flex items-center gap-2">
          {actions}
          {lastUpdated && <TimeAgo timestamp={lastUpdated} staleAfter={staleAfter} />}
          {loading && <Spinner size={11} />}
        </div>
      </div>
      <div style={{ height }}>
        {children}
      </div>
    </div>
  )
}