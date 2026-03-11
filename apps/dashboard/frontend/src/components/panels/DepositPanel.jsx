import { useState } from 'react'
import useDeposits from '../../hooks/useDeposits'
import { formatUSD } from '../../utils/format'

export default function DepositPanel() {
  const deposits = useDeposits()
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setErrorMsg('')
    setSuccess('')
    setSubmitting(true)

    try {
      const resp = await fetch('/api/deposit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount, note: note.trim() || null }),
      })

      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        throw new Error(body.detail ?? 'Deposit failed')
      }

      const data = await resp.json()
      setSuccess(`✓ $${formatUSD(data.amount)} deposited`)
      setAmount('')
      setNote('')
      deposits.refetch()
      setTimeout(() => setSuccess(''), 3000)
    } catch (err) {
      setErrorMsg(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card p-4 flex flex-col gap-3">
      <span className="label">Paper Deposits</span>

      <form onSubmit={handleSubmit} className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          <input
            type="number"
            step="0.01"
            min="0.01"
            placeholder="$0.00"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-28 bg-card border border-border rounded-sm px-2 py-1 font-mono text-xs text-text-primary placeholder:text-text-dim focus:outline-none focus:border-blue/50"
            required
          />
          <input
            type="text"
            maxLength={100}
            placeholder="e.g. Market dip opportunity"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="flex-1 bg-card border border-border rounded-sm px-2 py-1 font-mono text-xs text-text-primary placeholder:text-text-dim focus:outline-none focus:border-blue/50"
          />
          <button
            type="submit"
            disabled={submitting || !amount}
            className="px-3 py-1 rounded-sm text-xs font-mono border border-green/40 text-green bg-green/10 hover:bg-green/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? '...' : 'Add Funds'}
          </button>
        </div>
        {success && <span className="text-green font-mono text-xs">{success}</span>}
        {errorMsg && <span className="text-red font-mono text-xs">{errorMsg}</span>}
      </form>

      {deposits.loading && deposits.deposits.length === 0 ? (
        <span className="text-text-dim font-mono text-xs">Loading...</span>
      ) : deposits.deposits.length === 0 ? (
        <span className="text-text-dim font-mono text-xs">No deposits yet</span>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-1 pr-4 text-text-secondary font-normal">Date</th>
                  <th className="text-right py-1 pr-4 text-text-secondary font-normal">Amount</th>
                  <th className="text-left py-1 text-text-secondary font-normal">Note</th>
                </tr>
              </thead>
              <tbody>
                {deposits.deposits.map((d) => (
                  <tr key={d.id} className="border-b border-border/30">
                    <td className="py-1 pr-4 text-text-secondary whitespace-nowrap">
                      {new Date(d.created_ts).toLocaleString()}
                    </td>
                    <td className="py-1 pr-4 text-right text-green whitespace-nowrap">
                      ${formatUSD(d.amount)}
                    </td>
                    <td className="py-1 text-text-primary">{d.note ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex justify-between items-center pt-1 border-t border-border/50">
            <span className="text-text-secondary font-mono text-xs">Total deposited</span>
            <span className="font-mono text-xs text-text-primary">
              ${formatUSD(deposits.totalDeposited)} across {deposits.depositCount} deposit{deposits.depositCount !== 1 ? 's' : ''}
            </span>
          </div>
        </>
      )}
    </div>
  )
}
