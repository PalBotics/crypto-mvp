import useFillDrought from '../../hooks/useFillDrought'
import LoadingState, { ErrorState } from '../common/Loading'

function droughtColor(hoursSinceFill) {
  if (hoursSinceFill === null || hoursSinceFill === undefined) {
    return 'text-text-dim'
  }
  if (hoursSinceFill < 2) {
    return 'text-green'
  }
  if (hoursSinceFill <= 8) {
    return 'text-yellow'
  }
  return 'text-red'
}

function formatSince(hoursSinceFill) {
  if (hoursSinceFill === null || hoursSinceFill === undefined) {
    return 'No fills yet'
  }

  const totalSeconds = Math.max(0, Math.floor(hoursSinceFill * 3600))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)

  if (hours > 0) {
    return `${hours}h ${minutes}m since last fill`
  }

  return `${minutes}m ${totalSeconds % 60}s since last fill`
}

export default function FillDroughtPanel() {
  const drought = useFillDrought()

  return (
    <div className="card p-3 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="label">Fill Activity</span>
      </div>

      {drought.loading && !drought.data && <LoadingState rows={3} />}
      {drought.error && !drought.data && <ErrorState message={drought.error} onRetry={drought.refetch} />}

      {drought.data && (
        <>
          <div className={`font-mono text-2xl font-semibold text-center py-4 ${droughtColor(drought.data.hours_since_fill)}`}>
            {formatSince(drought.data.hours_since_fill)}
          </div>
          <div className="text-center text-text-secondary text-xs font-mono">
            Today: {drought.data.fill_count_today ?? 0} fills  Total: {drought.data.fill_count_total ?? 0} fills
          </div>
        </>
      )}
    </div>
  )
}
