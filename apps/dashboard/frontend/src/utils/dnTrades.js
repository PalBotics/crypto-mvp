function parseNum(value) {
  const n = parseFloat(value)
  return Number.isFinite(n) ? n : 0
}

function classifyLeg(fill) {
  const symbol = String(fill.symbol ?? '').toUpperCase()
  const side = String(fill.side ?? '').toUpperCase()

  if (symbol === 'ETHUSD' && side === 'BUY') return 'entry_spot'
  if (symbol === 'ETH-PERP' && side === 'SELL') return 'entry_perp'
  if (symbol === 'ETHUSD' && side === 'SELL') return 'exit_spot'
  if (symbol === 'ETH-PERP' && side === 'BUY') return 'exit_perp'
  return null
}

function toDate(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

function eventFromPair(type, spotFill, perpFill) {
  const spotTs = toDate(spotFill.fill_ts)
  const perpTs = toDate(perpFill.fill_ts)
  const eventTs = (spotTs && perpTs) ? new Date(Math.max(spotTs.getTime(), perpTs.getTime())) : (spotTs || perpTs)

  return {
    type,
    ts: eventTs,
    spotFill,
    perpFill,
    fee: parseNum(spotFill.fee_amount) + parseNum(perpFill.fee_amount),
    spotPrice: parseNum(spotFill.fill_price),
    spotQty: parseNum(spotFill.fill_qty),
  }
}

export function buildDnTradesFromFills(fills = [], now = new Date()) {
  const sorted = [...fills]
    .filter((f) => toDate(f.fill_ts))
    .sort((a, b) => new Date(a.fill_ts).getTime() - new Date(b.fill_ts).getTime())

  const pending = {
    entrySpot: [],
    entryPerp: [],
    exitSpot: [],
    exitPerp: [],
  }

  const entryEvents = []
  const exitEvents = []

  for (const fill of sorted) {
    const kind = classifyLeg(fill)
    if (!kind) continue

    if (kind === 'entry_spot') pending.entrySpot.push(fill)
    if (kind === 'entry_perp') pending.entryPerp.push(fill)
    if (kind === 'exit_spot') pending.exitSpot.push(fill)
    if (kind === 'exit_perp') pending.exitPerp.push(fill)

    while (pending.entrySpot.length > 0 && pending.entryPerp.length > 0) {
      entryEvents.push(eventFromPair('entry', pending.entrySpot.shift(), pending.entryPerp.shift()))
    }

    while (pending.exitSpot.length > 0 && pending.exitPerp.length > 0) {
      exitEvents.push(eventFromPair('exit', pending.exitSpot.shift(), pending.exitPerp.shift()))
    }
  }

  const openEntries = [...entryEvents]
  const trades = []

  for (const entry of openEntries) {
    const idx = exitEvents.findIndex((exit) => exit.ts && entry.ts && exit.ts.getTime() >= entry.ts.getTime())
    let exit = null
    if (idx >= 0) {
      exit = exitEvents.splice(idx, 1)[0]
    }

    const start = entry.ts
    const end = exit?.ts ?? now
    const durationHours = start && end ? Math.max(0, (end.getTime() - start.getTime()) / 3600000) : 0

    trades.push({
      entryTime: entry.ts,
      exitTime: exit?.ts ?? null,
      durationHours,
      entryPrice: entry.spotPrice,
      exitPrice: exit?.spotPrice ?? null,
      qty: entry.spotQty,
      fees: entry.fee + (exit?.fee ?? 0),
      isActive: exit == null,
    })
  }

  return trades
}

export function enrichDnTrades(trades = [], pnl = null) {
  const fundingPaid = parseNum(pnl?.total_funding_paid)
  const fundingAccrued = parseNum(pnl?.total_accrued_not_yet_settled)
  const totalFunding = fundingPaid + fundingAccrued
  const totalUnrealized = parseNum(pnl?.total_unrealized_pnl)

  const totalHours = trades.reduce((sum, t) => sum + (t.durationHours > 0 ? t.durationHours : 0), 0)
  const fundingPerHour = totalHours > 0 ? totalFunding / totalHours : 0

  let cumulative = 0
  let activeApplied = false

  return trades.map((trade) => {
    const fundingEarned = fundingPerHour * trade.durationHours
    let netPnl = fundingEarned - trade.fees

    if (trade.isActive && !activeApplied) {
      netPnl = totalUnrealized
      activeApplied = true
    }

    if (!trade.isActive) {
      cumulative += netPnl
    }

    let result = 'BREAKEVEN'
    if (trade.isActive) result = 'ACTIVE'
    else if (netPnl > 0) result = 'POSITIVE'
    else if (netPnl < 0) result = 'NEGATIVE'

    return {
      ...trade,
      fundingEarned,
      netPnl,
      cumulativeNet: cumulative,
      result,
    }
  })
}
