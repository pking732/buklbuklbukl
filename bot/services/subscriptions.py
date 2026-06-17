"""
services/subscriptions.py — ЕДИНСТВЕННАЯ точка изменения статуса подписки.

Правило из docs/03-modules-and-conflicts.md:
  статус subscriptions.status меняет ТОЛЬКО этот модуль.
  Хендлеры, webhook_server, scheduler вызывают здесь функции — не пишут в БД напрямую.

Порядок операций при совместном изменении БД + сервера:
  1. Сначала вызов vps_agent (может бросить исключение).
  2. Затем UPDATE в БД.
  Это гарантирует, что при ошибке агента БД не рассинхронизируется.
"""

from __future__ import annotations

import asyncpg
from datetime import datetime, timezone, timedelta

from bot import db
from bot.services import vps_agent


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

async def get(telegram_id: int) -> asyncpg.Record | None:
    """Вернуть строку subscriptions для пользователя, или None если не найдена."""
    return await db.fetchrow(
        "SELECT * FROM subscriptions WHERE telegram_id = $1",
        telegram_id,
    )


async def is_active(telegram_id: int) -> bool:
    """True если status='active'. Используется для доступа к разделу «Мои ключи»."""
    status = await db.fetchval(
        "SELECT status FROM subscriptions WHERE telegram_id = $1",
        telegram_id,
    )
    return status == "active"


# ---------------------------------------------------------------------------
# Инициализация строки
# ---------------------------------------------------------------------------

async def ensure_row(telegram_id: int) -> None:
    """
    Создать строку подписки при /start, если её ещё нет.
    Статус 'none', max_devices=0, device_key_id через vps_agent.device_key_id.
    INSERT ... ON CONFLICT DO NOTHING — идемпотентно.
    """
    dk = vps_agent.device_key_id(telegram_id)
    now = datetime.now(timezone.utc)
    await db.execute(
        """
        INSERT INTO subscriptions
            (telegram_id, status, device_key_id, max_devices,
             notified_expiring, created_at, updated_at)
        VALUES ($1, 'none', $2, 0, false, $3, $3)
        ON CONFLICT DO NOTHING
        """,
        telegram_id, dk, now,
    )


# ---------------------------------------------------------------------------
# Переходы статуса — новая покупка
# ---------------------------------------------------------------------------

async def activate_new(
    telegram_id: int,
    duration_days: int,
    max_devices: int,
) -> asyncpg.Record:
    """
    Новая покупка добросовестного пользователя.
    Создаём ключ на VPS, затем фиксируем 'active' в БД.
    Возвращает обновлённую строку subscriptions.
    """
    dk = vps_agent.device_key_id(telegram_id)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=duration_days)

    # 1. Сначала агент — при ошибке БД остаётся нетронутой
    result = await vps_agent.create_key(dk, expires_at, max_devices)

    # 2. Затем обновляем БД
    return await db.fetchrow(
        """
        UPDATE subscriptions
        SET status            = 'active',
            sub_url           = $2,
            sub_token         = $3,
            max_devices       = $4,
            expires_at        = $5,
            notified_expiring = false,
            updated_at        = $6
        WHERE telegram_id = $1
        RETURNING *
        """,
        telegram_id,
        result["subUrl"],
        result["subToken"],
        max_devices,
        expires_at,
        now,
    )


async def set_waiting(telegram_id: int) -> None:
    """
    Недобросовестный пользователь — ключ НЕ создаём.
    Ставим status='waiting_for_acceptance', ждём решения администратора.
    """
    now = datetime.now(timezone.utc)
    await db.execute(
        """
        UPDATE subscriptions
        SET status     = 'waiting_for_acceptance',
            updated_at = $2
        WHERE telegram_id = $1
        """,
        telegram_id, now,
    )


async def confirm_waiting(
    telegram_id: int,
    duration_days: int,
    max_devices: int,
) -> asyncpg.Record:
    """
    Администратор подтвердил оплату пользователя, который ждал проверки.
    Логика идентична activate_new: создаём ключ, status='active'.
    Возвращает обновлённую строку subscriptions.
    """
    dk = vps_agent.device_key_id(telegram_id)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=duration_days)

    # 1. Сначала агент
    result = await vps_agent.create_key(dk, expires_at, max_devices)

    # 2. Затем БД
    return await db.fetchrow(
        """
        UPDATE subscriptions
        SET status            = 'active',
            sub_url           = $2,
            sub_token         = $3,
            max_devices       = $4,
            expires_at        = $5,
            notified_expiring = false,
            updated_at        = $6
        WHERE telegram_id = $1
        RETURNING *
        """,
        telegram_id,
        result["subUrl"],
        result["subToken"],
        max_devices,
        expires_at,
        now,
    )


# ---------------------------------------------------------------------------
# Продление
# ---------------------------------------------------------------------------

