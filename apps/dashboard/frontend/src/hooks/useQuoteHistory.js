import useApi from './useApi'

export default function useQuoteHistory(hours = 8, before = null, poll = true) {
  const url = before
    ? `/api/quote-history?hours=${hours}&before=${encodeURIComponent(before)}`
    : `/api/quote-history?hours=${hours}`

  const { data, loading, error, lastUpdated, refetch } = useApi(
    url,
    { interval: poll ? 10000 : 0 }
  )

  return {
    data: data?.snapshots ?? [],
    orderEvents: data?.order_events ?? [],
    apiLastUpdated: data?.last_updated ?? null,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
