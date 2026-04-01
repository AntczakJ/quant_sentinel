# logger.py – wersja z obsługą kodowania
import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logger(name='quant_sentinel', level=logging.INFO):
    # Ścieżka do pliku logów
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(project_root, 'logs')
    log_file = os.path.join(log_dir, 'sentinel.log')
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Handler plikowy – zapisuje bez względu na kodowanie (UTF-8)
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setLevel(level)

    # Handler konsolowy – używa 'replace' dla niedozwolonych znaków
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    # Ustawienie obsługi błędów kodowania na 'replace' (zamiast domyślnego 'strict')
    console_handler.stream = open(os.devnull, 'w')  # tymczasowo, żeby nie psuć
    # Lepiej dodać własny handler z obsługą
    class SafeStreamHandler(logging.StreamHandler):
        def emit(self, record):
            try:
                super().emit(record)
            except UnicodeEncodeError:
                # Zastąp problematyczne znaki
                record.msg = record.msg.encode('ascii', 'replace').decode('ascii')
                super().emit(record)

    console_handler = SafeStreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False

    # Flush po każdym logu (opcjonalnie)
    file_handler.flush()

    return logger

logger = setup_logger()