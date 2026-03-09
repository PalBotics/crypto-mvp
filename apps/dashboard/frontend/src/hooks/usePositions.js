import useApi from './useApi'

export default function usePositions() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/runs/paper_mm/positions', {
    interval: 10000,
  })

  return { data: data ?? [], loading, error, lastUpdated, refetch }
}
