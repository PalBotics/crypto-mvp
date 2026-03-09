import { useOrderBooks } from '../../hooks/useMarket'
import DataTable from '../common/DataTable'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatUSD, toLocalTime } from '../../utils/format'

export default function MarketDataTable() {
  const orderBooks = useOrderBooks(undefined, 20)

  const columns = [
    {
      key: 'event_ts',
      label: 'Time',
      sortable: false,
      render: (v) => <span className="text-text-dim text-[10px]">{toLocalTime(v)}</span>,
    },
    {
      key: 'bid_price_1',
      label: 'Bid',
      align: 'right',
      render: (v) => <span className="font-mono text-xs text-green">{formatUSD(v)}</span>,
    },
    {
      key: 'ask_price_1',
      label: 'Ask',
      align: 'right',
      render: (v) => <span className="font-mono text-xs text-red">{formatUSD(v)}</span>,
    },
    {
      key: 'spread',
      label: 'Spread',
      align: 'right',
      render: (v) => {
        const parsed = parseFloat(v)
        const isAnomalous = !Number.isNaN(parsed) && parsed > 1.0
        return (
          <span className={isAnomalous ? 'text-yellow font-mono text-xs' : 'text-text-secondary font-mono text-xs'}>
            {formatUSD(v)}
          </span>
        )
      },
    },
    {
      key: 'spread_bps',
      label: 'Spread bps',
      align: 'right',
      render: (v) => {
        const parsed = parseFloat(v)
        const isAnomalous = !Number.isNaN(parsed) && parsed > 1.0
        return (
          <span className={isAnomalous ? 'text-yellow font-mono text-xs font-semibold' : 'text-text-secondary font-mono text-xs'}>
            {Number.isNaN(parsed) ? '—' : parsed.toFixed(2) + ' bps'}
          </span>
        )
      },
    },
    {
      key: 'mid_price',
      label: 'Mid',
      align: 'right',
      render: (v) => <span className="font-mono text-xs">{formatUSD(v)}</span>,
    },
  ]

  return (
    <div className="card flex flex-col">
      <span className="label px-3 pt-3 pb-2">Order Book Snapshots</span>

      {orderBooks.loading && <LoadingState rows={5} />}

      {orderBooks.error && <ErrorState message={orderBooks.error} onRetry={orderBooks.refetch} />}

      {!orderBooks.loading && !orderBooks.error && orderBooks.data.length === 0 && (
        <div className="text-text-dim font-mono text-xs text-center py-4">No order book data</div>
      )}

      {!orderBooks.loading && !orderBooks.error && orderBooks.data.length > 0 && (
        <DataTable
          columns={columns}
          rows={orderBooks.data}
          keyField="event_ts"
          compact={true}
          maxHeight="260px"
        />
      )}
    </div>
  )
}
