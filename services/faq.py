from __future__ import annotations

import re

_FAQ_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(графік|режим|робот[аиу]|вихідні|свят\w+|коли\s+робот|\bhours\b)",
            re.IGNORECASE | re.UNICODE,
        ),
        (
            "Ми працюємо пн–пт 09:00–18:00, сб–нд — вихідні. "
            "У святкові дні графік може змінюватись — уточніть у вашого менеджера."
        ),
    ),
    (
        re.compile(r"\b(адрес\w+|склад|офіс|куди\s+(ж|при)|де\s+ви\s+)|(location|address)\b", re.IGNORECASE),
        (
            "Основний офіс та склад обслуговуються лише через менеджерів або за попередньою домовленістю. "
            "Конкретну адресу відвантаження вам озвучить оператор із вашого напряму."
        ),
    ),
]


def try_faq_response(text: str) -> str | None:
    trimmed = text.strip()
    if len(trimmed) < 6:
        return None
    for pattern, reply in _FAQ_RULES:
        if reply and pattern.search(trimmed):
            return reply.strip() or None
    return None
