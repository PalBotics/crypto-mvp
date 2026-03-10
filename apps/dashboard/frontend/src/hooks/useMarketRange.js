import useApi from './useApi'

export default function useMarketRange(hours = 2) {
  const { data, loading, error, lastUpdated, refetch } = useApi(
    '/api/market-range?hours=' + hours,
    { interval: 30000 }
  )

  return {
    data,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
