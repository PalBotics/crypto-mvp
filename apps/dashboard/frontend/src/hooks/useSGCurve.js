import useApi from './useApi'

export default function useSGCurve(hours = 2, window = 25, degree = 2, before = null, poll = true) {
  const url = before
    ? `/api/sg-curve?hours=${hours}&window=${window}&degree=${degree}&before=${encodeURIComponent(before)}`
    : `/api/sg-curve?hours=${hours}&window=${window}&degree=${degree}`

  const { data, loading, error, lastUpdated, refetch } = useApi(
    url,
    { interval: poll ? 10000 : 0 }
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
