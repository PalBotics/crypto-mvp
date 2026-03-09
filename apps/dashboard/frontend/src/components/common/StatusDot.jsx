export default function StatusDot({ status = 'ok', label, size = 'sm' }) {
  const cfg = {
    ok:    { dot: 'bg-green',  text: 'text-green',          pulse: true  },
    warn:  { dot: 'bg-yellow', text: 'text-yellow',         pulse: true  },
    error: { dot: 'bg-red',    text: 'text-red',            pulse: false },
    stale: { dot: 'bg-muted',  text: 'text-text-secondary', pulse: false },
  }[status] ?? { dot: 'bg-muted', text: 'text-text-dim', pulse: false }

  const dotSize  = size === 'md' ? 'w-2.5 h-2.5' : 'w-1.5 h-1.5'
  const textSize = size === 'md' ? 'text-xs' : 'text-[10px]'

  return (
    <div className="flex items-center gap-1.5">
      <div className={`${dotSize} rounded-full ${cfg.dot} ${cfg.pulse ? 'animate-pulse-dot' : ''} shrink-0`} />
      {label && (
        <span className={`font-mono ${textSize} ${cfg.text} leading-none`}>{label}</span>
      )}
    </div>
  )
}