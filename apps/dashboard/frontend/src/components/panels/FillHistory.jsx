import { useMemo } from 'react'
import useFills from '../../hooks/useFills'
import DataTable from '../common/DataTable'
import SideTag from '../common/SideTag'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatUSD, formatQty, toLocalTime } from '../../utils/format'

export default function FillHistory() {
  const fills = useFills(200)

  const stats = useMemo(() => {
    const totalFills = fills.data.length
    let buyFills = 0
    let sellFills = 0
    let totalVolume = 0
    let totalFees = 0
    let totalPrice = 0

    for (const fill of fills.data) {
      const side = String(fill.side).toUpperCase()
      if (side === 'BUY') {
        buyFills += 1
      }
      if (side === 'SELL') {
        sellFills += 1
      }

      const qty = parseFloat(fill.fill_qty)
      if (!Number.isNaN(qty)) {
        totalVolume += qty
      }

      const fee = parseFloat(fill.fee_amount)
      if (!Number.isNaN(fee)) {
        totalFees += fee
      }

      const price = parseFloat(fill.fill_price)
      if (!Number.isNaN(price)) {
        totalPrice += price
      }
    }

    const avgFillPrice = totalFills > 0 ? totalPrice / totalFills : 0

    return {
      totalFills,
      buyFills,
      sellFills,
      totalVolume,
      totalFees,
      avgFillPrice,
    }
  }, [fills.data])

  const columns = [
    {
      key: 'fill_ts',
      label: 'Time',
      sortable: false,
      render: (v) => <span className="text-text-dim text-[10px]">{toLocalTime(v)}</span>,
    },
    {
      key: 'side',
      label: 'Side',
      sortable: false,
      render: (v) => <SideTag side={v} size="xs" />,
    },
    {
      key: 'symbol',
      label: 'Symbol',
      render: (v) => <span className="font-mono text-xs text-text-secondary">{v}</span>,
    },
    {
      key: 'fill_price',
      label: 'Price',
      align: 'right',
      render: (v) => <span className="font-mono text-xs">{formatUSD(v)}</span>,
    },
    {
      key: 'fill_qty',
      label: 'Qty',
      align: 'right',
      render: (v) => <span className="font-mono text-xs">{formatQty(v, 8)}</span>,
    },
    {
      key: 'fee_amount',
      label: 'Fee',
      align: 'right',
      render: (v) => <span className="text-text-dim font-mono text-xs">{formatUSD(v)}</span>,
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      <div className="card p-3 flex flex-col gap-2">
        <span className="label">Fill Statistics</span>

        <div className="flex justify-between items-center">
          <span className="label">Total Fills</span>
          <span className="font-mono text-xs text-text-primary">{stats.totalFills}</span>
        </div>

        <div className="flex justify-between items-center">
          <span className="label">Buy Fills</span>
          <span className="text-blue font-mono text-xs">{stats.buyFills}</span>
        </div>

        <div className="flex justify-between items-center">
          <span className="label">Sell Fills</span>
          <span className="text-orange font-mono text-xs">{stats.sellFills}</span>
        </div>

        <div className="flex justify-between items-center">
          <span className="label">Total Volume</span>
          <span className="font-mono text-xs text-text-primary">{formatQty(stats.totalVolume, 8)}</span>
        </div>

        <div className="flex justify-between items-center">
          <span className="label">Total Fees</span>
          <span className="font-mono text-xs text-text-primary">{formatUSD(stats.totalFees)}</span>
        </div>

        <div className="flex justify-between items-center">
          <span className="label">Avg Price</span>
          <span className="font-mono text-xs text-text-primary">{formatUSD(stats.avgFillPrice)}</span>
        </div>
      </div>

      <div className="card flex flex-col">
        <div className="flex items-center justify-between px-3 pt-3 pb-2">
          <span className="label">Fill History</span>
          <span className="font-mono text-[10px] text-text-dim">{fills.data.length}</span>
        </div>

        {fills.loading && <LoadingState rows={5} />}

        {fills.error && <ErrorState message={fills.error} onRetry={fills.refetch} />}

        {!fills.loading && !fills.error && fills.data.length === 0 && (
          <div className="text-text-dim font-mono text-xs text-center py-4">No fills yet</div>
        )}

        {!fills.loading && !fills.error && fills.data.length > 0 && (
          <DataTable
            columns={columns}
            rows={fills.data}
            keyField="fill_ts"
            compact={true}
            maxHeight="400px"
          />
        )}
      </div>
    </div>
  )
}
