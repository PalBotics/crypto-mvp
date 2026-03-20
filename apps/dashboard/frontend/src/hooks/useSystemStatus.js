import useApi from './useApi'

export default function useSystemStatus() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/system/status', {
    interval: 5000,
  })

  return {
    systemStatus: data,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
