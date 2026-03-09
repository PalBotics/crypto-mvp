import { useState } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'

export default function DataTable({ columns = [], rows = [], keyField = 'id', maxHeight, emptyText = 'No data', compact = false }) {
  const [sortKey, setSortKey] = useState(null)
  const [sortDir, setSortDir] = useState('desc')

  function handleSort(key) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sorted = [...rows].sort((a, b) => {
    if (!sortKey) return 0
    const av = a[sortKey], bv = b[sortKey]
    if (av == null) return 1
    if (bv == null) return -1
    const cmp = typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv))
    return sortDir === 'asc' ? cmp : -cmp
  })

  const rowPy = compact ? 'py-1' : 'py-2'

  return (
    <div className="w-full overflow-auto" style={maxHeight ? { maxHeight } : {}}>
      <table className="w-full border-collapse text-xs min-w-max">
        <thead className="sticky top-0 z-10">
          <tr className="bg-surface border-b border-border">
            {columns.map(col => (
              <th
                key={col.key}
                onClick={() => col.sortable !== false && handleSort(col.key)}
                className={`
                  px-3 ${rowPy} text-left font-medium text-text-dim whitespace-nowrap select-none
                  ${col.align === 'right' ? 'text-right' : ''}
                  ${col.align === 'center' ? 'text-center' : ''}
                  ${col.sortable !== false ? 'cursor-pointer hover:text-text-secondary transition-colors' : ''}
                `}
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {col.sortable !== false && (
                    sortKey === col.key
                      ? sortDir === 'asc'
                        ? <ChevronUp size={10} className="text-blue" />
                        : <ChevronDown size={10} className="text-blue" />
                      : <ChevronsUpDown size={10} className="text-text-dim/40" />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-3 py-6 text-center text-text-dim font-mono text-[11px]">
                {emptyText}
              </td>
            </tr>
          ) : (
            sorted.map((row, i) => (
              <tr key={row[keyField] ?? i} className="border-b border-border/50 hover:bg-muted/20 transition-colors duration-75">
                {columns.map(col => (
                  <td
                    key={col.key}
                    className={`
                      px-3 ${rowPy} text-text-primary whitespace-nowrap
                      ${col.align === 'right' ? 'text-right' : ''}
                      ${col.align === 'center' ? 'text-center' : ''}
                    `}
                  >
                    {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '—')}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}