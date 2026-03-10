import SystemStatusBar from '../components/panels/SystemStatusBar'
import PositionSummary from '../components/panels/PositionSummary'
import QuotesPanel from '../components/panels/QuotesPanel'
import PnLSummary from '../components/panels/PnLSummary'
import RecentFills from '../components/panels/RecentFills'
import MarketRangePanel from '../components/panels/MarketRangePanel'
import useQuotes from '../hooks/useQuotes'

export default function Overview() {
  const quotes = useQuotes()
  const buyQuote = quotes.data.find((quote) => String(quote.side).toLowerCase() === 'buy') ?? null
  const sellQuote = quotes.data.find((quote) => String(quote.side).toLowerCase() === 'sell') ?? null

  return (
    <div className="flex flex-col gap-4 h-full">
      <SystemStatusBar />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <PositionSummary />
        <QuotesPanel />
        <PnLSummary />
      </div>

      <RecentFills />

      <MarketRangePanel buyQuote={buyQuote} sellQuote={sellQuote} />
    </div>
  )
}