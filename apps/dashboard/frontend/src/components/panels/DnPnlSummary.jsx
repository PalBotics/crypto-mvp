import useApi from '../../hooks/useApi'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatUSD, toLocalTime, signColor } from '../../utils/format'
import { buildDnTradesFromFills, enrichDnTrades } from '../../utils/dnTrades'

const POLL_MS = 30000

export default function DnPnlSummary({ account = 'paper_dn', badge = 'PAPER' }) {
  const pnl = useApi(`/api/runs/${account}/pnl`, { interval: POLL_MS })
  const summary = useApi(`/api/runs/${account}/summary`, { interval: POLL_MS })
  const fills = useApi(`/api/runs/${account}/fills?limit=100`, { interval: POLL_MS })

  const rows = Array.isArray(fills.data) ? fills.data : []
  let trades = []
  try {
    const enriched = enrichDnTrades(buildDnTradesFromFills(rows), pnl.data)
    trades = Array.isArray(enriched) ? enriched : []
  } catch {
    trades = []
  }
  const activeTrade = trades.find((t) => t.isActive)
  const lastClosed = [...trades].reverse().find((t) => !t.isActive && t.exitTime)

  let statusText = 'No positions yet'
  if (Number(summary.data?.open_position_count ?? 0) > 0 && activeTrade?.entryTime) {
    statusText = `In position since ${toLocalTime(activeTrade.entryTime.toISOString())}`
  } else if (lastClosed?.exitTime) {
    statusText = `Last position closed ${toLocalTime(lastClosed.exitTime.toISOString())}`
  } else if (rows.length > 0) {
    statusText = `Last position closed ${toLocalTime(rows[0].fill_ts)}`
  }

  const loading = (pnl.loading || summary.loading || fills.loading) && !pnl.data
  const error = pnl.error || summary.error || fills.error

  if (loading) {
    return (
      <div className="card p-3 flex flex-col gap-3">
        <div className="flex justify-between items-center">
          <span className="label">PNL SUMMARY</span>
        </div>
        <LoadingState rows={6} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="card p-3 flex flex-col gap-3">
        <div className="flex justify-between items-center">
          <span className="label">PNL SUMMARY</span>
        </div>
        <ErrorState message={error} onRetry={() => { pnl.refetch(); summary.refetch(); fills.refetch() }} />
      </div>
    )
  }

  return (
    <div className="card p-3 flex flex-col gap-3">
      <div className="flex justify-between items-center">
        <span className="label">PNL SUMMARY</span>
        <span className={`font-mono text-[10px] px-2 py-0.5 rounded border ${badge === 'LIVE' ? 'text-orange border-orange/40' : 'text-blue border-blue/40'}`}>
          {badge}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="flex flex-col gap-2">
          <div className="flex justify-between items-center">
            <span className="label">REALIZED PNL</span>
            <span className={`font-mono text-xs ${signColor(pnl.data?.total_realized_pnl)}`}>{formatUSD(pnl.data?.total_realized_pnl)}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="label">FUNDING ACCRUED</span>
            <span className="font-mono text-xs text-green">{formatUSD(pnl.data?.total_accrued_not_yet_settled)}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="label">FEES PAID</span>
            <span className="font-mono text-xs text-red">{formatUSD(pnl.data?.total_funding_paid)}</span>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex justify-between items-center border-b border-border pb-1">
            <span className="label">NET PNL</span>
            <span className={`font-mono text-sm font-semibold ${signColor(pnl.data?.net_pnl)}`}>{formatUSD(pnl.data?.net_pnl)}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="label">TOTAL FILLS</span>
            <span className="font-mono text-xs text-text-primary">{summary.data?.total_fills ?? '—'}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="label">OPEN POSITIONS</span>
            <span className="font-mono text-xs text-text-primary">{summary.data?.open_position_count ?? '—'}</span>
          </div>
        </div>
      </div>

      <div className="border-t border-border pt-2">
        <span className="label">STATUS: </span>
        <span className="font-mono text-xs text-text-secondary">{statusText}</span>
      </div>
    </div>
  )
}
