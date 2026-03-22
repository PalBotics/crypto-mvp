from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests

from core.config.settings import get_settings

COINBASE_PRODUCT_ID = "ETH-PERP-INTX"
SYSTEM_STATUS_URL = "http://127.0.0.1:8000/api/system/status"
COINBASE_PRODUCT_URL = "https://api.coinbase.com/api/v3/brokerage/market/products/ETH-PERP-INTX"


@dataclass
class MonitorStats:
    started_at: datetime
    checks_run: int = 0
    threshold_crossings: int = 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ts_label(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_signed_pct(value: Decimal) -> str:
    return f"{value:+.2f}%"


def _extract_funding_rate(payload: dict[str, Any]) -> Decimal | None:
    future = payload.get("future_product_details")
    if not isinstance(future, dict):
        return None

    perp = future.get("perpetual_details")
    candidates: list[Any] = []
    if isinstance(perp, dict):
        candidates.append(perp.get("funding_rate"))
        candidates.append(perp.get("fundingRate"))

    candidates.append(future.get("funding_rate"))
    candidates.append(future.get("fundingRate"))

    for raw in candidates:
        if raw is None or raw == "":
            continue
        try:
            return Decimal(str(raw))
        except Exception:
            continue

    return None


def fetch_funding_apr() -> Decimal:
    response = requests.get(COINBASE_PRODUCT_URL, timeout=10)
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Coinbase product payload is not a dict")

    funding_rate = _extract_funding_rate(payload)
    if funding_rate is None:
        raise RuntimeError("Coinbase funding rate field missing")

    return funding_rate * Decimal("24") * Decimal("365") * Decimal("100")


def fetch_kill_switch_active() -> bool:
    try:
        response = requests.get(SYSTEM_STATUS_URL, timeout=5)
        if not response.ok:
            return False
        payload = response.json()
        if not isinstance(payload, dict):
            return False
        return bool(payload.get("kill_switch_active", False))
    except requests.RequestException:
        return False


def run_full_conditions_check(project_root: Path) -> tuple[int, int, str]:
    command = [sys.executable, str(project_root / "scripts" / "check_live_entry_conditions.py")]
    proc = subprocess.run(command, cwd=str(project_root), capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")

    pass_count = 0
    fail_count = 0
    overall = "UNKNOWN"

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("[PASS]"):
            pass_count += 1
        elif stripped.startswith("[FAIL]"):
            fail_count += 1
        elif stripped.startswith("Overall:"):
            overall = stripped.replace("Overall:", "").strip()

    total = pass_count + fail_count
    return pass_count, total, overall


def _write_log_line(path: Path, text: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def _print_startup(
    *,
    start_ts: datetime,
    end_ts: datetime,
    funding_apr: Decimal,
    entry_threshold_apr: Decimal,
    exit_threshold_apr: Decimal,
    fast_interval_minutes: int,
    slow_interval_hours: int,
    days: int,
    alerts_log: Path,
    status_log: Path,
) -> None:
    status = "READY" if funding_apr >= entry_threshold_apr else "WAITING"
    print("=" * 60)
    print("FUNDING MONITOR  starting up")
    print("=" * 60)
    print("Watching:     ETH-PERP on Coinbase CFM")
    print(f"Entry threshold:  {_fmt_signed_pct(entry_threshold_apr)} APR")
    print(f"Exit threshold:   {_fmt_signed_pct(exit_threshold_apr)} APR")
    print(f"Check interval:   every {fast_interval_minutes} minutes")
    print(f"Summary interval: every {slow_interval_hours} hours")
    print(f"Running for:      {days} days (until {end_ts.date().isoformat()})")
    print(f"Log files:        {alerts_log.as_posix()}")
    print(f"                  {status_log.as_posix()}")
    print(f"Current funding:  {_fmt_signed_pct(funding_apr)} APR  ({status})")
    print("=" * 60)
    print("Press Ctrl+C to stop.")


def _print_crossed_above_alert(*, ts: datetime, funding_apr: Decimal, entry_threshold_apr: Decimal) -> None:
    print("=" * 60)
    print("!! FUNDING THRESHOLD CROSSED !!")
    print("=" * 60)
    print(f"ETH Funding APR:  {_fmt_signed_pct(funding_apr)}  (threshold: {_fmt_signed_pct(entry_threshold_apr)})")
    print(f"Time:             {_ts_label(ts)} UTC")
    print("Action required:  Run python scripts/check_live_entry_conditions.py")
    print("                  If all checks pass, proceed to Sprint 3.")
    print("=" * 60)


def _print_crossed_below_alert(*, ts: datetime, funding_apr: Decimal, exit_threshold_apr: Decimal) -> None:
    print("=" * 60)
    print("!! FUNDING DROPPED BELOW EXIT THRESHOLD !!")
    print("=" * 60)
    print(f"ETH Funding APR:  {_fmt_signed_pct(funding_apr)}  (exit threshold: {_fmt_signed_pct(exit_threshold_apr)})")
    print(f"Time:             {_ts_label(ts)} UTC")
    print("Action required:  Stay in waiting mode until funding re-enters setup range.")
    print("=" * 60)


def _print_shutdown(*, ended_at: datetime, stats: MonitorStats, alerts_log: Path) -> None:
    runtime = ended_at - stats.started_at
    runtime_days = runtime.days
    runtime_hours = runtime.seconds // 3600

    print("=" * 60)
    print("FUNDING MONITOR  stopped")
    print("=" * 60)
    print(f"Runtime:          {runtime_days} days, {runtime_hours} hours")
    print(f"Checks run:       {stats.checks_run}")
    print(f"Threshold crossings detected: {stats.threshold_crossings}")
    print(f"Log saved to:     {alerts_log.as_posix()}")
    print("=" * 60)


def run_monitor(
    *,
    fast_interval_minutes: int,
    slow_interval_hours: int,
    days: int,
    dry_run: bool,
) -> int:
    settings = get_settings()
    entry_threshold_apr = Decimal(str(settings.dn_funding_entry_threshold_apr))
    exit_threshold_apr = Decimal(str(settings.dn_funding_exit_threshold_apr))

    project_root = Path(__file__).resolve().parents[1]
    logs_dir = project_root / "logs"
    alerts_log = logs_dir / "funding_alerts.log"
    status_log = logs_dir / "monitor_status.log"

    start_ts = _utc_now()
    end_ts = start_ts + timedelta(days=days)

    current_funding_apr = fetch_funding_apr()
    _print_startup(
        start_ts=start_ts,
        end_ts=end_ts,
        funding_apr=current_funding_apr,
        entry_threshold_apr=entry_threshold_apr,
        exit_threshold_apr=exit_threshold_apr,
        fast_interval_minutes=fast_interval_minutes,
        slow_interval_hours=slow_interval_hours,
        days=days,
        alerts_log=alerts_log,
        status_log=status_log,
    )

    stats = MonitorStats(started_at=start_ts)
    last_funding_apr = current_funding_apr
    had_above_entry = current_funding_apr >= entry_threshold_apr

    next_fast_check = start_ts
    next_slow_check = start_ts
    kill_switch_paused = False

    try:
        while _utc_now() < end_ts:
            now = _utc_now()
            kill_switch_active = fetch_kill_switch_active()

            if kill_switch_active and not kill_switch_paused:
                kill_switch_paused = True
                event = f"[{_ts_label(now)}] kill_switch_detected status=PAUSED"
                print(event)
                _write_log_line(alerts_log, event, dry_run=dry_run)
            elif (not kill_switch_active) and kill_switch_paused:
                kill_switch_paused = False
                event = f"[{_ts_label(now)}] kill_switch_cleared status=RESUMED"
                print(event)
                _write_log_line(alerts_log, event, dry_run=dry_run)

            if not kill_switch_paused and now >= next_fast_check:
                funding_apr = fetch_funding_apr()
                status = "READY" if funding_apr >= entry_threshold_apr else "WAITING"
                line = (
                    f"[{_ts_label(now)}]  ETH funding: {_fmt_signed_pct(funding_apr)} APR  |  "
                    f"Threshold: {_fmt_signed_pct(entry_threshold_apr)}  |  Status: {status}"
                )
                print(line)
                stats.checks_run += 1

                crossed_up = last_funding_apr < entry_threshold_apr and funding_apr >= entry_threshold_apr
                crossed_down = had_above_entry and last_funding_apr >= exit_threshold_apr and funding_apr < exit_threshold_apr

                if crossed_up:
                    stats.threshold_crossings += 1
                    alert_line = (
                        f"[{_ts_label(now)}] ALERT funding_threshold_crossed "
                        f"funding_rate_apr={funding_apr:.6f} threshold_apr={entry_threshold_apr:.2f}"
                    )
                    print(alert_line)
                    _print_crossed_above_alert(
                        ts=now,
                        funding_apr=funding_apr,
                        entry_threshold_apr=entry_threshold_apr,
                    )
                    _write_log_line(alerts_log, alert_line, dry_run=dry_run)
                    had_above_entry = True

                if crossed_down:
                    stats.threshold_crossings += 1
                    alert_line = (
                        f"[{_ts_label(now)}] ALERT funding_dropped_below_exit "
                        f"funding_rate_apr={funding_apr:.6f} exit_threshold_apr={exit_threshold_apr:.2f}"
                    )
                    print(alert_line)
                    _print_crossed_below_alert(
                        ts=now,
                        funding_apr=funding_apr,
                        exit_threshold_apr=exit_threshold_apr,
                    )
                    _write_log_line(alerts_log, alert_line, dry_run=dry_run)
                    had_above_entry = False

                last_funding_apr = funding_apr
                next_fast_check = now + timedelta(minutes=fast_interval_minutes)

            if not kill_switch_paused and now >= next_slow_check:
                pass_count, total_count, overall = run_full_conditions_check(project_root)
                funding_for_summary = last_funding_apr
                status = "READY" if overall.startswith("READY") else "WAITING"
                summary = (
                    f"[{_ts_label(now)}]  6h summary: funding={funding_for_summary:.2f}%  "
                    f"conditions={pass_count}/{total_count} passed  status={status}"
                )
                print(summary)
                _write_log_line(status_log, summary, dry_run=dry_run)
                next_slow_check = now + timedelta(hours=slow_interval_hours)

            print(f"[{_ts_label(now)}] heartbeat .")
            time.sleep(60)

    except KeyboardInterrupt:
        _print_shutdown(ended_at=_utc_now(), stats=stats, alerts_log=alerts_log)
        return 0

    _print_shutdown(ended_at=_utc_now(), stats=stats, alerts_log=alerts_log)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Funding monitor daemon for Phase 7 waiting period")
    parser.add_argument("--fast-interval-minutes", type=int, default=15)
    parser.add_argument("--slow-interval-hours", type=int, default=6)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_monitor(
        fast_interval_minutes=args.fast_interval_minutes,
        slow_interval_hours=args.slow_interval_hours,
        days=args.days,
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())
