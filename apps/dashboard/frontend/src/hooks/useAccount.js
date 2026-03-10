import useApi from './useApi'

export default function useAccount() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/account', {
    interval: 30000,
  })

  return { data, loading, error, lastUpdated, refetch }
}
