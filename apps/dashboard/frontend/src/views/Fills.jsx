import FillRateChart from '../components/charts/FillRateChart'
import FillHistory from '../components/panels/FillHistory'

export default function Fills() {
  return (
    <div className="flex flex-col gap-4">
      <FillRateChart />
      <FillHistory />
    </div>
  )
}