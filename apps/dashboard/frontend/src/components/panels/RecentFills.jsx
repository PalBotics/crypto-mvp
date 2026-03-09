import useFills from '../../hooks/useFills'
import DataTable from '../common/DataTable'
import SideTag from '../common/SideTag'
import LoadingState, { ErrorState } from '../common/Loading'
import { formatUSD, formatQty, toLocalTime } from '../../utils/format'

export default function RecentFills() {
  const fills = useFills(10)

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
      key: 'fill_price',
      label: 'Price',
      align: 'right',
      render: (v) => <span className="font-mono text-xs">{formatUSD(v)}</span>,
    },
    {
      key: 'fill_qty',
      label: 'Qty',
      align: 'right',
      render: (v) => <span className="font-mono text-xs">{formatQty(v)}</span>,
    },
    {
      key: 'fee_amount',
      label: 'Fee',
      align: 'right',
      render: (v) => <span className="text-text-dim font-mono text-xs">{formatUSD(v)}</span>,
    },
  ]

  return (
    <div className="card flex flex-col">
      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <span className="label">Recent Fills</span>
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
          maxHeight="260px"
        />
      )}
    </div>
  )
}
