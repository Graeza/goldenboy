"""Application logging shared by the CLI and Qt log pump."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(directory=Path('logs')):
    logger = logging.getLogger('goldenboy')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        Path(directory).mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(Path(directory) / 'goldenboy.log',
                                      maxBytes=2_000_000, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        logger.addHandler(handler)
    return logger
