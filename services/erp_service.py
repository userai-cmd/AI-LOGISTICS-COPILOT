from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from db.postgres import ClaimsRepository

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TtnStatus:
    ttn: str
    status: str
    location: str
    eta: str


_BASE_RATES_BY_CITY_SUFFIX: dict[str, float] = {
    "Kyiv": 120.0,
    "Київ": 120.0,
    "Kharkiv": 150.0,
    "Lviv": 140.0,
    "Львів": 140.0,
    "Odesa": 135.0,
    "UNKNOWN": 130.0,
}


class ErpService:
    """Mock ERP / 1C bridge + claims persistence."""

    def __init__(self, claims: ClaimsRepository | None = None) -> None:
        self._claims = claims

    async def get_ttn_status(self, number: str) -> TtnStatus:
        digest = hashlib.sha256(number.encode("utf-8")).hexdigest()[:12]
        # Deterministic faux statuses for QA / demos (not real 1C).
        statuses = ["у дорозі", "на складі", "видано отримувачу", "митне оформлення"]
        idx = int(digest[:2], 16) % len(statuses)
        return TtnStatus(
            ttn=number,
            status=statuses[idx],
            location=f"хаб-{digest[-3:]}",
            eta="1–3 робочих дні" if statuses[idx] != "видано отримувачу" else "—",
        )

    async def calculate_delivery_cost(self, weight_kg: float, city: str) -> tuple[float, str]:
        normalized = city.strip() or "UNKNOWN"
        base = None
        lowered = normalized.lower()
        for key, rate in _BASE_RATES_BY_CITY_SUFFIX.items():
            if key.lower() in lowered:
                base = rate
                break
        base = base or _DEFAULT_BASE_RATE()
        surcharge = max(0.0, weight_kg - 1.0) * 18.5
        total = round(base + surcharge, 2)
        readable = (
            f"Базова ставка для «{normalized}»: {base:.2f}; "
            f"доплата за понадну вагу: {surcharge:.2f}; орієнтовно разом: {total:.2f} (мок, не оферта)."
        )
        return total, readable

    async def register_damage(self, *, ttn: str, details: str, user_id: int | None) -> str:
        if self._claims is None:
            log.warning("ClaimsRepository missing; skipping DB insert for TTN=%s", ttn)
            return "claim_logged_locally_skipped_db"
        row = await self._claims.register_damage(ttn=ttn, user_id=user_id, details=details)
        return str(row.get("id"))


def _DEFAULT_BASE_RATE() -> float:
    return _BASE_RATES_BY_CITY_SUFFIX["UNKNOWN"]
