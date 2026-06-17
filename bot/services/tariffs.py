"""
Сервис тарифов: чтение каталога tariffs (рендерится в кнопки, цены не захардкожены).
Только чтение — каталог правится в БД.
"""
from __future__ import annotations

import asyncpg

from bot import db


async def list_active() -> list[asyncpg.Record]:
    """Активные тарифы в порядке sort_order — для рендеринга кнопок."""
    return await db.fetch(
        """
        SELECT id, code, title, price_rub, duration_days, max_devices, sort_order, is_active
        FROM tariffs
        WHERE is_active = true
        ORDER BY sort_order, id
        """
    )


async def get_by_code(code: str) -> asyncpg.Record | None:
    """Тариф по коду."""
    return await db.fetchrow("SELECT * FROM tariffs WHERE code = $1", code)


async def get_by_title(title: str) -> asyncpg.Record | None:
    """
    Тариф по тексту кнопки (title). Используется payment-хендлером, чтобы сопоставить
    нажатую reply-кнопку с тарифом. Берём только активные.
    """
    return await db.fetchrow(
        "SELECT * FROM tariffs WHERE title = $1 AND is_active = true",
        title,
    )
