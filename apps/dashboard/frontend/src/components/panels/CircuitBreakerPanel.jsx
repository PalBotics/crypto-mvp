import { toLocalTime } from '../../utils/format'

const EXCHANGES = ['kraken', 'coinbase_advanced', 'kraken_futures']

function statusForBreaker(breaker) {
  const state = String(breaker?.state ?? 'closed').toLowerCase()
  const failures = Number(breaker?.failure_count ?? 0)

  if (state === 'open') {
    return { dot: 'error', text: 'OPEN - BLOCKING', tone: 'text-red' }
  }

  if (state === 'half_open') {
    return { dot: 'stale', text: 'TESTING', tone: 'text-yellow' }
  }

  if (failures > 0) {
    return { dot: 'stale', text: `DEGRADED (${failures} failures)`, tone: 'text-yellow' }
  }

  return { dot: 'ok', text: 'HEALTHY', tone: 'text-green' }
}

function openElapsedLabel(breaker) {
  if (!breaker || String(breaker.state).toLowerCase() !== 'open') {
    return null
  }

  const ts = breaker?.opened_at || breaker?.last_canary_at || null
  if (!ts) return null

  const opened = new Date(ts)
  if (Number.isNaN(opened.getTime())) return null

  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - opened.getTime()) / 1000))
  const mins = Math.floor(elapsedSeconds / 60)
  const secs = elapsedSeconds % 60
  return `open ${mins}m ${secs}s`
}

export default function CircuitBreakerPanel({ systemStatus }) {
  const list = systemStatus?.circuit_breakers ?? []
  const byExchange = new Map(list.map((item) => [item.exchange, item]))

  const rows = EXCHANGES.map((exchange) => {
    const breaker = byExchange.get(exchange) ?? {
      exchange,
      state: 'closed',
      failure_count: 0,
    }

    const failureCount = Number(breaker.failure_count ?? 0)
    const failureLabel = `${failureCount} ${failureCount === 1 ? 'failure' : 'failures'}`
    const status = statusForBreaker(breaker)
    const elapsed = openElapsedLabel(breaker)

    return {
      exchange,
      breaker,
      failureLabel,
      status,
      elapsed,
    }
  })

  return (
    <div className="card p-3 flex flex-col gap-3">
      <span className="label">CIRCUIT BREAKERS</span>

      <div className="flex flex-col gap-2">
        {rows.map(({ exchange, breaker, status, failureLabel, elapsed }) => (
          <div key={exchange} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 items-center">
            <span className="font-mono text-xs text-text-primary">{exchange}</span>

            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  status.dot === 'ok'
                    ? 'bg-green'
                    : status.dot === 'error'
                      ? 'bg-red'
                      : 'bg-yellow'
                }`}
              />
              <span className={`font-mono text-[11px] ${status.tone}`}>{status.text}</span>
              {elapsed && <span className="font-mono text-[11px] text-red">{elapsed}</span>}
            </div>

            <span className="font-mono text-[11px] text-text-secondary">{failureLabel}</span>
          </div>
        ))}
      </div>

      <div className="border-t border-border pt-2">
        <span className="text-text-dim text-[10px] font-mono">
          Last status snapshot: {toLocalTime(systemStatus?.last_updated || null)}
        </span>
      </div>
    </div>
  )
}
