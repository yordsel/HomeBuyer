"""Logging configuration for the HomeBuyer application."""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
) -> logging.Logger:
    """Configure structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        log_file: Optional path to a log file. If None, logs to console only.

    Returns:
        The root logger for the homebuyer package.
    """
    root_logger = logging.getLogger("homebuyer")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (always)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_file))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Quiet down noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    return root_logger
