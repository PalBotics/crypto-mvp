import HedgeStatusPanel from '../components/panels/HedgeStatusPanel'
import DnPnlSummary from '../components/panels/DnPnlSummary'
import DnTradeHistory from '../components/panels/DnTradeHistory'
import DnPnlChart from '../components/charts/DnPnlChart'
import useDnAccount from '../hooks/useDnAccount'

export default function DeltaNeutral() {
  const { account, badge } = useDnAccount()

  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="mb-2">
        <h1 className="text-xl font-semibold text-text-primary">Delta-Neutral Strategy</h1>
        <p className="text-sm text-text-secondary">Monitor hedge ratio, funding rates, and position balance</p>
      </div>

      <HedgeStatusPanel />
      <DnPnlSummary account={account} badge={badge} />
      <DnTradeHistory account={account} />
      <DnPnlChart account={account} />
    </div>
  )
}
