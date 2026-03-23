import usePositions from '../../hooks/usePositions'
import useRunSummary from '../../hooks/useRunSummary'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatUSD, formatQty, toLocalTime, signColor } from '../../utils/format'

export default function PositionSummary() {
  const positions = usePositions()
  const summary = useRunSummary()

  const position = positions.data?.[0]
  const qtyNumber = position ? parseFloat(position.quantity) : Number.NaN
  const side = Number.isNaN(qtyNumber) || qtyNumber >= 0 ? 'BUY' : 'SELL'
  const sideClass = side === 'BUY' ? 'text-blue' : 'text-orange'

  return (
    <div className="card p-3 flex flex-col gap-3">
      <div className="flex justify-between items-center">
        <span className="label">Position</span>
        <span className="text-text-dim font-mono text-xs">{position?.symbol ?? 'No open position'}</span>
      </div>

      {positions.loading && <LoadingState rows={4} />}

      {positions.error && <ErrorState message={positions.error} onRetry={positions.refetch} />}

      {!positions.loading && !positions.error && !position && (
        <div className="text-text-dim font-mono text-xs py-4 text-center">No open position</div>
      )}

      {!positions.loading && !positions.error && position && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex justify-between items-center">
              <span className="label">Quantity</span>
              <span className="font-mono text-xs">{formatQty(position.quantity, 8)}</span>
            </div>

            <div className="flex justify-between items-center">
              <span className="label">Side</span>
              <span className={`font-mono text-xs ${sideClass}`}>{side}</span>
            </div>

            <div className="flex justify-between items-center">
              <span className="label">Entry Price</span>
              <span className="font-mono text-xs">{formatUSD(position.avg_entry_price)}</span>
            </div>

            <div className="flex justify-between items-center">
              <span className="label">Unrealized PnL</span>
              <span className={`font-mono text-xs ${signColor(summary.data?.unrealized_pnl)}`}>
                {formatUSD(summary.data?.unrealized_pnl)}
              </span>
            </div>
          </div>

          <div className="text-text-dim text-[10px]">{toLocalTime(position.snapshot_ts)}</div>
        </>
      )}
    </div>
  )
}
