import { RefreshCw, AlertTriangle } from 'lucide-react'

export function LoadingState({ rows = 3, height }) {
  return (
    <div className="flex flex-col gap-2 p-3 animate-pulse" style={height ? { height } : {}}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-3 rounded bg-muted"
          style={{ width: `${70 + (i % 3) * 10}%`, opacity: 1 - i * 0.15 }}
        />
      ))}
    </div>
  )
}

export function Spinner({ size = 12 }) {
  return <RefreshCw size={size} strokeWidth={2} className="text-text-dim animate-spin-slow" />
}

export function ErrorState({ message = 'Failed to load', onRetry, height }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-4 text-center" style={height ? { height } : {}}>
      <AlertTriangle size={18} className="text-yellow" />
      <span className="text-text-secondary text-xs">{message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 px-3 py-1 rounded-sm border border-border
                     text-text-secondary text-xs hover:border-blue/40 hover:text-blue
                     transition-colors duration-150 font-mono"
        >
          <RefreshCw size={10} />
          Retry
        </button>
      )}
    </div>
  )
}

export default LoadingState