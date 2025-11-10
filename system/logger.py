import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logger(base_dir):
    """Return a process‑wide logger writing into a project's root logs folder.

    The caller should pass the *project root* (not the UI folder) as
    ``base_dir``.  Logs will be stored under a lower‑case ``logs`` directory
    to align with the user's folder structure, rather than the
    capitalised ``Logs`` used in the original monolith.  The folder is
    created on demand.
    """
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "Fortnite-Video-Converter.log")
    logger = logging.getLogger("fvconv")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d | %H:%M:%S")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logging.addLevelName(logging.CRITICAL, "FATAL")
        logger.fatal = logger.critical
        logging.captureWarnings(True)
    return logger