export default function SideTag({ side = '', size = 'sm' }) {
  const upper = String(side).toUpperCase()
  const isBuy = upper === 'BUY'
  const sizeMap = { xs: 'text-[9px] px-1 py-0', sm: 'text-[10px] px-1.5 py-0.5' }

  return (
    <span className={`
      font-mono font-semibold tracking-wider rounded-sm inline-block
      ${sizeMap[size]}
      ${isBuy
        ? 'bg-blue/15 text-blue border border-blue/25'
        : 'bg-orange/15 text-orange border border-orange/25'
      }
    `}>
      {upper || '—'}
    </span>
  )
}
