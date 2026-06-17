"""
Сервис пользователей: владеет базовыми полями таблицы users
(telegram_id, username, first_name, created_at, last_start_at).
Колонкой referred_by владеет referrals.py — её здесь не трогаем.
"""
from __future__ import annotations

import asyncpg

from bot import db


async def register_or_touch(
    telegram_id: int,
    username: str | None,
    first_name: str | None,
) -> bool:
    """
    Регистрирует пользователя при первом /start или обновляет last_start_at/профиль.
    Возвращает True, если пользователь НОВЫЙ (создан этим вызовом), иначе False.
    referred_by здесь НЕ трогаем (это зона referrals.link_on_start).
    """
    row = await db.fetchrow(
        """
        INSERT INTO users (telegram_id, username, first_name, created_at, last_start_at)
        VALUES ($1, $2, $3, now(), now())
        ON CONFLICT (telegram_id) DO NOTHING
        RETURNING telegram_id
        """,
        telegram_id,
        username,
        first_name,
    )
    is_new = row is not None
    if not is_new:
        # Уже был — обновим профиль и время последнего старта.
        await db.execute(
            """
            UPDATE users
            SET username = $2, first_name = $3, last_start_at = now()
            WHERE telegram_id = $1
            """,
            telegram_id,
            username,
            first_name,
        )
    return is_new


async def get(telegram_id: int) -> asyncpg.Record | None:
    """Полная строка пользователя или None."""
    return await db.fetchrow(
        "SELECT * FROM users WHERE telegram_id = $1",
        telegram_id,
    )


async def get_username(telegram_id: int) -> str | None:
    """Username пользователя (без @) или None."""
    return await db.fetchval(
        "SELECT username FROM users WHERE telegram_id = $1",
        telegram_id,
    )
