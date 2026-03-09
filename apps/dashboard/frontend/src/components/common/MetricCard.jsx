export default function MetricCard({ label, value, delta, color = 'default', mono = true, size = 'md', sub }) {
  const colorMap = {
    default: 'text-text-primary',
    green:   'text-green',
    red:     'text-red',
    blue:    'text-blue',
    orange:  'text-orange',
    yellow:  'text-yellow',
  }

  const valueSize = { sm: 'text-base', md: 'text-xl', lg: 'text-2xl' }[size]
  const deltaPositive = delta && !delta.startsWith('-')

  return (
    <div className="card p-3 flex flex-col gap-1">
      <span className="label truncate">{label}</span>
      <div className="flex items-baseline gap-2 min-w-0">
        <span className={`${valueSize} font-semibold ${mono ? 'font-mono' : 'font-sans'} ${colorMap[color]} truncate leading-tight`}>
          {value ?? '—'}
        </span>
        {delta && (
          <span className={`font-mono text-xs shrink-0 ${deltaPositive ? 'text-green' : 'text-red'}`}>
            {delta}
          </span>
        )}
      </div>
      {sub && <span className="text-text-dim font-mono text-[10px] truncate">{sub}</span>}
    </div>
  )
}