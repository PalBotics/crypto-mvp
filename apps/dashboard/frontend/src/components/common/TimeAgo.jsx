import { useState, useEffect } from 'react'

export default function TimeAgo({ timestamp, className = '', staleAfter = 120 }) {
  const [, tick] = useState(0)

  useEffect(() => {
    const id = setInterval(() => tick(n => n + 1), 5000)
    return () => clearInterval(id)
  }, [])

  if (!timestamp) return <span className={`font-mono text-text-dim ${className}`}>—</span>

  const ms = typeof timestamp === 'number' ? timestamp : Date.parse(timestamp)
  if (isNaN(ms)) return <span className={`font-mono text-text-dim ${className}`}>—</span>

  const diffSec = Math.floor((Date.now() - ms) / 1000)
  const stale = diffSec > staleAfter

  function fmt(s) {
    if (s < 5)    return 'just now'
    if (s < 60)   return `${s}s ago`
    if (s < 3600) return `${Math.floor(s / 60)}m ago`
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`
    return `${Math.floor(s / 86400)}d ago`
  }

  return (
    <span
      className={`font-mono text-[10px] ${stale ? 'text-yellow' : 'text-text-dim'} ${className}`}
      title={new Date(ms).toLocaleString()}
    >
      {fmt(diffSec)}
    </span>
  )
}
