import logging
from logging.handlers import RotatingFileHandler
import os


def setup_logger(name='quant_sentinel', log_file='logs/sentinel.log', level=logging.INFO):
    """Konfiguruje logger z rotacją plików (max 5MB, 5 kopii)."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Handler plikowy z rotacją
    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5)
    file_handler.setLevel(level)

    # Handler konsolowy (opcjonalnie)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)

    # Formatowanie
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# Globalny logger
logger = setup_logger()