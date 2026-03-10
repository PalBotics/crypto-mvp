import { useEffect, useRef } from 'react'

import useApi from './useApi'

export default function useQuotes() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/quotes', {
    interval: 10000,
  })

  const lastKnownRef = useRef([])

  useEffect(() => {
    const liveQuotes = data?.quotes ?? []
    if (liveQuotes.length > 0) {
      lastKnownRef.current = liveQuotes
    }
  }, [data])

  return {
    data: data?.quotes ?? [],
    lastKnownData: lastKnownRef.current,
    apiLastUpdated: data?.last_updated ?? null,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
