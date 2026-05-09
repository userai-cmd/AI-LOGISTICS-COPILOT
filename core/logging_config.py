import logging
import sys


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    if root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)
    log_level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(log_level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    handler.setFormatter(fmt)
    root.addHandler(handler)
