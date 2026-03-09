import PnLChart from '../components/charts/PnLChart'
import PnLBreakdown from '../components/panels/PnLBreakdown'

export default function PnL() {
  return (
    <div className="flex flex-col gap-4">
      <PnLChart />
      <PnLBreakdown />
    </div>
  )
}