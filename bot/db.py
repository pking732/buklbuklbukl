"""
bot/db.py — asyncpg connection pool и хелперы для работы с БД.

Инициализация: вызвать `await init_pool()` при старте бота.
Завершение: вызвать `await close_pool()` при остановке.
"""

from __future__ import annotations

import asyncpg

import bot.config as config

# Глобальный пул соединений; None — до первого вызова init_pool()
_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    """Создаёт глобальный asyncpg-пул из config.PG_DSN.

    Идемпотентно: если пул уже создан — ничего не делает.
    """
    global _pool
    if _pool is not None:
        return
    _pool = await asyncpg.create_pool(
        dsn=config.PG_DSN,
        min_size=1,
        max_size=10,
    )


async def close_pool() -> None:
    """Закрывает глобальный пул соединений."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    """Возвращает текущий пул.

    Raises:
        RuntimeError: если пул не был инициализирован через init_pool().
    """
    if _pool is None:
        raise RuntimeError("pool not initialized — call await init_pool() first")
    return _pool


# ---------------------------------------------------------------------------
# Хелперы — тонкие обёртки над asyncpg, чтобы не писать acquire() вручную
# ---------------------------------------------------------------------------


async def fetch(query: str, *args) -> list[asyncpg.Record]:
    """Выполняет SELECT и возвращает список строк."""
    async with pool().acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args) -> asyncpg.Record | None:
    """Выполняет SELECT и возвращает одну строку (или None)."""
    async with pool().acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args):
    """Выполняет SELECT и возвращает скалярное значение первой колонки первой строки."""
    async with pool().acquire() as conn:
        return await conn.fetchval(query, *args)


async def execute(query: str, *args) -> str:
    """Выполняет INSERT/UPDATE/DELETE и возвращает статусную строку (напр. 'INSERT 0 1')."""
    async with pool().acquire() as conn:
        return await conn.execute(query, *args)
