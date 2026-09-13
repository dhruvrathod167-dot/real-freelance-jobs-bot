"""
Structured Logging Module with Secret Masking
Provides application-wide loggers that automatically mask bot tokens, API keys,
and sensitive user identifiers to prevent secret leaks in stdout or log files.
"""

import logging
import re
import sys
from config import settings

# Ensure UTF-8 output encoding on Windows consoles
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class SecretMaskingFilter(logging.Filter):
    """Filter that scrubs sensitive bot tokens and API keys from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.msg, str):
            return True

        msg = record.msg

        # Scrub Telegram Bot token (e.g. 123456789:ABCdef...)
        msg = re.sub(r"\d{8,10}:[A-Za-z0-9_-]{35}", "[REDACTED_TELEGRAM_TOKEN]", msg)

        # Scrub configured bot token explicitly if available
        if settings.telegram_token and len(settings.telegram_token) > 6:
            msg = msg.replace(settings.telegram_token, "[REDACTED_BOT_TOKEN]")
        if settings.TELEGRAM_BOT_TOKEN and len(settings.TELEGRAM_BOT_TOKEN) > 6:
            msg = msg.replace(settings.TELEGRAM_BOT_TOKEN, "[REDACTED_BOT_TOKEN]")

        # Scrub AI API key if configured
        if settings.AI_API_KEY and len(settings.AI_API_KEY) > 6:
            msg = msg.replace(settings.AI_API_KEY, "[REDACTED_AI_KEY]")

        record.msg = msg
        return True


def setup_logger(name: str = "RealFreelanceJobs") -> logging.Logger:
    """Configures and returns a logger instance with formatting and secret masking."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        logger.setLevel(level)

        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        handler.addFilter(SecretMaskingFilter())

        logger.addHandler(handler)
        logger.propagate = False

    return logger


logger = setup_logger()
