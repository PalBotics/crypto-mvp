import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, LineChart, ArrowLeftRight,
  TrendingUp, HeartPulse, Settings,
} from 'lucide-react'
import Overview     from './views/Overview'
import MarketData   from './views/MarketData'
import Fills        from './views/Fills'
import PnL          from './views/PnL'
import Health       from './views/Health'
import SettingsView from './views/Settings'

const NAV = [
  { to: '/',         icon: LayoutDashboard, label: 'Overview'    },
  { to: '/market',   icon: LineChart,       label: 'Market Data' },
  { to: '/fills',    icon: ArrowLeftRight,  label: 'Fills'       },
  { to: '/pnl',      icon: TrendingUp,      label: 'PnL'         },
  { to: '/health',   icon: HeartPulse,      label: 'Health'      },
  { to: '/settings', icon: Settings,        label: 'Settings'    },
]

function Sidebar() {
  return (
    <nav className="flex flex-col w-14 bg-surface border-r border-border shrink-0 py-3 z-20">
      <div className="flex items-center justify-center h-10 mb-4">
        <div className="w-6 h-6 rounded-sm bg-blue flex items-center justify-center">
          <span className="font-mono text-[10px] font-bold text-white leading-none">₿</span>
        </div>
      </div>

      <div className="w-8 mx-auto mb-4 border-t border-border" />

      <div className="flex flex-col gap-1 px-2 flex-1">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `group relative flex items-center justify-center h-9 w-full rounded-sm
               transition-all duration-150 cursor-pointer
               ${isActive
                 ? 'bg-blue/15 text-blue'
                 : 'text-text-dim hover:text-text-secondary hover:bg-muted/40'
               }`
            }
          >
            <Icon size={16} strokeWidth={1.75} />
            <span className="tooltip">{label}</span>
          </NavLink>
        ))}
      </div>

      <div className="flex items-center justify-center pb-1">
        <span className="text-text-dim font-mono text-[9px]">v0.1</span>
      </div>
    </nav>
  )
}

function StatusChip({ label, status = 'ok' }) {
  const dot   = { ok: 'bg-green animate-pulse-dot', warn: 'bg-yellow animate-pulse-dot', error: 'bg-red' }
  const color = { ok: 'text-green', warn: 'text-yellow', error: 'text-red' }
  return (
    <div className="flex items-center gap-1.5">
      <div className={`w-1.5 h-1.5 rounded-full ${dot[status]}`} />
      <span className={`font-mono text-[10px] ${color[status]}`}>{label}</span>
    </div>
  )
}

function Header() {
  const location = useLocation()
  const current = NAV.find(n =>
    n.to === '/' ? location.pathname === '/' : location.pathname.startsWith(n.to)
  )
  return (
    <header className="h-10 bg-surface border-b border-border flex items-center justify-between px-4 shrink-0">
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs text-text-dim tracking-widest uppercase">crypto-mvp</span>
        <span className="text-border">›</span>
        <span className="text-text-primary text-xs font-medium">{current?.label ?? 'Dashboard'}</span>
      </div>
      <div className="flex items-center gap-4">
        <StatusChip label="Collector"    status="ok" />
        <StatusChip label="Paper Trader" status="ok" />
        <StatusChip label="DB"           status="ok" />
      </div>
    </header>
  )
}

export default function App() {
  return (
    <div className="flex h-full bg-bg overflow-hidden">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto p-4 animate-fade-in">
          <Routes>
            <Route path="/"         element={<Overview />}     />
            <Route path="/market"   element={<MarketData />}   />
            <Route path="/fills"    element={<Fills />}        />
            <Route path="/pnl"      element={<PnL />}          />
            <Route path="/health"   element={<Health />}       />
            <Route path="/settings" element={<SettingsView />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}