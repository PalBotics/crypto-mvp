import useApi from './useApi'

export default function useSGCurve(hours = 2, window = 25, degree = 2) {
  const { data, loading, error, lastUpdated, refetch } = useApi(
    `/api/sg-curve?hours=${hours}&window=${window}&degree=${degree}`,
    { interval: 30000 }
  )

  return {
    data: data?.points ?? [],
    apiLastUpdated: data?.last_updated ?? null,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
