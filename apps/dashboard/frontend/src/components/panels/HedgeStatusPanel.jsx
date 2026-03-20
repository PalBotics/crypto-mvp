import LoadingState, { ErrorState } from '../common/Loading'
import useHedgeStatus from '../../hooks/useHedgeStatus'
import { formatQty, formatUSD } from '../../utils/format'

const SUCCESS_HEX = '#3B6D11'
const DANGER_HEX = '#A32D2D'
const WARNING_HEX = '#854F0B'
const ENTRY_THRESHOLD_APR = 5.0

function toNum(value) {
  const parsed = parseFloat(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function ratioBarPercent(ratio) {
  const clamped = Math.max(0, Math.min(2, ratio))
  return (clamped / 2) * 100
}

function fundingStatus(aprPct) {
  if (aprPct < 0) {
    return {
      label: 'Entry blocked',
      color: DANGER_HEX,
    }
  }

  if (aprPct < ENTRY_THRESHOLD_APR) {
    return {
      label: 'Below threshold',
      color: WARNING_HEX,
    }
  }

  return {
    label: 'Entry ready',
    color: SUCCESS_HEX,
  }
}

function accrualColor(value) {
  if (value > 0) return SUCCESS_HEX
  if (value < 0) return DANGER_HEX
  return undefined
}

export default function HedgeStatusPanel() {
  const { hedgeStatus, perpStatus, loading, error, refetch } = useHedgeStatus()

  const spotQty = toNum(hedgeStatus?.spot_qty)
  const perpQty = toNum(hedgeStatus?.perp_qty)
  const spotNotional = hedgeStatus?.spot_notional
  const perpNotional = hedgeStatus?.perp_notional
  const hedgeRatio = toNum(hedgeStatus?.hedge_ratio)
  const markPrice = hedgeStatus?.mark_price ?? perpStatus?.mark_price
  const isBalanced = Boolean(hedgeStatus?.is_balanced)
  const hasPosition = spotQty > 0 || perpQty > 0

  const fundingAprPct = toNum(perpStatus?.funding_rate_apr_pct)
  const funding = fundingStatus(fundingAprPct)
  const fundingAccrued = toNum(hedgeStatus?.daily_funding_accrued_usd)
  const isStale = (perpStatus?.data_age_seconds ?? 0) > 120

  const perpContracts = perpQty > 0 ? (perpQty / 0.1).toFixed(0) : '0'
  const fillPercent = ratioBarPercent(hedgeRatio)
  const ratioColor = hedgeRatio >= 0.9 && hedgeRatio <= 1.1 ? SUCCESS_HEX : DANGER_HEX

  return (
    <div className={`card p-3 flex flex-col gap-3 ${isStale ? 'panel-stale' : ''}`}>
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: hasPosition ? SUCCESS_HEX : '#555a6a' }}
          />
          <span className="label">Delta-neutral hedge</span>
        </div>
        {isStale && (
          <span className="font-mono text-[10px] text-yellow">stale feed</span>
        )}
      </div>

      {loading && <LoadingState rows={5} />}

      {error && <ErrorState message={error} onRetry={refetch} />}

      {!loading && !error && (
        <>
          <div className="flex justify-between items-center">
            <span className="label">Funding APR (ETH-PERP)</span>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs" style={{ color: funding.color }}>
                {fundingAprPct.toFixed(2)}%
              </span>
              <span className="font-mono text-[10px]" style={{ color: funding.color }}>
                {funding.label}
              </span>
            </div>
          </div>

          <div className="flex justify-between items-center">
            <span className="label">Entry threshold</span>
            <span className="font-mono text-xs text-text-secondary">5.0% APR minimum</span>
          </div>

          {hasPosition && (
            <>
              <div className="sep" />

              <div className="flex justify-between items-center">
                <span className="label">Spot leg (kraken)</span>
                <span className="font-mono text-xs">
                  {formatQty(spotQty, 2)} ETH | {formatUSD(spotNotional)}
                </span>
              </div>

              <div className="flex justify-between items-center">
                <span className="label">Perp leg (coinbase_advanced)</span>
                <span className="font-mono text-xs">
                  {perpContracts} contracts | {formatUSD(perpNotional)}
                </span>
              </div>

              <div className="flex flex-col gap-1">
                <div className="flex justify-between items-center">
                  <span className="label">Hedge ratio</span>
                  <span className="font-mono text-xs" style={{ color: ratioColor }}>
                    {hedgeRatio.toFixed(2)}
                  </span>
                </div>

                <div className="relative h-2 rounded bg-muted overflow-hidden">
                  <div
                    className="absolute left-1/2 top-0 h-full w-px bg-text-dim"
                    aria-hidden="true"
                  />
                  <div
                    className="h-full"
                    style={{
                      width: `${fillPercent}%`,
                      backgroundColor: ratioColor,
                    }}
                  />
                </div>

                <div className="flex justify-between text-[10px] font-mono text-text-dim">
                  <span>0.0</span>
                  <span>1.0 target</span>
                  <span>2.0</span>
                </div>
              </div>

              <div className="flex justify-between items-center">
                <span className="label">Daily funding accrued</span>
                <span className="font-mono text-xs" style={{ color: accrualColor(fundingAccrued) }}>
                  {formatUSD(hedgeStatus?.daily_funding_accrued_usd)}
                </span>
              </div>

              <div className="flex justify-between items-center">
                <span className="label">Mark price (ETH)</span>
                <span className="font-mono text-xs">{formatUSD(markPrice)}</span>
              </div>

              <div className="flex justify-between items-center">
                <span className="label">Balance state</span>
                <span
                  className="font-mono text-xs"
                  style={{ color: isBalanced ? SUCCESS_HEX : DANGER_HEX }}
                >
                  {isBalanced ? 'Balanced' : 'Out of range'}
                </span>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
