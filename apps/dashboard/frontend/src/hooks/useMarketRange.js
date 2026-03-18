import useApi from './useApi'

export default function useMarketRange(hours = 2, before = null, poll = true) {
  const url = before
    ? `/api/market-range?hours=${hours}&before=${encodeURIComponent(before)}`
    : `/api/market-range?hours=${hours}`

  const { data, loading, error, lastUpdated, refetch } = useApi(
    url,
    { interval: poll ? 10000 : 0 }
  )

  return {
    data,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
