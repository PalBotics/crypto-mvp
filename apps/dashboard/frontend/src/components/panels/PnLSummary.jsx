import usePnL from '../../hooks/usePnL'
import useRunSummary from '../../hooks/useRunSummary'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatUSD, signColor } from '../../utils/format'

export default function PnLSummary() {
  const pnl = usePnL()
  const summary = useRunSummary()

  return (
    <div className="card p-3 flex flex-col gap-3">
      <div className="flex justify-between items-center">
        <span className="label">PnL Summary</span>
      </div>

      {pnl.loading && <LoadingState rows={4} />}

      {pnl.error && <ErrorState message={pnl.error} onRetry={pnl.refetch} />}

      {!pnl.loading && !pnl.error && pnl.data && (
        <>
          <div className="flex justify-between items-center">
            <span className="label">Realized PnL</span>
            <span className={`font-mono text-xs ${signColor(pnl.data.total_realized_pnl)}`}>
              {formatUSD(pnl.data.total_realized_pnl)}
            </span>
          </div>

          <div className="flex justify-between items-center">
            <span className="label">Unrealized PnL</span>
            <span className={`font-mono text-xs ${signColor(pnl.data.total_unrealized_pnl)}`}>
              {formatUSD(pnl.data.total_unrealized_pnl)}
            </span>
          </div>

          <div className="flex justify-between items-center">
            <span className="label">Funding Paid</span>
            <span className={`font-mono text-xs ${signColor(pnl.data.total_funding_paid)}`}>
              {formatUSD(pnl.data.total_funding_paid)}
            </span>
          </div>

          <div className="flex justify-between items-center border-t border-border pt-2 mt-1">
            <span className="label">Net PnL</span>
            <span className={`font-mono text-xs font-semibold ${signColor(pnl.data.net_pnl)}`}>
              {formatUSD(pnl.data.net_pnl)}
            </span>
          </div>

          <div className="flex justify-between items-center">
            <span className="label">Fills</span>
            <span className={`font-mono text-xs ${signColor(summary.data?.total_fills)}`}>
              {summary.data?.total_fills ?? '—'}
            </span>
          </div>
        </>
      )}
    </div>
  )
}
