import { useMemo } from 'react'
import useApi from '../../hooks/useApi'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatUSD, toLocalTime } from '../../utils/format'
import { buildDnTradesFromFills, enrichDnTrades } from '../../utils/dnTrades'

const POLL_MS = 60000

function formatDuration(hours) {
  if (!(hours > 0)) return '0m'
  const totalMinutes = Math.round(hours * 60)
  const h = Math.floor(totalMinutes / 60)
  const m = totalMinutes % 60
  if (h <= 0) return `${m}m`
  return `${h}h ${m}m`
}

function resultColor(result) {
  if (result === 'ACTIVE') return '#854F0B'
  if (result === 'POSITIVE') return '#3B6D11'
  if (result === 'NEGATIVE') return '#A32D2D'
  return '#555a6a'
}

function rowTint(result) {
  if (result === 'POSITIVE') return { backgroundColor: 'rgba(59,109,17,0.10)' }
  if (result === 'NEGATIVE') return { backgroundColor: 'rgba(163,45,45,0.10)' }
  return null
}

export default function DnTradeHistory({ account = 'paper_dn' }) {
  const fills = useApi(`/api/runs/${account}/fills?limit=100`, { interval: POLL_MS })
  const pnl = useApi(`/api/runs/${account}/pnl`, { interval: POLL_MS })

  const trades = useMemo(() => {
    try {
      const raw = buildDnTradesFromFills(Array.isArray(fills.data) ? fills.data : [])
      const enriched = enrichDnTrades(raw, pnl.data)
      return Array.isArray(enriched) ? enriched : []
    } catch {
      return []
    }
  }, [fills.data, pnl.data])

  const loading = (fills.loading || pnl.loading) && !fills.data
  const error = fills.error || pnl.error

  return (
    <div className="card flex flex-col">
      <div className="flex items-center justify-between px-3 pt-3 pb-2 border-b border-border">
        <span className="label">Trade History</span>
        <span className="font-mono text-[10px] text-text-dim">{trades.length}</span>
      </div>

      {loading && <LoadingState rows={6} />}
      {error && <ErrorState message={error} onRetry={() => { fills.refetch(); pnl.refetch() }} />}

      {!loading && !error && trades.length === 0 && (
        <div className="text-text-dim font-mono text-xs text-center py-5">No completed trades yet — waiting for first entry</div>
      )}

      {!loading && !error && trades.length > 0 && (
        <div className="w-full overflow-auto" style={{ maxHeight: '320px' }}>
          <table className="w-full border-collapse text-xs min-w-max">
            <thead className="sticky top-0 z-10">
              <tr className="bg-surface border-b border-border">
                {['Entry Time', 'Exit Time', 'Duration', 'Entry Price', 'Exit Price', 'Funding Earned', 'Fees', 'Net PnL', 'Result'].map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-medium text-text-dim whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...trades].reverse().map((trade, idx) => (
                <tr key={`${trade.entryTime?.toISOString() || idx}-${idx}`} className="border-b border-border/50" style={rowTint(trade.result) || undefined}>
                  <td className="px-3 py-2 font-mono text-text-secondary whitespace-nowrap">{trade.entryTime ? toLocalTime(trade.entryTime.toISOString()) : '—'}</td>
                  <td className="px-3 py-2 font-mono text-text-secondary whitespace-nowrap">{trade.exitTime ? toLocalTime(trade.exitTime.toISOString()) : 'open'}</td>
                  <td className="px-3 py-2 font-mono text-text-primary whitespace-nowrap">{formatDuration(trade.durationHours)}</td>
                  <td className="px-3 py-2 font-mono text-text-primary whitespace-nowrap">{formatUSD(trade.entryPrice)}</td>
                  <td className="px-3 py-2 font-mono text-text-primary whitespace-nowrap">{trade.exitTime ? formatUSD(trade.exitPrice) : 'open'}</td>
                  <td className="px-3 py-2 font-mono text-green whitespace-nowrap">{formatUSD(trade.fundingEarned)}</td>
                  <td className="px-3 py-2 font-mono text-red whitespace-nowrap">{formatUSD(trade.fees)}</td>
                  <td className="px-3 py-2 font-mono whitespace-nowrap" style={{ color: resultColor(trade.result) }}>{formatUSD(trade.netPnl)}</td>
                  <td className="px-3 py-2 font-mono whitespace-nowrap" style={{ color: resultColor(trade.result) }}>{trade.result}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
