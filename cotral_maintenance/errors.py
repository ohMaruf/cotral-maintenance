"""Exception hierarchy for the package.

Error messages must never contain the API key, so request URLs are not
included in any message.
"""


class CotralMaintenanceError(Exception):
    """Base class for all errors raised by this package."""


class ConfigError(CotralMaintenanceError):
    """Configuration is missing or invalid."""


class StopNotFoundError(CotralMaintenanceError):
    """A requested stop id does not exist in the GTFS data."""


class NoImageryError(CotralMaintenanceError):
    """No Street View panorama exists near the requested location.

    Recoverable: affects a single stop only.
    """


class ServerError(CotralMaintenanceError):
    """The API reported an internal error (UNKNOWN_ERROR) for this request.

    Recoverable: in practice it repeats for some locations (e.g. over water),
    so it is treated as "no result here" rather than retried.
    """


FATAL_API_STATUSES = frozenset({"HTTP_401", "HTTP_403", "HTTP_429", "REQUEST_DENIED", "OVER_QUERY_LIMIT",
                                "OVER_DAILY_LIMIT"})


class ApiError(CotralMaintenanceError):
    """The API rejected the request (bad key, API disabled, quota, bad params).

    Fatal: retrying with other stops would fail the same way.
    """

    def __init__(self, status: str, message: str = "") -> None:
        self.status = status
        super().__init__(f"{status}: {message}" if message else status)

    @property
    def fatal(self) -> bool:
        return self.status in FATAL_API_STATUSES


class TransportError(CotralMaintenanceError):
    """The request failed at the network/HTTP level, after retries."""
