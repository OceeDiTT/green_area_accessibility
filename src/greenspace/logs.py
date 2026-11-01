import logging
import os
import sys


def setup_logging(level: str | None = None) -> None:
    level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(level=level, stream=sys.stdout, force=True,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    for noisy in ("urllib3", "fiona", "pyogrio", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
