from __future__ import annotations

import re


_AGGRESSIVE = re.compile(
    r"|".join(
        [
            # Ukrainian / Russian rough signals (coverage for contact-center tone alerts)
            r"\bсука\b",
            r"\b[\w]*хуй[\w]*\b",
            r"\b\dолб[oа]ё\w*\b",
            r"\bідіот\w*\b",
            r"\bдурак\w*\b",
            r"\bдибіл\w*\b",
            r"\bscam\b",
            r"\bfraud\b",
            r"[?!]{5,}",
        ]
    ),
    re.IGNORECASE | re.UNICODE,
)


def is_aggressive_tone(text: str) -> bool:
    if not text.strip():
        return False
    if _AGGRESSIVE.search(text):
        return True
    letters = sum(1 for ch in text if ch.isalpha())
    if letters >= 20:
        uppercase = sum(1 for ch in text if ch.isupper())
        if uppercase / letters > 0.55:
            return True
    return False
