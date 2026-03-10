import { useEffect, useRef } from 'react'

import useApi from './useApi'

export default function useQuotes() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/quotes', {
    interval: 10000,
  })

  const lastKnownQuotes = useRef([])

  useEffect(() => {
    const newData = data?.quotes ?? []
    if (newData.length > 0) {
      lastKnownQuotes.current = newData
    }
  }, [data])

  return {
    data: data?.quotes ?? [],
    lastKnown: lastKnownQuotes.current,
    apiLastUpdated: data?.last_updated ?? null,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
