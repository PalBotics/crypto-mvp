"""Exchange adapter exception types.

Defines the exception hierarchy for exchange adapter errors, allowing
collectors and trading engines to handle different error types appropriately.
"""


class ExchangeError(Exception):
    """Base exception for all exchange adapter errors.

    Use this as the base class for all exchange-specific errors.
    Catch this to handle all exchange-related failures.
    """


class ExchangeConnectionError(ExchangeError):
    """Network or connectivity problem.

    Raised when network requests fail due to timeouts, connection errors,
    or server errors (5xx). These are typically transient and may succeed on retry.
    """


class ExchangeAuthenticationError(ExchangeError):
    """API authentication failed.

    Raised when API credentials are invalid or missing. These errors typically
    require configuration changes and won't resolve with retries.
    """


class ExchangeRateLimitError(ExchangeError):
    """Exchange rate limit reached.

    Raised when the exchange returns HTTP 429. Clients should back off and
    retry after the specified delay (check Retry-After header).
    """


class ExchangeOrderError(ExchangeError):
    """Order placement or cancellation failure.

    Raised when order operations fail due to invalid parameters, insufficient
    funds, or other order-specific issues.
    """