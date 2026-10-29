"""Logging configuration: console output plus a rotating log file.

Call `setup_logging` once at program start; modules then use
`logging.getLogger(__name__)` as usual.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
MAX_LOG_BYTES = 5_000_000
LOG_BACKUP_COUNT = 3

# Third-party loggers that would otherwise log request URLs, which contain the API key.
NOISY_LOGGERS = ("urllib3", "requests")


def setup_logging(log_file: Path, console_level: int = logging.INFO) -> None:
    """Send logs to the console at `console_level` and to `log_file` at DEBUG."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
