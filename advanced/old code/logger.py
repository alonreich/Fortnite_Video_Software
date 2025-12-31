import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logger():
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'Advanced_Editor_App.log')
    logger = logging.getLogger("Advanced_Video_Editor")
    logger.setLevel(logging.INFO)
    if logger.hasHandlers():
        return logger
    handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger