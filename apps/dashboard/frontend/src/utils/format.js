const FALLBACK = '—'

function parseNumber(value) {
  if (value === null || value === undefined) {
    return Number.NaN
  }

  return parseFloat(value)
}

function formatNumber(value, decimals) {
  const parsed = parseNumber(value)
  if (Number.isNaN(parsed)) {
    return FALLBACK
  }

  return parsed.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function formatUSD(value) {
  return formatNumber(value, 2)
}

export function formatBTC(value) {
  return formatNumber(value, 8)
}

export function formatQty(value, decimals = 4) {
  return formatNumber(value, decimals)
}

export function formatPct(value, decimals = 4) {
  const parsed = parseNumber(value)
  if (Number.isNaN(parsed)) {
    return FALLBACK
  }

  return `${(parsed * 100).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}%`
}

export function toLocalTime(isoString) {
  if (isoString === null || isoString === undefined) {
    return FALLBACK
  }

  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) {
    return FALLBACK
  }

  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

export function signColor(value) {
  const parsed = parseNumber(value)

  if (Number.isNaN(parsed) || parsed === 0) {
    return 'text-text-secondary'
  }

  if (parsed > 0) {
    return 'text-green'
  }

  return 'text-red'
}
