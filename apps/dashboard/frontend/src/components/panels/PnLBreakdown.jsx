import usePnL from '../../hooks/usePnL'
import useRunSummary from '../../hooks/useRunSummary'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatUSD, signColor } from '../../utils/format'

export default function PnLBreakdown({ middleContent = null }) {
  const pnl = usePnL()
  const summary = useRunSummary()

  const showPlaceholderValues = pnl.loading || !!pnl.error

  const realizedValue = showPlaceholderValues ? '—' : formatUSD(pnl.data?.total_realized_pnl)
  const unrealizedValue = showPlaceholderValues ? '—' : formatUSD(pnl.data?.total_unrealized_pnl)
  const fundingValue = showPlaceholderValues ? '—' : formatUSD(pnl.data?.total_funding_paid)
  const netValue = showPlaceholderValues ? '—' : formatUSD(pnl.data?.net_pnl)

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="card p-3 flex flex-col gap-1">
          <span className="label">Realized PnL</span>
          <span className={`${signColor(pnl.data?.total_realized_pnl)} font-mono text-lg font-semibold`}>
            {realizedValue}
          </span>
        </div>

        <div className="card p-3 flex flex-col gap-1">
          <span className="label">Unrealized PnL</span>
          <span className={`${signColor(pnl.data?.total_unrealized_pnl)} font-mono text-lg font-semibold`}>
            {unrealizedValue}
          </span>
        </div>

        <div className="card p-3 flex flex-col gap-1">
          <span className="label">Funding Paid</span>
          <span className={`${signColor(pnl.data?.total_funding_paid)} font-mono text-lg font-semibold`}>
            {fundingValue}
          </span>
        </div>

        <div className="card p-3 flex flex-col gap-1 border border-blue/20">
          <span className="label">Net PnL</span>
          <span className={`${signColor(pnl.data?.net_pnl)} font-mono text-xl font-bold`}>
            {netValue}
          </span>
        </div>
      </div>

      {middleContent}

      <div className="card flex flex-col">
        <span className="label px-3 pt-3 pb-2">PnL Components</span>

        {pnl.loading && <LoadingState rows={4} />}

        {pnl.error && <ErrorState message={pnl.error} onRetry={pnl.refetch} />}

        {!pnl.loading && !pnl.error && pnl.data && (
          <>
            <div className="flex justify-between items-center px-3 py-2 border-b border-border/50">
              <span className="label">Realized PnL</span>
              <span className={`font-mono text-xs ${signColor(pnl.data.total_realized_pnl)}`}>
                {formatUSD(pnl.data.total_realized_pnl)}
              </span>
            </div>

            <div className="flex justify-between items-center px-3 py-2 border-b border-border/50">
              <span className="label">Unrealized PnL</span>
              <span className={`font-mono text-xs ${signColor(pnl.data.total_unrealized_pnl)}`}>
                {formatUSD(pnl.data.total_unrealized_pnl)}
              </span>
            </div>

            <div className="flex justify-between items-center px-3 py-2 border-b border-border/50">
              <span className="label">Funding Paid</span>
              <span className={`font-mono text-xs ${signColor(pnl.data.total_funding_paid)}`}>
                {formatUSD(pnl.data.total_funding_paid)}
              </span>
            </div>

            <div className="flex justify-between items-center px-3 py-2 border-b border-border/50">
              <span className="label">Net PnL</span>
              <span className={`font-mono text-xs font-semibold ${signColor(pnl.data.net_pnl)}`}>
                {formatUSD(pnl.data.net_pnl)}
              </span>
            </div>

            <div className="flex justify-between items-center px-3 py-2 border-b border-border/50">
              <span className="label">Total Fills</span>
              <span className="font-mono text-xs text-text-primary">{summary.data?.total_fills ?? '—'}</span>
            </div>

            <div className="flex justify-between items-center px-3 py-2 border-b border-border/50">
              <span className="label">Open Positions</span>
              <span className="font-mono text-xs text-text-primary">{summary.data?.open_position_count ?? '—'}</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
