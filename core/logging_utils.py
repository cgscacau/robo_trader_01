# core/logging_utils.py

import logging
import json
import sys
import os
from typing import Optional, Dict, Any


class JsonFormatter(logging.Formatter):
    """
    Formatter simples que gera logs em JSON.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_record: Dict[str, Any] = {
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, self.datefmt),
        }

        # Adiciona extras (campos customizados passados em extra=)
        for key, value in record.__dict__.items():
            if key in (
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            ):
                continue
            log_record[key] = value

        return json.dumps(log_record, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_logs: bool = True, filename: Optional[str] = None) -> None:
    """
    Configura logging global do app.
    - level: "DEBUG", "INFO", "WARNING", etc.
    - json_logs: se True, logs em JSON
    - filename: se fornecido, também grava em arquivo
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(numeric_level)

    # Limpa handlers existentes para evitar duplicação
    if logger.handlers:
        for h in list(logger.handlers):
            logger.removeHandler(h)

    # Formatter
    if json_logs:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Handler de console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler de arquivo opcional
    if filename:
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
        except Exception:
            pass
        file_handler = logging.FileHandler(filename, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
