"""Log em arquivo (%LOCALAPPDATA%/AvantHidro/logs/avant-hidro.log) e no console."""

from __future__ import annotations

import logging
import logging.handlers
import os

from ..branding import APP_SLUG, LOG_DIRECTORY


def log_dir() -> str:
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    path = os.path.join(base, LOG_DIRECTORY, 'logs')
    os.makedirs(path, exist_ok=True)
    return path


def log_path() -> str:
    return os.path.join(log_dir(), APP_SLUG + '.log')


def setup_logging(level=logging.INFO):
    root = logging.getLogger()
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return
    root.setLevel(level)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    fh = logging.handlers.RotatingFileHandler(log_path(), maxBytes=2_000_000, backupCount=3,
                                              encoding='utf-8')
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    root.addHandler(sh)
