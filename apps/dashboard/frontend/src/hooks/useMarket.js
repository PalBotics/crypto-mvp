import useApi from './useApi'

export function useTicks(symbol = 'XBTUSD', limit = 120) {
  const { data, loading, error, lastUpdated, refetch } = useApi(
    '/api/market/ticks?symbol=' + symbol + '&limit=' + limit,
    { interval: 10000 }
  )

  return {
    data: data ?? [],
    loading,
    error,
    lastUpdated,
    refetch,
  }
}

export function useOrderBooks(symbol = 'XBTUSD', limit = 20) {
  const { data, loading, error, lastUpdated, refetch } = useApi(
    '/api/market/order-books?symbol=' + symbol + '&limit=' + limit,
    { interval: 10000 }
  )

  return {
    data: data ?? [],
    loading,
    error,
    lastUpdated,
    refetch,
  }
}

export function useFundingRates(symbol = 'XBTUSD', limit = 48) {
  const { data, loading, error, lastUpdated, refetch } = useApi(
    '/api/market/funding?symbol=' + symbol + '&limit=' + limit,
    { interval: 10000 }
  )

  return {
    data: data ?? [],
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
