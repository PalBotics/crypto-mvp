import SystemStatusBar from '../components/panels/SystemStatusBar'
import PositionSummary from '../components/panels/PositionSummary'
import QuotesPanel from '../components/panels/QuotesPanel'
import PnLSummary from '../components/panels/PnLSummary'
import RecentFills from '../components/panels/RecentFills'

export default function Overview() {
  return (
    <div className="flex flex-col gap-4 h-full">
      <SystemStatusBar />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <PositionSummary />
        <QuotesPanel />
        <PnLSummary />
      </div>

      <RecentFills />
    </div>
  )
}