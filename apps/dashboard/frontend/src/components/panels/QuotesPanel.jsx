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

export default function QuotesPanel() {
  const quotes = useQuotes()

  return (
    <div className="card p-3 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="label">Active Quotes</span>
        <TimeAgo timestamp={quotes.apiLastUpdated || quotes.lastUpdated} staleAfter={120} />
      </div>

      {quotes.loading && <LoadingState rows={3} />}
      {quotes.error && <ErrorState message={quotes.error} onRetry={quotes.refetch} />}

      {!quotes.loading && !quotes.error && quotes.data.length === 0 && (
        <div className="text-text-dim font-mono text-xs py-4 text-center">No active quotes</div>
      )}

      {!quotes.loading && !quotes.error && quotes.data.length > 0 && (
        <div className="flex flex-col gap-3">
          {quotes.data.map((quote, index) => {
            const side = String(quote.side || '').toUpperCase()
            const proximity = quoteProximity(quote.distance_bps)
            const fillPct = Math.round(proximity * 100)
            const fillColor = side === 'BUY' ? 'bg-blue' : 'bg-orange'

            return (
              <div key={`${quote.created_ts}-${quote.side}-${index}`} className="bg-surface border border-border rounded-sm p-3">
                <div className="flex items-center justify-between mb-2">
                  <SideTag side={side} size="xs" />
                  <span className="text-text-dim text-[10px] font-mono uppercase">{quote.status}</span>
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
                  <TimeAgo timestamp={quote.created_ts} staleAfter={300} />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
