import SystemStatusBar from '../components/panels/SystemStatusBar'
import PositionSummary from '../components/panels/PositionSummary'
import PnLSummary from '../components/panels/PnLSummary'
import RecentFills from '../components/panels/RecentFills'

export default function Overview() {
  return (
    <div className="flex flex-col gap-4 h-full">
      <SystemStatusBar />

      <div className="grid grid-cols-2 gap-4">
        <PositionSummary />
        <PnLSummary />
      </div>

      <RecentFills />
    </div>
  )
}