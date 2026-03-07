from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from core.domain.normalize import to_decimal


class FeeModel(Protocol):
    """Protocol for paper-trading fee models."""

    def calculate_fee(self, fill_notional: Decimal) -> Decimal:
        """Return fee amount for a fill notional."""


@dataclass(frozen=True, slots=True)
class FixedBpsFeeModel:
    """Deterministic fixed basis-point fee model.

    Sprint 4 MVP assumes fills are taker fills and applies one fixed bps rate.
    """

    bps: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "bps", to_decimal(self.bps))

    def calculate_fee(self, fill_notional: Decimal) -> Decimal:
        notional = to_decimal(fill_notional)
        return (notional * self.bps) / Decimal("10000")
