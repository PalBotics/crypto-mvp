import useAccount from '../../hooks/useAccount'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatBTC, formatUSD, signColor } from '../../utils/format'

function row(label, value, className = 'font-mono text-xs text-text-primary') {
  return (
    <div className="flex justify-between items-center">
      <span className="label">{label}</span>
      <span className={className}>{value}</span>
    </div>
  )
}

export default function AccountPanel() {
  const account = useAccount()
  const data = account.data
  const pctRaw = data?.pct_in_btc ?? '0'
  const pctValue = Number.parseFloat(pctRaw)
  const pctClamped = Number.isFinite(pctValue) ? Math.max(0, Math.min(100, pctValue)) : 0

  return (
    <div className="card p-3 flex flex-col gap-3">
      <div className="flex justify-between items-center">
        <span className="label">Account</span>
        <span className="text-text-dim font-mono text-xs">{data?.currency ?? 'USD'}</span>
      </div>

      {account.loading && <LoadingState rows={4} />}
      {account.error && <ErrorState message={account.error} onRetry={account.refetch} />}

      {!account.loading && !account.error && data && (
        <>
          <div className="font-mono text-2xl text-text-primary">
            ${formatUSD(data.account_value)}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {row('Starting Capital', `$${formatUSD(data.starting_capital)}`)}
            {Number(data.total_deposited ?? '0') > 0 && row('Deposits', `$${formatUSD(data.total_deposited)}`, 'font-mono text-xs text-cyan-400')}
            {row('Realized PnL', formatUSD(data.realized_pnl), `font-mono text-xs ${signColor(data.realized_pnl)}`)}
            {row('Fees Paid', formatUSD(data.fees_paid), `font-mono text-xs ${signColor(`-${data.fees_paid}`)}`)}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {row('Cash', `$${formatUSD(data.cash_value)}`)}
            {row('BTC Held', formatBTC(data.btc_held))}
            {row('BTC Value', `$${formatUSD(data.btc_value_usd)}`)}
          </div>

          <div className="flex flex-col gap-1">
            <div className="w-full h-2 bg-muted rounded-sm overflow-hidden">
              <div className="bg-blue h-full transition-all duration-300" style={{ width: `${pctClamped}%` }} />
            </div>
            <span className="text-[10px] font-mono text-text-secondary">{formatUSD(data.pct_in_btc)}% in BTC</span>
          </div>
        </>
      )}
    </div>
  )
}
