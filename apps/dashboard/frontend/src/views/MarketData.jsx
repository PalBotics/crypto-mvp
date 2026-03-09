import MidPriceChart from '../components/charts/MidPriceChart'
import FundingRateChart from '../components/charts/FundingRateChart'
import MarketDataTable from '../components/panels/MarketDataTable'

export default function MarketData() {
  return (
    <div className="flex flex-col gap-4">
      <MidPriceChart />
      <MarketDataTable />
      <FundingRateChart />
    </div>
  )
}