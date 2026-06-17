"""
Сервис платежей (payments) и черного списка (fraud_list).
Владеет таблицами payments и fraud_list — только этот модуль их пишет.
"""

from __future__ import annotations

import asyncpg
from datetime import datetime, timezone

from bot import db
from bot.services import subscriptions, referrals


# ---------------------------------------------------------------------------
# Вспомогательная функция
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    """Текущее время UTC."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# fraud_list
# ---------------------------------------------------------------------------

async def is_fraud(telegram_id: int) -> bool:
    """Проверить, есть ли пользователь в списке недобросовестных."""
    val = await db.fetchval(
        "SELECT 1 FROM fraud_list WHERE telegram_id = $1",
        telegram_id,
    )
    return val is not None


async def add_fraud(
    telegram_id: int,
    reason: str,
    related_payment_id: int | None,
) -> None:
    """Добавить пользователя в fraud_list. При повторном вызове — ничего не делает (ON CONFLICT DO NOTHING)."""
    await db.execute(
        """
        INSERT INTO fraud_list (telegram_id, reason, related_payment_id, added_at)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING
        """,
        telegram_id,
        reason,
        related_payment_id,
        _now_utc(),
    )


# ---------------------------------------------------------------------------
# Основные операции с payments
# ---------------------------------------------------------------------------

async def create_and_apply(
    telegram_id: int,
    tariff_code: str,
    amount_rub,
    duration_days: int,
    max_devices: int,
    kind: str,
    sender_name: str,
) -> dict:
    """
    Создать платёжную заявку и СРАЗУ применить доступ согласно §5 бизнес-логики.

    kind ∈ {'purchase', 'extension'}

    Возвращает dict {payment_id, kind, outcome}.
    outcome: 'active' | 'waiting' | 'extended'
    """
    # --- Определяем, применяем ли оптимистично ---
    if kind == "extension":
        applied_optimistically = True
    else:
        # purchase: оптимистично только для добросовестных
        fraud = await is_fraud(telegram_id)
        applied_optimistically = not fraud

    # --- INSERT payments ---
    payment_id: int = await db.fetchval(
        """
        INSERT INTO payments (
            telegram_id, tariff_code, amount_rub, duration_days, max_devices,
            kind, sender_name, status, applied_optimistically, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8, $9)
        RETURNING id
        """,
        telegram_id,
        tariff_code,
        amount_rub,
        duration_days,
        max_devices,
        kind,
        sender_name,
        applied_optimistically,
        _now_utc(),
    )

    # --- Применяем доступ ---
    if kind == "purchase" and applied_optimistically:
        # Добросовестный новый покупатель — сразу активируем
        await subscriptions.activate_new(telegram_id, duration_days, max_devices)
        outcome = "active"
    elif kind == "purchase" and not applied_optimistically:
        # Недобросовестный — ставим в режим ожидания проверки
        await subscriptions.set_waiting(telegram_id)
        outcome = "waiting"
    else:
        # kind == 'extension' — всегда оптимистично продлеваем
        await subscriptions.extend(telegram_id, duration_days)
        outcome = "extended"

    return {"payment_id": payment_id, "kind": kind, "outcome": outcome}


async def get(payment_id: int) -> asyncpg.Record | None:
    """Получить строку платежа по id."""
    return await db.fetchrow(
        "SELECT * FROM payments WHERE id = $1",
        payment_id,
    )


async def list_pending() -> list[asyncpg.Record]:
    """Вернуть все платежи со статусом 'pending', отсортированные по дате создания."""
    return await db.fetch(
        "SELECT * FROM payments WHERE status = 'pending' ORDER BY created_at ASC",
    )


# ---------------------------------------------------------------------------
# Решение администратора
# ---------------------------------------------------------------------------

async def approve(payment_id: int, admin_id: int) -> dict:
    """
    Подтвердить платёж (§6).

    Возвращает:
    - {ok: False, reason: 'not_pending'} если заявка уже обработана
    - {ok: True, buyer_telegram_id, kind, was_waiting, referral_gift}
    """
    # Загружаем заявку
    payment = await get(payment_id)
    if payment is None or payment["status"] != "pending":
        return {"ok": False, "reason": "not_pending"}

    tg: int = payment["telegram_id"]
    kind: str = payment["kind"]
    duration_days: int = payment["duration_days"]
    max_devices: int = payment["max_devices"]

    # Обновляем статус
    await db.execute(
        """
        UPDATE payments
        SET status = 'approved', admin_id = $2, processed_at = $3
        WHERE id = $1
        """,
        payment_id,
        admin_id,
        _now_utc(),
    )

    # Проверяем, был ли пользователь в статусе ожидания (недобросовестный purchase)
    sub = await subscriptions.get(tg)
    was_waiting = sub is not None and sub["status"] == "waiting_for_acceptance"

    if was_waiting:
        # Подтверждаем ожидавшую подписку (VPS-ключ создаётся внутри confirm_waiting)
        await subscriptions.confirm_waiting(tg, duration_days, max_devices)

    # Реферальная проверка — только для покупок (§7)
    gift = None
    if kind == "purchase":
        gift = await referrals.on_purchase_approved(tg, payment_id)

    return {
        "ok": True,
        "buyer_telegram_id": tg,
        "kind": kind,
        "was_waiting": was_waiting,
        "referral_gift": gift,
    }


async def reject(payment_id: int, admin_id: int) -> dict:
    """
    Отклонить платёж (§6).

    Возвращает:
    - {ok: False, reason: 'not_pending'} если заявка уже обработана
    - {ok: True, buyer_telegram_id, kind}
    """
    # Загружаем заявку
    payment = await get(payment_id)
    if payment is None or payment["status"] != "pending":
        return {"ok": False, "reason": "not_pending"}

    tg: int = payment["telegram_id"]
    kind: str = payment["kind"]
    duration_days: int = payment["duration_days"]
    applied_optimistically: bool = payment["applied_optimistically"]

    # Обновляем статус
    await db.execute(
        """
        UPDATE payments
        SET status = 'rejected', admin_id = $2, processed_at = $3
        WHERE id = $1
        """,
        payment_id,
        admin_id,
        _now_utc(),
    )

    if kind == "purchase":
        if applied_optimistically:
            # Добросовестный: отключаем выданный ключ, помечаем как мошенника
            await subscriptions.disable_and_expire(tg)
            await add_fraud(tg, "payment rejected", payment_id)
        else:
            # Недобросовестный (был waiting_for_acceptance): ключа не было, ничего не откатываем
            pass
    elif kind == "extension":
        # Продление: откатываем ранее добавленные дни
        await subscriptions.rollback_extension(tg, duration_days)

    return {"ok": True, "buyer_telegram_id": tg, "kind": kind}
