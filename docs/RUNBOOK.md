# crypto-mvp Incident Runbook

## Exchange API goes down

Symptoms: circuit breaker opens, exchange_circuit_breaker_opened in logs
Immediate action: check dashboard Health view -> Circuit Breakers panel

Steps:
1. Confirm which exchange is down (Kraken or Coinbase CFM)
2. Check exchange status page (kraken.com/en-us/system-status, status.coinbase.com)
3. If planned maintenance: wait, circuit breaker will auto-recover
4. If unplanned outage: monitor, do not manually intervene
5. If outage > 2 hours with open live positions: consider manual flatten via kill switch
6. When exchange recovers: circuit breaker closes automatically, strategy resumes. Verify positions still match DB.

## Position mismatch detected

Symptoms: scripts/reconcile.py shows MISMATCH, or manual review finds DB position differs from exchange by > 1%
Immediate action: DO NOT PLACE NEW ORDERS until resolved

Steps:
1. Activate kill switch immediately via dashboard Health view
2. Run: python scripts/reconcile.py to get exact mismatch details
3. Log into exchange UI directly to verify actual position
4. Identify source: partial fill, fee discrepancy, or DB write failure
5. Do not deactivate kill switch until mismatch is explained and resolved
6. After resolution: update DB manually if needed, deactivate kill switch, run reconcile.py again to confirm PASS

## Max daily loss hit

Symptoms: daily_loss_limit_hit in logs, strategy halted automatically
Immediate action: review what caused the loss before restarting

Steps:
1. Check dashboard Delta-Neutral view for current position PnL
2. Check Health view Risk Events table for triggering event
3. Do NOT restart strategy immediately - understand the cause first
4. If loss was caused by a bug: fix the bug before restarting
5. If loss was caused by market conditions: review if entry threshold should be raised
6. To restart: deactivate kill switch via dashboard, verify all conditions in check_live_entry_conditions.py pass

## Circuit breaker opens

Symptoms: exchange_circuit_breaker_opened in logs, strategy pauses
Immediate action: check if exchange is actually down or if it is a transient API error

Steps:
1. Check dashboard Health view -> Circuit Breakers panel
2. Wait 60 seconds - breaker enters half-open state and sends one canary request automatically
3. If exchange responds: breaker closes automatically, no action needed
4. If breaker stays open: check exchange status page
5. If false positive (exchange is fine but breaker opened): check logs for root cause, consider restarting the paper trader service

## Kill switch accidentally activated

Symptoms: strategy halted, kill_switch_active_halting logs appearing, DN positions were flattened
Immediate action: verify no unintended orders were placed during activation

Steps:
1. Check dashboard for current positions - confirm flat or expected
2. Check fills table for any unexpected fills during the incident
3. Run reconcile.py to confirm DB matches exchange
4. If positions were unexpectedly closed: note the realized PnL impact
5. Deactivate kill switch via dashboard Health view -> DEACTIVATE button
6. Verify strategy resumes normally on next iteration
7. Check entry conditions before re-entering: python scripts/check_live_entry_conditions.py

## Quick reference - useful commands

Check entry conditions:   python scripts/check_live_entry_conditions.py
Reconcile positions:      python scripts/reconcile.py
Validate live feeds:      python scripts/validate_live_feeds.py
Start all services:       .\start-crypto-mvp.bat
Stop all services:        .\stop-crypto-mvp.bat
Dashboard:                http://localhost:8000/health
Kraken status:            https://www.kraken.com/en-us/system-status
Coinbase status:          https://status.coinbase.com
