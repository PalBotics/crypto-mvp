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
    return { text: '-', className: 'text-text-dim' }
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

function QuoteCard({ quote, isLive }) {
  const side = String(quote.side || '').toUpperCase()
  const proximity = quoteProximity(quote.distance_bps)
  const fillPct = Math.round(proximity * 100)
  const fillColor = side === 'BUY' ? 'bg-blue' : 'bg-orange'
  const age = quoteAge(quote.created_ts)
  const statusLabel = isLive ? 'PENDING' : 'NOT QUOTING'
  const statusClass = isLive ? 'text-yellow' : 'text-text-dim'

  return (
    <div className="bg-surface border border-border rounded-sm p-3">
      <div className="flex items-center justify-between mb-2">
        <SideTag side={side} size="xs" />
        <span className={`text-[10px] font-mono uppercase ${statusClass}`}>{statusLabel}</span>
      </div>

      <div className="font-mono text-lg leading-none mb-2">
        {quote.limit_price ? `$${formatUSD(quote.limit_price)}` : '-'}
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
}

export default function QuotesPanel() {
  const { data, lastKnown, apiLastUpdated, loading, error, lastUpdated, refetch } = useQuotes()
  const [, setTick] = useState(0)
  const isLive = data.length > 0
  const displayQuotes = isLive ? data : lastKnown
  const buyQuote = displayQuotes.find((q) => q.side === 'buy')
  const sellQuote = displayQuotes.find((q) => q.side === 'sell')

  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="card p-3 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="label">Quotes</span>
        <TimeAgo timestamp={apiLastUpdated || lastUpdated} staleAfter={120} />
      </div>

      {loading && <LoadingState rows={3} />}
      {error && <ErrorState message={error} onRetry={refetch} />}

      {!loading && !error && (
        <div className="flex flex-col gap-3">
          {buyQuote ? (
            <QuoteCard quote={buyQuote} isLive={isLive} />
          ) : (
            <div className="bg-surface border border-border rounded-sm p-3">
              <div className="flex items-center justify-between mb-2">
                <SideTag side="BUY" size="xs" />
                <span className="text-text-dim text-[10px] font-mono uppercase">Awaiting first quote</span>
              </div>
              <div className="font-mono text-lg leading-none mb-2 text-text-dim">BUY - Awaiting first quote</div>
              <div className="text-text-secondary text-xs mb-2">Awaiting first quote</div>
              <div className="w-full h-2 bg-muted rounded-sm overflow-hidden mb-2" />
              <div className="flex justify-between items-center">
                <span className="text-text-dim text-[10px] font-mono">0% proximity</span>
                <span className="text-[10px] font-mono text-text-dim">Quote Age: -</span>
              </div>
            </div>
          )}

          {sellQuote && <QuoteCard quote={sellQuote} isLive={isLive} />}
        </div>
      )}
    </div>
  )
}
