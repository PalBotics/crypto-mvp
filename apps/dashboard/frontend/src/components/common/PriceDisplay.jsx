export default function PriceDisplay({ value, currency = 'USD', showSign = false, size = 'sm', prefix, className = '' }) {
  const num = parseFloat(value)
  const isValid = !isNaN(num)
  const decimals = currency === 'BTC' ? 8 : 2
  const formatted = isValid
    ? Math.abs(num).toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
    : '—'

  const sign = isValid && num >= 0 ? '+' : '-'
  const colorClass = showSign && isValid ? (num >= 0 ? 'text-green' : 'text-red') : 'text-text-primary'
  const sizeMap = { xs: 'text-[10px]', sm: 'text-xs', md: 'text-sm', lg: 'text-base', xl: 'text-lg' }
  const pfx = prefix ?? (currency === 'USD' ? '$' : '')

  return (
    <span className={`font-mono tabular-nums ${sizeMap[size]} ${colorClass} ${className}`}>
      {showSign && isValid && sign === '+' && <span className="text-green/70">+</span>}
      {showSign && isValid && sign === '-' && <span className="text-red/70">−</span>}
      {pfx}{formatted}
    </span>
  )
}