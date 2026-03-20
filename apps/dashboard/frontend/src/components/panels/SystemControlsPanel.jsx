import { useMemo, useState } from 'react'

import LoadingState, { ErrorState } from '../common/Loading'
import StatusDot from '../common/StatusDot'
import { formatUSD } from '../../utils/format'

function strategyButtonClass(enabled, inFlight) {
  if (inFlight) {
    return 'opacity-50 cursor-not-allowed'
  }

  if (enabled) {
    return 'bg-amber-700 hover:bg-amber-600 text-white'
  }

  return 'bg-green hover:bg-green/80 text-bg'
}

export default function SystemControlsPanel({ systemStatus, loading, error, onRefresh }) {
  const [killSwitchPending, setKillSwitchPending] = useState(false)
  const [mmPending, setMmPending] = useState(false)
  const [dnPending, setDnPending] = useState(false)
  const [requestError, setRequestError] = useState(null)

  const killSwitchActive = Boolean(systemStatus?.kill_switch_active)
  const mmEnabled = Boolean(systemStatus?.mm_enabled)
  const dnEnabled = Boolean(systemStatus?.dn_enabled)

  const mmOpenPositions = systemStatus?.mm_open_positions ?? 0
  const dnOpenPositions = systemStatus?.dn_open_positions ?? 0
  const totalNotionalUsd = systemStatus?.total_notional_usd ?? '0'

  const panelClass = useMemo(() => {
    if (killSwitchActive) {
      return 'card p-3 flex flex-col gap-3 border-red shadow-[0_0_0_1px_rgba(239,68,68,0.45)]'
    }
    return 'card p-3 flex flex-col gap-3'
  }, [killSwitchActive])

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const body = await response.text()
      throw new Error(body || `Request failed with status ${response.status}`)
    }

    return response.json()
  }

  async function toggleKillSwitch() {
    const nextActive = !killSwitchActive
    const confirmed = window.confirm(
      nextActive
        ? 'This will halt all strategies and flatten all DN positions. Confirm?'
        : 'Resume all strategies? Confirm?'
    )
    if (!confirmed) return

    setKillSwitchPending(true)
    setRequestError(null)

    try {
      await postJson('/api/system/kill-switch', {
        active: nextActive,
        reason: 'manual_dashboard',
      })
      onRefresh?.()
    } catch (err) {
      setRequestError(err instanceof Error ? err.message : String(err))
    } finally {
      setKillSwitchPending(false)
    }
  }

  async function toggleStrategy(strategy, enabled) {
    const setter = strategy === 'mm' ? setMmPending : setDnPending
    setter(true)
    setRequestError(null)

    try {
      await postJson('/api/system/strategy-control', {
        strategy,
        enabled: !enabled,
        reason: 'manual_dashboard',
      })
      onRefresh?.()
    } catch (err) {
      setRequestError(err instanceof Error ? err.message : String(err))
    } finally {
      setter(false)
    }
  }

  return (
    <div className={panelClass}>
      <span className="label">SYSTEM CONTROLS</span>

      {loading && <LoadingState rows={3} />}
      {error && <ErrorState message={error} onRetry={onRefresh} />}

      {!loading && !error && (
        <>
          <div className="flex items-center justify-between gap-3">
            <span className="label">Kill switch</span>
            <div className="flex items-center gap-3">
              <StatusDot status={killSwitchActive ? 'error' : 'ok'} label={killSwitchActive ? 'ACTIVE' : 'INACTIVE'} />
              <button
                type="button"
                className={`font-mono text-[11px] px-3 py-1.5 rounded-sm border border-border transition-colors ${
                  killSwitchPending
                    ? 'opacity-50 cursor-not-allowed'
                    : killSwitchActive
                      ? 'bg-green hover:bg-green/80 text-bg'
                      : 'bg-red-700 hover:bg-red-600 text-white'
                }`}
                disabled={killSwitchPending}
                onClick={toggleKillSwitch}
              >
                {killSwitchActive ? 'DEACTIVATE' : 'ACTIVATE KILL SWITCH'}
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between gap-3">
            <span className="label">Market Maker</span>
            <div className="flex items-center gap-3">
              <StatusDot status={mmEnabled ? 'ok' : 'error'} label={mmEnabled ? 'ENABLED' : 'DISABLED'} />
              <button
                type="button"
                className={`font-mono text-[11px] px-3 py-1.5 rounded-sm border border-border transition-colors ${strategyButtonClass(mmEnabled, mmPending)}`}
                disabled={mmPending}
                onClick={() => toggleStrategy('mm', mmEnabled)}
              >
                {mmEnabled ? 'DISABLE' : 'ENABLE'}
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between gap-3">
            <span className="label">Delta-Neutral</span>
            <div className="flex items-center gap-3">
              <StatusDot status={dnEnabled ? 'ok' : 'error'} label={dnEnabled ? 'ENABLED' : 'DISABLED'} />
              <button
                type="button"
                className={`font-mono text-[11px] px-3 py-1.5 rounded-sm border border-border transition-colors ${strategyButtonClass(dnEnabled, dnPending)}`}
                disabled={dnPending}
                onClick={() => toggleStrategy('dn', dnEnabled)}
              >
                {dnEnabled ? 'DISABLE' : 'ENABLE'}
              </button>
            </div>
          </div>

          <div className="border-t border-border pt-2">
            <span className="font-mono text-[11px] text-text-secondary">
              MM: {mmOpenPositions} positions | DN: {dnOpenPositions} positions | Notional: ${formatUSD(totalNotionalUsd)}
            </span>
          </div>

          {requestError && (
            <div className="text-red font-mono text-[11px]">{requestError}</div>
          )}
        </>
      )}
    </div>
  )
}
