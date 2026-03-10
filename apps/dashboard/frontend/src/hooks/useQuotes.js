import useApi from './useApi'

export default function useQuotes() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/quotes', {
    interval: 10000,
  })

  return {
    data: data?.quotes ?? [],
    apiLastUpdated: data?.last_updated ?? null,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
