import logging
import os
from logging.handlers import RotatingFileHandler
_handler_configured = False

def setup_logger(base_dir, name="Main_App"):
    """
    Configures a single rotating file handler on the root logger the first
    time it's called, then returns a specific named logger.
    """
    global _handler_configured
    if not _handler_configured:
        log_dir = os.path.join(base_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "Fortnite_Video_Compressor_App.log")
        handler = RotatingFileHandler(log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(fmt)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)
        logging.addLevelName(logging.CRITICAL, "FATAL")
        logging.captureWarnings(True)
        _handler_configured = True
    return logging.getLogger(name)