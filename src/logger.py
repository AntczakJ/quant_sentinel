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
            except (UnicodeEncodeError, IOError, AttributeError):
                self.handleError(record)
        except (UnicodeEncodeError, IOError, AttributeError):
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


# ═══════════════════════════════════════════════════════════════════════════
#  JSON STRUCTURED LOGGING (for machine-parseable log output)
# ═══════════════════════════════════════════════════════════════════════════

import json
import datetime as _dt


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging. Outputs one JSON object per line."""

    def format(self, record):
        log_entry = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Attach extra structured fields if present
        for key in ("trade_id", "model", "action", "symbol", "pnl", "risk", "session"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_json_log_file(name: str = 'quant_sentinel') -> None:
    """
    Add a JSON-formatted file handler to the existing logger.
    Writes to logs/sentinel_structured.jsonl (one JSON object per line).
    Does not replace the existing human-readable handlers.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_log_path = os.path.join(project_root, 'logs', 'sentinel_structured.jsonl')

    existing = logging.getLogger(name)

    # Avoid duplicate JSON handlers
    for h in existing.handlers:
        if isinstance(h, RotatingFileHandler) and 'structured' in getattr(h, 'baseFilename', ''):
            return

    json_handler = RotatingFileHandler(
        json_log_path,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=3,
        encoding='utf-8'
    )
    json_handler.setLevel(logging.INFO)
    json_handler.setFormatter(JsonFormatter())
    existing.addHandler(json_handler)


# Create global logger instance
logger = setup_logger()

# Enable JSON structured log file alongside human-readable logs
try:
    setup_json_log_file()
except (OSError, PermissionError):
    pass  # JSON logging is optional

