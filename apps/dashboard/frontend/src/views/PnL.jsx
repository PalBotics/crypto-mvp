import { useMemo } from 'react'
import PnLChart from '../components/charts/PnLChart'
import MetricCard from '../components/common/MetricCard'
import PnLBreakdown from '../components/panels/PnLBreakdown'
import useFills from '../hooks/useFills'
import { computeKpis } from '../utils/format'

function sharpeColor(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'default'
  if (value >= 1.0) return 'green'
  if (value >= 0) return 'yellow'
  return 'red'
}

function profitFactorColor(value) {
  if (value === null || value === undefined) return 'default'
  if (value === Number.POSITIVE_INFINITY || value >= 1.5) return 'green'
  if (value >= 1.0) return 'yellow'
  return 'red'
}

function formatKpiValue(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return 'N/A'
  }
  return value.toFixed(2)
}

export default function PnL() {
  const fills = useFills(500)
  const kpis = useMemo(() => computeKpis(fills.data), [fills.data])

  const sharpeValue = formatKpiValue(kpis.sharpe)
  const profitFactorValue = kpis.profitFactor === Number.POSITIVE_INFINITY
    ? '∞'
    : formatKpiValue(kpis.profitFactor)

  const kpiRow = (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <MetricCard
        label="SHARPE RATIO (annualized)"
        value={sharpeValue}
        color={sharpeColor(kpis.sharpe)}
        sub={`Based on ${kpis.tradeCount} trades`}
      />
      <MetricCard
        label="PROFIT FACTOR"
        value={profitFactorValue}
        color={profitFactorColor(kpis.profitFactor)}
        sub="W:L ratio of gross trade PnL"
      />
    </div>
  )

  return (
    <div className="flex flex-col gap-4">
      <PnLChart />
      <PnLBreakdown middleContent={kpiRow} />
    </div>
  )
}