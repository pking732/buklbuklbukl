"""
bot/services/settings.py — чтение настроек из таблицы `settings` (key-value).

Публичный интерфейс:
    get(key, default)  — строковое значение по ключу
    get_int(key, default) — целочисленное значение по ключу
    get_all()          — все настройки одним словарём
    refresh()          — принудительный сброс in-memory кэша

Кэш: простой словарь + метка времени последнего обновления.
TTL по умолчанию — 60 секунд. По истечении следующий вызов
автоматически перезагружает данные из БД.
"""

from __future__ import annotations

import time
from typing import Final

from bot import db

# ---------------------------------------------------------------------------
# Внутренний кэш
# ---------------------------------------------------------------------------

# Словарь key → value; None означает «кэш ещё не загружен»
_cache: dict[str, str] | None = None

# Время последней загрузки кэша (unix timestamp float); 0.0 — не загружался
_cache_loaded_at: float = 0.0

# Время жизни кэша в секундах
_CACHE_TTL: Final[int] = 60


def _is_cache_valid() -> bool:
    """Возвращает True, если кэш загружен и ещё не устарел."""
    return _cache is not None and (time.monotonic() - _cache_loaded_at) < _CACHE_TTL


async def _load_cache() -> dict[str, str]:
    """Загружает все настройки из БД и обновляет кэш."""
    global _cache, _cache_loaded_at

    rows = await db.fetch("SELECT key, value FROM settings")
    _cache = {row["key"]: row["value"] for row in rows}
    _cache_loaded_at = time.monotonic()
    return _cache


async def _get_cache() -> dict[str, str]:
    """Возвращает актуальный кэш (загружает при необходимости)."""
    if _is_cache_valid():
        return _cache  # type: ignore[return-value]
    return await _load_cache()


# ---------------------------------------------------------------------------
# Публичный интерфейс
# ---------------------------------------------------------------------------


async def refresh() -> None:
    """Принудительно сбрасывает in-memory кэш и перезагружает данные из БД."""
    await _load_cache()


async def get(key: str, default: str | None = None) -> str | None:
    """Возвращает строковое значение настройки по ключу.

    Args:
        key: ключ из таблицы settings (напр. 'support_username').
        default: значение, возвращаемое если ключ не найден.

    Returns:
        Строка из settings.value, либо default если ключ отсутствует.
    """
    cache = await _get_cache()
    return cache.get(key, default)


async def get_int(key: str, default: int = 0) -> int:
    """Возвращает целочисленное значение настройки по ключу.

    Если значение отсутствует или не является валидным int — возвращает default.

    Args:
        key: ключ из таблицы settings (напр. 'referral_threshold').
        default: значение при отсутствии ключа или ошибке парсинга.

    Returns:
        Целое число из settings.value, либо default.
    """
    raw = await get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        # Значение есть, но не конвертируется в int — возвращаем default
        return default


async def get_all() -> dict[str, str]:
    """Возвращает все настройки одним словарём {key: value}.

    Returns:
        Копия кэша на момент вызова. Пустой словарь если таблица пуста.
    """
    cache = await _get_cache()
    # Возвращаем копию, чтобы внешний код не мог случайно изменить кэш
    return dict(cache)
