import useApi from './useApi'

export default function useRiskEvents(limit = 50) {
  const { data, loading, error, lastUpdated, refetch } = useApi(
    '/api/runs/paper_mm/risk-events?limit=' + limit,
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
