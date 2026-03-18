import useApi from './useApi'

export function useTicks(symbol = 'XBTUSD', limit = 120, before = null, poll = true) {
  const url = before
    ? '/api/market/ticks?symbol=' + symbol + '&limit=' + limit + '&before=' + encodeURIComponent(before)
    : '/api/market/ticks?symbol=' + symbol + '&limit=' + limit

  const { data, loading, error, lastUpdated, refetch } = useApi(
    url,
    { interval: poll ? 10000 : 0 }
  )

  return {
    data: data ?? [],
    loading,
    error,
    lastUpdated,
    refetch,
  }
}

export function useOrderBooks(symbol = 'XBTUSD', limit = 20, before = null, poll = true) {
  const url = before
    ? '/api/market/order-books?symbol=' + symbol + '&limit=' + limit + '&before=' + encodeURIComponent(before)
    : '/api/market/order-books?symbol=' + symbol + '&limit=' + limit

  const { data, loading, error, lastUpdated, refetch } = useApi(
    url,
    { interval: poll ? 10000 : 0 }
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
