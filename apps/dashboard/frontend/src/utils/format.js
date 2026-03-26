const FALLBACK = '—'

const KPI_NA = null
const MATCH_EPSILON = 1e-12

function parseNumber(value) {
  if (value === null || value === undefined) {
    return Number.NaN
  }

  return parseFloat(value)
}

function parseFiniteNumber(value, fallback = Number.NaN) {
  const parsed = parseNumber(value)
  return Number.isFinite(parsed) ? parsed : fallback
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

export function computeKpis(fills) {
  if (!Array.isArray(fills) || fills.length === 0) {
    return { sharpe: KPI_NA, profitFactor: KPI_NA, tradeCount: 0 }
  }

  const sortedFills = [...fills].sort((left, right) => {
    const leftTime = new Date(left?.fill_ts ?? 0).getTime()
    const rightTime = new Date(right?.fill_ts ?? 0).getTime()
    return leftTime - rightTime
  })

  const openLotsBySymbol = new Map()
  const tradePnls = []

  for (const fill of sortedFills) {
    const symbol = String(fill?.symbol ?? '')
    const side = String(fill?.side ?? '').toLowerCase()
    const price = parseFiniteNumber(fill?.fill_price)
    const quantity = parseFiniteNumber(fill?.fill_qty)
    const feeAmount = Math.max(0, parseFiniteNumber(fill?.fee_amount, 0))

    if (!symbol || !Number.isFinite(price) || !Number.isFinite(quantity) || quantity <= 0) {
      continue
    }

    if (side === 'buy') {
      const lots = openLotsBySymbol.get(symbol) ?? []
      lots.push({
        price,
        quantityRemaining: quantity,
        feePerUnit: quantity > 0 ? feeAmount / quantity : 0,
      })
      openLotsBySymbol.set(symbol, lots)
      continue
    }

    if (side !== 'sell') {
      continue
    }

    const openLots = openLotsBySymbol.get(symbol) ?? []
    const sellFeePerUnit = quantity > 0 ? feeAmount / quantity : 0
    let quantityRemaining = quantity

    while (quantityRemaining > MATCH_EPSILON && openLots.length > 0) {
      const lot = openLots[0]
      const matchedQuantity = Math.min(quantityRemaining, lot.quantityRemaining)
      const grossPnl = (price - lot.price) * matchedQuantity
      const totalFees = (lot.feePerUnit * matchedQuantity) + (sellFeePerUnit * matchedQuantity)

      tradePnls.push(grossPnl - totalFees)

      lot.quantityRemaining -= matchedQuantity
      quantityRemaining -= matchedQuantity

      if (lot.quantityRemaining <= MATCH_EPSILON) {
        openLots.shift()
      }
    }

    if (openLots.length === 0) {
      openLotsBySymbol.delete(symbol)
    }
  }

  const tradeCount = tradePnls.length
  if (tradeCount === 0) {
    return { sharpe: KPI_NA, profitFactor: KPI_NA, tradeCount: 0 }
  }

  let sharpe = KPI_NA
  if (tradeCount >= 5) {
    const mean = tradePnls.reduce((sum, value) => sum + value, 0) / tradeCount
    const variance = tradePnls.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / tradeCount
    const stdDev = Math.sqrt(variance)

    if (stdDev > MATCH_EPSILON) {
      sharpe = (mean / stdDev) * Math.sqrt(8760)
    }
  }

  let profitFactor = KPI_NA
  if (tradeCount >= 2) {
    const grossWins = tradePnls.filter((value) => value > 0).reduce((sum, value) => sum + value, 0)
    const grossLosses = Math.abs(tradePnls.filter((value) => value < 0).reduce((sum, value) => sum + value, 0))

    if (grossWins <= MATCH_EPSILON) {
      profitFactor = 0
    } else if (grossLosses <= MATCH_EPSILON) {
      profitFactor = Number.POSITIVE_INFINITY
    } else {
      profitFactor = grossWins / grossLosses
    }
  }

  return { sharpe, profitFactor, tradeCount }
}
