import HedgeStatusPanel from '../components/panels/HedgeStatusPanel'

export default function DeltaNeutral() {
  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="mb-2">
        <h1 className="text-xl font-semibold text-text-primary">Delta-Neutral Strategy</h1>
        <p className="text-sm text-text-secondary">Monitor hedge ratio, funding rates, and position balance</p>
      </div>

      <HedgeStatusPanel />
    </div>
  )
}
