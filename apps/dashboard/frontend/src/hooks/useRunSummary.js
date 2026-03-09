import useApi from './useApi'

const ACCOUNT = 'paper_mm'

export default function useRunSummary() {
  const { data, loading, error, lastUpdated, refetch } = useApi('/api/runs/paper_mm/summary', {
    interval: 10000,
  })

  return { data, loading, error, lastUpdated, refetch }
}
