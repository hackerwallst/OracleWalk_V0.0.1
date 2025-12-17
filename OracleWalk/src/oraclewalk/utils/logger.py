# file: oraclewalk/utils/logger.py

import logging
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logger(name: str = "OracleWalk", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # já configurado

    logger.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)

    fh = logging.FileHandler("oraclewalk.log", encoding="utf-8")
    fh.setFormatter(formatter)

    logger.addHandler(ch)
    logger.addHandler(fh)

    return logger
