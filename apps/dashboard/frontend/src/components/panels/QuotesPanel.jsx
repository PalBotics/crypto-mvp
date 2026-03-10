import { useEffect, useState } from 'react'

import useQuotes from '../../hooks/useQuotes'
import LoadingState, { ErrorState } from '../common/Loading'
import SideTag from '../common/SideTag'
import TimeAgo from '../common/TimeAgo'
import { formatUSD } from '../../utils/format'

const MAX_SPREAD_BPS = 70

function quoteProximity(distanceBps) {
  const parsed = parseFloat(distanceBps)
  if (Number.isNaN(parsed)) {
    return 0
  }

  const proximity = 1 - parsed / MAX_SPREAD_BPS
  return Math.max(0, Math.min(1, proximity))
}

function distanceText(quote) {
  if (quote.distance_usd === null || quote.distance_bps === null) {
    return 'Distance unavailable'
  }

  return `$${formatUSD(quote.distance_usd)} away (${formatUSD(quote.distance_bps)} bps)`
}

function quoteAge(isoTs) {
  const ms = Date.parse(isoTs)
  if (Number.isNaN(ms)) {
    return { text: '—', className: 'text-text-dim' }
  }

  const ageSec = Math.max(0, Math.floor((Date.now() - ms) / 1000))
  const minutes = Math.floor(ageSec / 60)
  const seconds = ageSec % 60
  const hours = Math.floor(minutes / 60)

  const text = hours > 0
    ? `${hours}h ${minutes % 60}m`
    : `${minutes}m ${seconds}s`

  if (ageSec < 60) {
    return { text, className: 'text-green' }
  }
  if (ageSec <= 90) {
    return { text, className: 'text-yellow' }
  }
  return { text, className: 'text-red' }
}

export default function QuotesPanel() {
  const quotes = useQuotes()
  const [, setTick] = useState(0)
  const liveQuotes = quotes.data ?? []
  const lastKnownQuotes = quotes.lastKnownData ?? []
  const usingLastKnown = liveQuotes.length === 0 && lastKnownQuotes.length > 0
  const displayQuotes = liveQuotes.length > 0 ? liveQuotes : lastKnownQuotes

  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="card p-3 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="label">Active Quotes</span>
        <TimeAgo timestamp={quotes.apiLastUpdated || quotes.lastUpdated} staleAfter={120} />
      </div>

      {quotes.loading && <LoadingState rows={3} />}
      {quotes.error && <ErrorState message={quotes.error} onRetry={quotes.refetch} />}

      {!quotes.loading && !quotes.error && displayQuotes.length === 0 && (
        <div className="bg-surface border border-border rounded-sm p-3">
          <div className="flex items-center justify-between mb-2">
            <SideTag side="BUY" size="xs" />
            <span className="text-text-dim text-[10px] font-mono uppercase">Awaiting first quote</span>
          </div>
          <div className="font-mono text-lg leading-none mb-2 text-text-dim">—</div>
          <div className="text-text-secondary text-xs mb-2">Awaiting first quote</div>
          <div className="w-full h-2 bg-muted rounded-sm overflow-hidden mb-2" />
          <div className="flex justify-between items-center">
            <span className="text-text-dim text-[10px] font-mono">0% proximity</span>
            <span className="text-[10px] font-mono text-text-dim">Quote Age: —</span>
          </div>
        </div>
      )}

      {!quotes.loading && !quotes.error && displayQuotes.length > 0 && (
        <div className="flex flex-col gap-3">
          {displayQuotes.map((quote, index) => {
            const side = String(quote.side || '').toUpperCase()
            const proximity = quoteProximity(quote.distance_bps)
            const fillPct = Math.round(proximity * 100)
            const fillColor = side === 'BUY' ? 'bg-blue' : 'bg-orange'
            const age = quoteAge(quote.created_ts)
            const statusLabel = usingLastKnown ? 'NOT QUOTING' : 'PENDING'
            const statusClass = usingLastKnown ? 'text-text-dim' : 'text-yellow'

            return (
              <div key={`${quote.created_ts}-${quote.side}-${index}`} className="bg-surface border border-border rounded-sm p-3">
                <div className="flex items-center justify-between mb-2">
                  <SideTag side={side} size="xs" />
                  <span className={`text-[10px] font-mono uppercase ${statusClass}`}>{statusLabel}</span>
                </div>

                <div className="font-mono text-lg leading-none mb-2">
                  {quote.limit_price ? `$${formatUSD(quote.limit_price)}` : '—'}
                </div>

                <div className="text-text-secondary text-xs mb-2">{distanceText(quote)}</div>

                <div className="w-full h-2 bg-muted rounded-sm overflow-hidden mb-2">
                  <div
                    className={`${fillColor} h-full transition-all duration-300`}
                    style={{ width: `${fillPct}%` }}
                  />
                </div>

                <div className="flex justify-between items-center">
                  <span className="text-text-dim text-[10px] font-mono">{fillPct}% proximity</span>
                  <span className={`text-[10px] font-mono ${age.className}`}>Quote Age: {age.text}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
