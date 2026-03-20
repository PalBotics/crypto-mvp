import { useCallback, useEffect, useState } from 'react'

export default function useRiskEvents(limit = 50) {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  const fetchData = useCallback(async () => {
    const isInitial = loading && data.length === 0
    if (isInitial) {
      setLoading(true)
    }

    try {
      const [mmResp, dnResp] = await Promise.all([
        fetch(`/api/runs/paper_mm/risk-events?limit=${limit}`),
        fetch(`/api/runs/paper_dn/risk-events?limit=${limit}`),
      ])

      if (!mmResp.ok) throw new Error(`Request failed with status ${mmResp.status}`)
      if (!dnResp.ok) throw new Error(`Request failed with status ${dnResp.status}`)

      const [mmEvents, dnEvents] = await Promise.all([mmResp.json(), dnResp.json()])
      const merged = [...(mmEvents ?? []), ...(dnEvents ?? [])]
        .sort((a, b) => new Date(b.created_ts) - new Date(a.created_ts))
        .slice(0, limit)

      setData(merged)
      setError(null)
      setLastUpdated(new Date())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (isInitial) {
        setLoading(false)
      }
    }
  }, [data.length, limit, loading])

  const refetch = useCallback(() => {
    void fetchData()
  }, [fetchData])

  useEffect(() => {
    void fetchData()
    const timer = setInterval(() => {
      void fetchData()
    }, 30000)

    return () => {
      clearInterval(timer)
    }
  }, [fetchData])

  return {
    data,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
