from decimal import Decimal

from core.app import bootstrap_app
from core.db.session import get_db_session
from core.paper.execution_flow import execute_one_paper_market_intent
from core.paper.fees import FixedBpsFeeModel


def main() -> None:
    ctx = bootstrap_app(service_name="execution_engine", check_db=True)
    session = get_db_session()

    try:
        executed = execute_one_paper_market_intent(
            session=session,
            fee_model=FixedBpsFeeModel(bps=Decimal("10")),
        )
        ctx.logger.info("paper_execution_cycle_completed", executed=executed)
    finally:
        session.close()


if __name__ == "__main__":
    main()
