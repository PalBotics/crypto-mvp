import useApi from './useApi'

export default function useQuoteHistory(hours = 8) {
  const { data, loading, error, lastUpdated, refetch } = useApi(
    '/api/quote-history?hours=' + hours,
    { interval: 30000 }
  )

  return {
    data: data?.snapshots ?? [],
    apiLastUpdated: data?.last_updated ?? null,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
