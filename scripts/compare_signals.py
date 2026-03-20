from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from core.db.session import SessionLocal
from core.models.strategy_signal_log import StrategySignalLog


@dataclass
class Divergence:
    ts: datetime
    dry_run_signal: str
    paper_signal: str
    funding_rate_apr: str


@dataclass
class ComparisonResult:
    dry_run_count: int
    paper_count: int
    matching: int
    divergences: list[Divergence]


def compare_signal_rows(*, hours: int, account: str) -> ComparisonResult:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    with SessionLocal() as session:
        dry_rows = (
            session.execute(
                select(StrategySignalLog)
                .where(StrategySignalLog.is_dry_run.is_(True))
                .where(StrategySignalLog.created_ts >= cutoff)
                .order_by(StrategySignalLog.created_ts.asc())
            )
            .scalars()
            .all()
        )
        paper_rows = (
            session.execute(
                select(StrategySignalLog)
                .where(StrategySignalLog.is_dry_run.is_(False))
                .where(StrategySignalLog.account_name == account)
                .where(StrategySignalLog.created_ts >= cutoff)
                .order_by(StrategySignalLog.created_ts.asc())
            )
            .scalars()
            .all()
        )

    matches = 0
    divergences: list[Divergence] = []
    compare_len = min(len(dry_rows), len(paper_rows))

    for idx in range(compare_len):
        dry_row = dry_rows[idx]
        paper_row = paper_rows[idx]
        if (dry_row.signal or "").upper() == (paper_row.signal or "").upper():
            matches += 1
            continue
        divergences.append(
            Divergence(
                ts=dry_row.created_ts,
                dry_run_signal=dry_row.signal,
                paper_signal=paper_row.signal,
                funding_rate_apr=str(dry_row.funding_rate_apr),
            )
        )

    if len(dry_rows) != len(paper_rows):
        longer = dry_rows if len(dry_rows) > len(paper_rows) else paper_rows
        missing_side = "paper_missing" if len(dry_rows) > len(paper_rows) else "dry_run_missing"
        for row in longer[compare_len:]:
            divergences.append(
                Divergence(
                    ts=row.created_ts,
                    dry_run_signal=row.signal if missing_side == "paper_missing" else "MISSING",
                    paper_signal=row.signal if missing_side == "dry_run_missing" else "MISSING",
                    funding_rate_apr=str(row.funding_rate_apr),
                )
            )

    return ComparisonResult(
        dry_run_count=len(dry_rows),
        paper_count=len(paper_rows),
        matching=matches,
        divergences=divergences,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare dry-run DN signals against paper DN signals")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--account", type=str, default="paper_dn")
    args = parser.parse_args()

    result = compare_signal_rows(hours=args.hours, account=args.account)
    total_for_pct = max(1, min(result.dry_run_count, result.paper_count))
    match_pct = (result.matching / total_for_pct) * 100

    print("=" * 48)
    print(f"SIGNAL COMPARISON  [last {args.hours} hours]")
    print("=" * 48)
    print(f"Dry-run iterations:     {result.dry_run_count}")
    print(f"Paper iterations:       {result.paper_count}")
    print(f"Matching signals:       {result.matching} ({match_pct:.2f}%)")
    print(f"Divergences:            {len(result.divergences)}")
    print("=" * 48)

    if result.divergences:
        for div in result.divergences:
            print(
                f"{div.ts.isoformat()} dry_run={div.dry_run_signal} "
                f"paper={div.paper_signal} funding_apr={div.funding_rate_apr}"
            )

    print("=" * 48)
    if len(result.divergences) == 0:
        print("Result: PASS (0 divergences)")
        print("=" * 48)
        return 0

    print(f"Result: FAIL ({len(result.divergences)} divergences)")
    print("=" * 48)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
