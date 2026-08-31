"""
logging_config.py

Central logging setup so `uvicorn app.main:app --reload` in a VS Code
terminal prints readable, leveled logs for every stage of the pipeline
(ingestion/chunking and retrieval/chat) instead of relying on print()
scattered around the codebase.

Import and call `setup_logging()` once, at app startup (see main.py).
Every other module just does `logger = logging.getLogger(__name__)` and
logs normally -- this file only owns the *formatting/handler* config.
"""

import logging
import sys

# Toggle this (or set LOG_LEVEL=DEBUG in your environment) if you want
# even more detail, e.g. raw scores per chunk.
DEFAULT_LEVEL = logging.INFO

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-32s | %(message)s"
_DATEFMT = "%H:%M:%S"


def setup_logging(level: int = DEFAULT_LEVEL) -> None:
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. reload triggered this twice) -- avoid
        # duplicate log lines.
        root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))

    root.setLevel(level)
    root.addHandler(handler)

    # Quiet down noisy third-party loggers so your own pipeline logs
    # aren't buried under HTTP client chatter.
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)