import useApi from './useApi'

const POLL_INTERVAL_MS = 30000

export default function useDnAccount() {
  const liveSummary = useApi('/api/runs/live_dn/summary', {
    interval: POLL_INTERVAL_MS,
  })

  const openPositions = Number(liveSummary.data?.open_position_count ?? 0)
  const totalFills = Number(liveSummary.data?.total_fills ?? 0)
  const isLive = openPositions > 0 || totalFills > 0

  return {
    account: isLive ? 'live_dn' : 'paper_dn',
    badge: isLive ? 'LIVE' : 'PAPER',
    isLive,
    liveSummary,
  }
}
