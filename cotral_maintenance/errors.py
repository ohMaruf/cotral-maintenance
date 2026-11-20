class CotralMaintenanceError(Exception):
    ...


class ConfigError(CotralMaintenanceError):
    ...


class StopNotFoundError(CotralMaintenanceError):
    ...


class NoImageryError(CotralMaintenanceError):
    ...


class ServerError(CotralMaintenanceError):
    ...


FATAL_API_STATUSES = frozenset({"HTTP_401", "HTTP_403", "HTTP_429", "REQUEST_DENIED", "OVER_QUERY_LIMIT",
                                "OVER_DAILY_LIMIT"})


class ApiError(CotralMaintenanceError):
    def __init__(self, status: str, message: str = "") -> None:
        self.status = status
        super().__init__(f"{status}: {message}" if message else status)

    @property
    def fatal(self) -> bool:
        return self.status in FATAL_API_STATUSES


class TransportError(CotralMaintenanceError):
    ...
