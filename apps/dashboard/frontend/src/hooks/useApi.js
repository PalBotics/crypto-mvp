import { useCallback, useEffect, useRef, useState } from 'react'

export default function useApi(url, options = {}) {
  const interval = options.interval ?? 10000
  const enabled = options.enabled ?? true

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  const hasFetchedRef = useRef(false)

  const fetchData = useCallback(async () => {
    if (!enabled || !url) {
      return
    }

    const isInitialFetch = !hasFetchedRef.current
    if (isInitialFetch) {
      setLoading(true)
    }

    try {
      const response = await fetch(url)
      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`)
      }

      const json = await response.json()
      setData(json)
      setError(null)
      setLastUpdated(new Date())
      hasFetchedRef.current = true
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (isInitialFetch) {
        setLoading(false)
      }
    }
  }, [enabled, url])

  const refetch = useCallback(() => {
    void fetchData()
  }, [fetchData])

  useEffect(() => {
    if (!enabled || !url) {
      setLoading(false)
      return undefined
    }

    void fetchData()

    if (!(interval > 0)) {
      return undefined
    }

    const timer = setInterval(() => {
      void fetchData()
    }, interval)

    return () => {
      clearInterval(timer)
    }
  }, [enabled, interval, url, fetchData])

  return { data, loading, error, lastUpdated, refetch }
}
