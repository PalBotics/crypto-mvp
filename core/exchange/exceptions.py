class ExchangeError(Exception):
    """Base exchange error."""


class ExchangeConnectionError(ExchangeError):
    """Network or connectivity problem."""


class ExchangeAuthenticationError(ExchangeError):
    """API authentication failed."""


class ExchangeRateLimitError(ExchangeError):
    """Exchange rate limit reached."""


class ExchangeOrderError(ExchangeError):
    """Order placement or cancellation failure."""