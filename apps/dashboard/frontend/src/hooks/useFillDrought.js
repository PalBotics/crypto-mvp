import useApi from './useApi'

export default function useFillDrought() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/fill-drought', {
    interval: 30000,
  })

  return {
    data,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
