import useRiskEvents from '../../hooks/useRiskEvents'
import DataTable from '../common/DataTable'
import LoadingState, { ErrorState } from '../common/Loading'
import { toLocalTime } from '../../utils/format'

export default function RiskEventsTable() {
  const riskEvents = useRiskEvents(50)

  function detailsText(row) {
    if (!row || row.details_json === null || row.details_json === undefined) {
      return '—'
    }
    if (typeof row.details_json === 'string') {
      return row.details_json
    }
    try {
      return JSON.stringify(row.details_json)
    } catch {
      return '—'
    }
  }

  const columns = [
    {
      key: 'created_ts',
      label: 'Time',
      sortable: false,
      render: (v) => <span className="text-text-dim text-[10px]">{toLocalTime(v)}</span>,
    },
    {
      key: 'strategy_name',
      label: 'Account',
      render: (v) => <span className="font-mono text-xs text-text-primary">{v || '—'}</span>,
    },
    {
      key: 'event_type',
      label: 'Type',
      render: (v) => <span className="font-mono text-xs text-text-secondary">{v}</span>,
    },
    {
      key: 'severity',
      label: 'Severity',
      render: (v) => {
        const sev = String(v ?? '').toLowerCase()
        const sevClass = sev === 'critical' ? 'text-red' : sev === 'warning' ? 'text-yellow' : sev === 'info' ? 'text-text-primary' : 'text-text-dim'

        return <span className={`font-mono text-[10px] font-semibold uppercase ${sevClass}`}>{sev || '—'}</span>
      },
    },
    {
      key: 'details_json',
      label: 'Details',
      render: (_v, row) => (
        <span className="font-mono text-[10px] text-text-dim break-all">{detailsText(row)}</span>
      ),
    },
  ]

  return (
    <div className="card flex flex-col">
      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <span className="label">Risk Events</span>
        <span className="font-mono text-[10px] text-text-dim">{riskEvents.data.length}</span>
      </div>

      {riskEvents.loading && <LoadingState rows={3} />}

      {riskEvents.error && <ErrorState message={riskEvents.error} onRetry={riskEvents.refetch} />}

      {!riskEvents.loading && !riskEvents.error && riskEvents.data.length === 0 && (
        <div className="text-text-dim font-mono text-xs text-center py-4">No risk events</div>
      )}

      {!riskEvents.loading && !riskEvents.error && riskEvents.data.length > 0 && (
        <DataTable
          columns={columns}
          rows={riskEvents.data}
          keyField="created_ts"
          compact={true}
          maxHeight="300px"
        />
      )}
    </div>
  )
}
