"""
Реферальный сервис: владеет записями referral_progress, referral_events
и колонкой users.referred_by. Не трогает payments напрямую.
"""

from __future__ import annotations

from bot import db
from bot.services import settings
from bot.services import subscriptions


async def ensure_progress(telegram_id: int) -> None:
    """Создать строку referral_progress с нулевыми счётчиками, если её нет."""
    await db.execute(
        """
        INSERT INTO referral_progress (telegram_id, confirmed_count, gifts_received, updated_at)
        VALUES ($1, 0, 0, now())
        ON CONFLICT (telegram_id) DO NOTHING
        """,
        telegram_id,
    )


async def link_on_start(
    new_telegram_id: int,
    referrer_telegram_id: int | None,
) -> bool:
    """
    Привязать реферера при первом /start нового пользователя (§1).

    Условия привязки:
    - referrer_telegram_id не None и не совпадает с new_telegram_id;
    - реферер существует в таблице users;
    - у нового пользователя users.referred_by сейчас NULL.

    Возвращает True, если привязка была установлена.
    """
    if referrer_telegram_id is None or referrer_telegram_id == new_telegram_id:
        return False

    # Проверяем, что реферер существует в users
    referrer_exists: bool = await db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM users WHERE telegram_id = $1)",
        referrer_telegram_id,
    )
    if not referrer_exists:
        return False

    # Атомарно ставим referred_by только если оно NULL
    result = await db.fetchrow(
        """
        UPDATE users
        SET referred_by = $2
        WHERE telegram_id = $1
          AND referred_by IS NULL
        RETURNING telegram_id
        """,
        new_telegram_id,
        referrer_telegram_id,
    )
    return result is not None


async def on_purchase_approved(
    buyer_telegram_id: int,
    payment_id: int,
) -> dict | None:
    """
    Обработать реферальную цепочку при подтверждении НОВОЙ покупки (kind='purchase') (§7).

    Возвращает {'referrer_id': int, 'new_expires_at': datetime} если реферер получил подарок,
    иначе None (прогресс мог быть увеличен без выдачи подарка).
    """
    # Получаем реферера покупателя
    referrer_id: int | None = await db.fetchval(
        "SELECT referred_by FROM users WHERE telegram_id = $1",
        buyer_telegram_id,
    )
    if referrer_id is None:
        return None

    # Пытаемся вставить событие; UNIQUE на referred_id гарантирует одну запись
    event_row = await db.fetchrow(
        """
        INSERT INTO referral_events (referrer_id, referred_id, payment_id, counted_at)
        VALUES ($1, $2, $3, now())
        ON CONFLICT (referred_id) DO NOTHING
        RETURNING referred_id
        """,
        referrer_id,
        buyer_telegram_id,
        payment_id,
    )
    # Если строка не вставилась — покупатель уже был засчитан ранее
    if event_row is None:
        return None

    # Убеждаемся, что у реферера есть строка прогресса
    await ensure_progress(referrer_id)

    # Атомарно увеличиваем счётчик и сразу читаем новое значение
    progress_row = await db.fetchrow(
        """
        UPDATE referral_progress
        SET confirmed_count = confirmed_count + 1,
            updated_at      = now()
        WHERE telegram_id = $1
        RETURNING confirmed_count
        """,
        referrer_id,
    )
    confirmed_count: int = progress_row["confirmed_count"]

    # Считываем пороговые настройки
    threshold: int = await settings.get_int("referral_threshold", 2)
    bonus: int = await settings.get_int("referral_bonus_days", 30)

    if confirmed_count >= threshold:
        # Выдаём подарок: продлеваем подписку реферера
        sub_row = await subscriptions.extend(referrer_id, bonus)

        # Сбрасываем счётчик и увеличиваем gifts_received
        await db.execute(
            """
            UPDATE referral_progress
            SET confirmed_count = 0,
                gifts_received  = gifts_received + 1,
                updated_at      = now()
            WHERE telegram_id = $1
            """,
            referrer_id,
        )

        return {
            "referrer_id": referrer_id,
            "new_expires_at": sub_row["expires_at"],
        }

    # Прогресс увеличен, порог не достигнут — подарка нет
    return None


async def get_progress(telegram_id: int) -> dict:
    """
    Вернуть данные для экрана реферальной программы (§9).

    Структура ответа:
    {
        'confirmed_count': int,   # текущий цикл
        'threshold':       int,   # нужно рефералов до подарка
        'bonus':           int,   # бонус в днях
        'gifts_received':  int,   # всего подарков получено
    }
    """
    threshold: int = await settings.get_int("referral_threshold", 2)
    bonus: int = await settings.get_int("referral_bonus_days", 30)

    row = await db.fetchrow(
        "SELECT confirmed_count, gifts_received FROM referral_progress WHERE telegram_id = $1",
        telegram_id,
    )

    confirmed_count: int = row["confirmed_count"] if row else 0
    gifts_received: int = row["gifts_received"] if row else 0

    return {
        "confirmed_count": confirmed_count,
        "threshold": threshold,
        "bonus": bonus,
        "gifts_received": gifts_received,
    }
