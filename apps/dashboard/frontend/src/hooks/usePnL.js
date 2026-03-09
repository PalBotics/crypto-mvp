import useApi from './useApi'

export default function usePnL() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/runs/paper_mm/pnl', {
    interval: 10000,
  })

  return { data, loading, error, lastUpdated, refetch }
}
