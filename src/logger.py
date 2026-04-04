"""
src/logger.py - Professional logging configuration
UTF-8 compliant with graceful Unicode handling
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler


class UnicodeStreamHandler(logging.StreamHandler):
    """
    Custom stream handler with graceful Unicode encoding fallback.
    Handles non-ASCII characters without raising UnicodeEncodeError.
    """

    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            # Try to encode with current system encoding
            stream.write(msg + self.terminator)
            self.flush()
        except UnicodeEncodeError:
            try:
                # Fallback 1: Use 'replace' strategy (replace problematic chars with ?)
                msg = self.format(record)
                # Remove emoji and non-ASCII characters
                safe_msg = ''.join(c if ord(c) < 128 else '?' for c in msg)
                stream = self.stream
                stream.write(safe_msg + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)
        except Exception:
            self.handleError(record)


def setup_logger(name: str = 'quant_sentinel', level: int = logging.INFO) -> logging.Logger:
    """
    Professional logger setup with file and console handlers.

    Args:
        name: Logger name
        level: Logging level (INFO, DEBUG, etc)

    Returns:
        Configured logger instance
    """
    # Setup log directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(project_root, 'logs')
    log_file = os.path.join(log_dir, 'sentinel.log')
    os.makedirs(log_dir, exist_ok=True)

    # Get or create logger
    logger_instance = logging.getLogger(name)
    logger_instance.setLevel(level)

    # Prevent duplicate handlers
    if logger_instance.handlers:
        return logger_instance

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # File handler - UTF-8 with rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # Console handler - Unicode safe
    console_handler = UnicodeStreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # Add handlers
    logger_instance.addHandler(file_handler)
    logger_instance.addHandler(console_handler)
    logger_instance.propagate = False

    return logger_instance


# Create global logger instance
logger = setup_logger()