async def extend(
    telegram_id: int,
    duration_days: int,
) -> asyncpg.Record:
    """
    Продление подписки (всегда оптимистично).
    База: текущий expires_at если в будущем, иначе now().
    При отсутствии ключа на сервере — fallback на create_key с max_devices из строки.
    Возвращает обновлённую строку subscriptions.
    """
    dk = vps_agent.device_key_id(telegram_id)
    now = datetime.now(timezone.utc)

    row = await get(telegram_id)
    current_expires = row["expires_at"] if row else None

    # Вычисляем базу для продления
    if current_expires is not None and current_expires > now:
        base = current_expires
    else:
        base = now

    new_expires = base + timedelta(days=duration_days)

    # 1. Сначала агент: пробуем extend, при отсутствии ключа — пересоздаём
    try:
        await vps_agent.extend_key(dk, new_expires)
    except Exception:
        # Fallback: ключа нет на сервере — создаём заново
        max_dev = row["max_devices"] if row else 1
        result = await vps_agent.create_key(dk, new_expires, max_dev)
        # Обновляем sub_url/sub_token тоже
        return await db.fetchrow(
            """
            UPDATE subscriptions
            SET status            = 'active',
                sub_url           = $2,
                sub_token         = $3,
                expires_at        = $4,
                notified_expiring = false,
                updated_at        = $5
            WHERE telegram_id = $1
            RETURNING *
            """,
            telegram_id,
            result["subUrl"],
            result["subToken"],
            new_expires,
            now,
        )

    # 2. Затем БД (обычный extend)
    return await db.fetchrow(
        """
        UPDATE subscriptions
        SET expires_at        = $2,
            status            = 'active',
            notified_expiring = false,
            updated_at        = $3
        WHERE telegram_id = $1
        RETURNING *
        """,
        telegram_id, new_expires, now,
    )


async def rollback_extension(
    telegram_id: int,
    duration_days: int,
) -> None:
    """
    Откат продления при reject администратором.
    Вычитаем ровно ту дельту duration_days, что была начислена.
    """
    dk = vps_agent.device_key_id(telegram_id)
    now = datetime.now(timezone.utc)

    row = await get(telegram_id)
    current_expires = row["expires_at"] if row else now
    new_expires = current_expires - timedelta(days=duration_days)

    # 1. Сначала агент
    await vps_agent.extend_key(dk, new_expires)

    # 2. Затем БД
    await db.execute(
        """
        UPDATE subscriptions
        SET expires_at = $2,
            updated_at = $3
        WHERE telegram_id = $1
        """,
        telegram_id, new_expires, now,
    )


# ---------------------------------------------------------------------------
# Отключение / блокировка
# ---------------------------------------------------------------------------

async def disable_and_expire(telegram_id: int) -> None:
    """
    Reject добросовестной новой покупки (applied_optimistically=true).
    Отключаем ключ на сервере, ставим status='expired'.
    """
    dk = vps_agent.device_key_id(telegram_id)
    now = datetime.now(timezone.utc)

    # 1. Сначала агент
    await vps_agent.disable_key(dk)

    # 2. Затем БД
    await db.execute(
        """
        UPDATE subscriptions
        SET status     = 'expired',
            expires_at = $2,
            updated_at = $2
        WHERE telegram_id = $1
        """,
        telegram_id, now,
    )


async def mark_expired(telegram_id: int) -> None:
    """
    Вызывается из webhook_server при колбэке экспирации от VPS-агента.
    Сервер УЖЕ удалил ключ — disable_key НЕ вызываем, только фиксируем статус.
    """
    now = datetime.now(timezone.utc)
    await db.execute(
        """
        UPDATE subscriptions
        SET status     = 'expired',
            updated_at = $2
        WHERE telegram_id = $1
        """,
        telegram_id, now,
    )


# ---------------------------------------------------------------------------
# Вспомогательные флаги и джобы
# ---------------------------------------------------------------------------

async def set_notified(telegram_id: int, value: bool) -> None:
    """Выставить notified_expiring. Используется джобом напоминаний."""
    now = datetime.now(timezone.utc)
    await db.execute(
        """
        UPDATE subscriptions
        SET notified_expiring = $2,
            updated_at        = $3
        WHERE telegram_id = $1
        """,
        telegram_id, value, now,
    )


async def list_expiring(within_hours: int) -> list[asyncpg.Record]:
    """
    Для джоба напоминаний (APScheduler).
    Возвращает активные подписки, истекающие в пределах within_hours,
    которым ещё не отправлено уведомление.
    """
    now = datetime.now(timezone.utc)
    threshold = now + timedelta(hours=within_hours)
    return await db.fetch(
        """
        SELECT * FROM subscriptions
        WHERE status            = 'active'
          AND expires_at       <= $1
          AND notified_expiring = false
        """,
        threshold,
    )


async def list_active() -> list[asyncpg.Record]:
    """
    Для джоба учёта трафика (APScheduler).
    Возвращает все строки со status='active'.
    """
    return await db.fetch(
        "SELECT * FROM subscriptions WHERE status = 'active'"
    )
