from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
from decimal import Decimal

import httpx

from core.utils.logging import get_logger

_log = get_logger(__name__)


class KrakenAuthError(RuntimeError):
    """Raised when Kraken authenticated API calls fail."""


class KrakenAuthAdapter:
    """Authenticated read-only Kraken spot REST adapter.

    This adapter only calls read-only account endpoints. It never places,
    modifies, or cancels orders.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.kraken.com",
        timeout: int = 10,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def get_account_balance(self) -> dict[str, Decimal]:
        payload = self._post_private("/0/private/Balance")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise KrakenAuthError("Kraken Balance response missing 'result' object")

        balances: dict[str, Decimal] = {}
        for asset, value in result.items():
            balances[str(asset)] = Decimal(str(value))
        return balances

    def get_open_orders(self) -> list[dict]:
        payload = self._post_private("/0/private/OpenOrders")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise KrakenAuthError("Kraken OpenOrders response missing 'result' object")

        open_orders = result.get("open", {})
        if isinstance(open_orders, dict):
            return [order for order in open_orders.values() if isinstance(order, dict)]
        if isinstance(open_orders, list):
            return [order for order in open_orders if isinstance(order, dict)]
        return []

    def verify_no_open_orders(self) -> bool:
        open_orders = self.get_open_orders()
        if open_orders:
            _log.warning(
                "open_orders_detected",
                open_orders_count=len(open_orders),
            )
            return False
        return True

    def _post_private(self, url_path: str, params: dict[str, str] | None = None) -> dict:
        nonce = str(int(time.time() * 1000))
        post_data: dict[str, str] = {"nonce": nonce}
        if params:
            post_data.update(params)

        encoded = urllib.parse.urlencode(post_data)
        message = (nonce + encoded).encode()
        sha256_hash = hashlib.sha256(message).digest()

        try:
            hmac_key = base64.b64decode(self._api_secret)
        except Exception as exc:  # pragma: no cover - defensive only
            raise KrakenAuthError("Invalid Kraken API secret encoding") from exc

        signature = hmac.new(
            hmac_key,
            url_path.encode() + sha256_hash,
            hashlib.sha512,
        ).digest()
        api_sign = base64.b64encode(signature).decode()

        headers = {
            "API-Key": self._api_key,
            "API-Sign": api_sign,
        }

        response = httpx.post(
            f"{self._base_url}{url_path}",
            data=post_data,
            headers=headers,
            timeout=self._timeout,
        )
        if response.status_code != 200:
            raise KrakenAuthError(f"Kraken auth HTTP status {response.status_code}")

        payload = response.json()
        errors = payload.get("error")
        if isinstance(errors, list) and errors:
            raise KrakenAuthError(f"Kraken auth API error: {errors}")

        return payload
