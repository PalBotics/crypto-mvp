import useApi from './useApi'

export default function useFills(limit = 20) {
  const { data, loading, error, lastUpdated, refetch } = useApi(
    '/api/runs/paper_mm/fills?limit=' + limit,
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
