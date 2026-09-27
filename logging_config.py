import logging
import os
from concurrent_log_handler import ConcurrentRotatingFileHandler
from pathlib import Path


DEFAULT_LOG_DIR = "logs"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_BACKUP_COUNT = 10
DEFAULT_CELERY_LOGGER = "celery"

LOG_FORMAT = (
    "%(asctime)s | "
    "%(levelname)-8s | "
    "%(name)s | "
    "%(message)s"
)

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(
    *,
    log_dir: str | None = None,
    level: int = logging.INFO,
) -> None:
    """
    Configure application-wide logging.

    Application logs:
        logs/application.log

    Celery logs:
        logs/celery.log

    Both files use concurrent-safe rotating handlers.

    Rotation:
        10 MB per file
        10 backup files

    Console output remains enabled.

    The function is idempotent.
    """

    log_directory = Path(
        log_dir
        or os.getenv("LOG_DIR", DEFAULT_LOG_DIR)
    )

    log_directory.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt=LOG_FORMAT,
        datefmt=DATE_FORMAT,
    )

    # ---------------------------------------------------------
    # Root / application logger
    # ---------------------------------------------------------

    root_logger = logging.getLogger()
    root_logger.setLevel(level)


    application_file_exists = any(
        isinstance(handler, ConcurrentRotatingFileHandler)
        and getattr(handler, "baseFilename", "").endswith(
            str(Path("application.log"))
        )
        for handler in root_logger.handlers
    )

    if not application_file_exists:
        application_log_path = log_directory / "application.log"

        file_handler = ConcurrentRotatingFileHandler(
            application_log_path,
            maxBytes=DEFAULT_MAX_BYTES,
            backupCount=DEFAULT_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)

        root_logger.addHandler(file_handler)

    console_exists = any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, ConcurrentRotatingFileHandler)
        for handler in root_logger.handlers
    )

    if not console_exists:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)

        root_logger.addHandler(console_handler)

    # ---------------------------------------------------------
    # Celery logger
    # ---------------------------------------------------------

    celery_logger = logging.getLogger(DEFAULT_CELERY_LOGGER)
    celery_logger.setLevel(level)
    celery_logger.propagate = False

    celery_log_exists = any(
        isinstance(handler, ConcurrentRotatingFileHandler)
        and getattr(handler, "baseFilename", "").endswith(
            str(Path("celery.log"))
        )
        for handler in celery_logger.handlers
    )

    if not celery_log_exists:
        celery_log_path = log_directory / "celery.log"

        celery_file_handler = ConcurrentRotatingFileHandler(
            celery_log_path,
            maxBytes=DEFAULT_MAX_BYTES,
            backupCount=DEFAULT_BACKUP_COUNT,
            encoding="utf-8",
        )
        celery_file_handler.setLevel(level)
        celery_file_handler.setFormatter(formatter)

        celery_logger.addHandler(celery_file_handler)
def get_logger(name: str) -> logging.Logger:
    """
    Return a logger using the application's logging configuration.
    """
    return logging.getLogger(name)