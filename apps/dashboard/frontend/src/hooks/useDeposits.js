import useApi from './useApi'

export default function useDeposits() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/deposits', {
    interval: 60000,
  })

  return {
    deposits: data?.deposits ?? [],
    totalDeposited: data?.total_deposited ?? '0',
    depositCount: data?.deposit_count ?? 0,
    loading,
    error,
    lastUpdated,
    refetch,
  }
}
