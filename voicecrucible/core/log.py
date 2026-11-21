"""Logging to the console and to a plain-text file, so every run can be followed and checked later."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(log_dir: Path | None, command: str, verbose: bool = False) -> Path | None:
    """Configure logging for one CLI command; returns the log file path (None = console only)."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{command}_{datetime.now():%Y%m%d_%H%M%S}.log"
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format=_FORMAT,
                        handlers=handlers, force=True)
    return log_file


def get(name: str) -> logging.Logger:
    """Return a logger named after the module that uses it."""
    return logging.getLogger(name)
