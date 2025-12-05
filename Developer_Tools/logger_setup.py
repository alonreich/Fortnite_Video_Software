import logging
import sys

def setup_logger():
    """Sets up and returns a configured logger for the application."""
    logger = logging.getLogger("CropToolLogger")
    logger.setLevel(logging.INFO)
    
    # Prevent adding multiple handlers if called more than once
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger
