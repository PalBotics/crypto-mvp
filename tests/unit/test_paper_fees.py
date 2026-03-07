from decimal import Decimal

from core.paper.fees import FixedBpsFeeModel


def test_fixed_bps_fee_calculation_uses_decimal_math() -> None:
    model = FixedBpsFeeModel(bps=Decimal("10"))

    fee = model.calculate_fee(Decimal("1000"))

    assert fee == Decimal("1")


def test_fixed_bps_fee_output_is_deterministic() -> None:
    model = FixedBpsFeeModel(bps=Decimal("7.5"))

    first = model.calculate_fee(Decimal("1234.56"))
    second = model.calculate_fee(Decimal("1234.56"))

    assert first == second


def test_fixed_bps_zero_fee_case() -> None:
    model = FixedBpsFeeModel(bps=Decimal("0"))

    fee = model.calculate_fee(Decimal("100000"))

    assert fee == Decimal("0")
