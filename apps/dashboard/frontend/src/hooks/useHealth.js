import useApi from './useApi'

export default function useHealth() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/health', {
    interval: 10000,
  })

  return { data, loading, error, lastUpdated, refetch }
}
