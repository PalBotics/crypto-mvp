from __future__ import annotations

import base64
import hashlib
import hmac
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import requests

from core.config.settings import get_settings
from core.utils.logging import get_logger

_log = get_logger(__name__)


class ExchangeConnectionError(Exception):
    pass


class LiveModeDisabledError(Exception):
    pass


class CredentialValidationError(Exception):
    pass


class KrakenLiveAdapter:
    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key = api_key.strip()
        self._api_secret = api_secret.strip()
        self._base_url = "https://api.kraken.com"

    def get_eth_ticker(self) -> dict[str, Decimal | str]:
        url = f"{self._base_url}/0/public/Ticker"
        try:
            response = requests.get(url, params={"pair": "ETHUSD"}, timeout=10)
        except requests.RequestException as exc:
            raise ExchangeConnectionError("Kraken public ticker request failed") from exc

        if response.status_code != 200:
            raise ExchangeConnectionError(
                f"Kraken public ticker status {response.status_code}"
            )

        payload = response.json()
        errors = payload.get("error", [])
        if errors:
            raise ExchangeConnectionError("Kraken public ticker returned API errors")

        result = payload.get("result", {})
        ticker = result.get("XETHZUSD") or result.get("ETHUSD")
        if not isinstance(ticker, dict):
            raise ExchangeConnectionError("Kraken public ticker payload missing ETHUSD")

        try:
            bid = Decimal(str((ticker.get("b") or [None])[0]))
            ask = Decimal(str((ticker.get("a") or [None])[0]))
            last = Decimal(str((ticker.get("c") or [None])[0]))
        except Exception as exc:
            raise ExchangeConnectionError("Kraken public ticker price parsing failed") from exc

        return {
            "pair": "ETHUSD",
            "bid": bid,
            "ask": ask,
            "last": last,
        }

    def get_account_balance(self) -> dict[str, Decimal]:
        settings = get_settings()
        if not settings.live_mode:
            raise LiveModeDisabledError("LIVE_MODE is disabled")

        if not self._api_key or not self._api_secret:
            raise CredentialValidationError("Kraken live credentials are missing")

        endpoint_path = "/0/private/Balance"
        nonce = str(int(time.time() * 1000))
        post_data = {"nonce": nonce}
        post_body = urlencode(post_data)
        api_sign = self._sign(endpoint_path, nonce, post_body)

        headers = {
            "API-Key": self._api_key,
            "API-Sign": api_sign,
        }

        url = f"{self._base_url}{endpoint_path}"
        try:
            response = requests.post(url, headers=headers, data=post_data, timeout=10)
        except requests.RequestException as exc:
            raise ExchangeConnectionError("Kraken private balance request failed") from exc

        if response.status_code != 200:
            raise ExchangeConnectionError(
                f"Kraken private balance status {response.status_code}"
            )

        payload = response.json()
        errors = payload.get("error", [])
        if errors:
            raise CredentialValidationError("Kraken private balance returned API errors")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise ExchangeConnectionError("Kraken private balance payload missing result")

        balances: dict[str, Decimal] = {}
        for asset, raw_value in result.items():
            try:
                balances[str(asset)] = Decimal(str(raw_value))
            except Exception:
                continue
        return balances

    def validate_credentials(self) -> bool:
        try:
            self.get_account_balance()
            _log.info("kraken_live_credentials_valid")
            return True
        except Exception as exc:
            _log.error(
                "kraken_live_credentials_invalid",
                error_type=type(exc).__name__,
            )
            return False

    def _sign(self, path: str, nonce: str, post_body: str) -> str:
        sha256_hash = hashlib.sha256((nonce + post_body).encode("utf-8")).digest()
        message = path.encode("utf-8") + sha256_hash
        try:
            secret = base64.b64decode(self._api_secret)
        except Exception as exc:
            raise CredentialValidationError("Kraken secret is not valid base64") from exc

        mac = hmac.new(secret, message, hashlib.sha512)
        signature = base64.b64encode(mac.digest()).decode("utf-8")
        return signature
