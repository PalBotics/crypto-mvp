import useApi from './useApi'

const ACCOUNT = 'paper_dn'
const POLL_INTERVAL_MS = 10000

export default function useHedgeStatus() {
  const hedge = useApi(`/api/runs/${ACCOUNT}/hedge-status`, {
    interval: POLL_INTERVAL_MS,
  })
  const perp = useApi('/api/market/perp-status', {
    interval: POLL_INTERVAL_MS,
  })

  const perpStatus = Array.isArray(perp.data)
    ? perp.data.find((item) => item?.exchange === 'coinbase_advanced' && item?.symbol === 'ETH-PERP') ?? null
    : null

  return {
    hedgeStatus: hedge.data,
    perpStatus,
    loading: hedge.loading || perp.loading,
    error: hedge.error || perp.error,
    lastUpdated: hedge.lastUpdated || perp.lastUpdated,
    refetch: () => {
      hedge.refetch()
      perp.refetch()
    },
  }
}
