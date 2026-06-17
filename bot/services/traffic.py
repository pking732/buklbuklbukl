"""
Сервис учёта трафика VPN-пользователей.

Владеет таблицами: user_traffic, traffic_usage.
Запускается APScheduler-джобом через collect_once().
"""

import logging
from datetime import datetime, timezone

from bot import db
from bot.services import vps_agent, subscriptions

logger = logging.getLogger(__name__)


async def collect_once(write_periods: bool = True) -> int:
    """
    Сбор трафика по всем активным подпискам (§10 бизнес-логики).

    Для каждой активной подписки запрашивает накопленный трафик у VPS-агента
    (с reset=True, т.е. счётчик на агенте обнуляется после чтения),
    затем инкрементирует агрегаты в user_traffic и опционально пишет
    детальную запись в traffic_usage.

    Ошибка по одному пользователю не прерывает обход — логируется и пропускается.

    :param write_periods: если True — писать строку в traffic_usage за каждый сбор.
    :return: количество подписок, по которым был ненулевой трафик.
    """
    active = await subscriptions.list_active()
    processed = 0

    for sub in active:
        telegram_id: int = sub["telegram_id"]
        key_id: str = sub["device_key_id"]

        try:
            # Запрашиваем трафик; агент сбрасывает счётчик на своей стороне
            t = await vps_agent.get_traffic(key_id, reset=True)
            up: int = t.get("uplink", 0)
            down: int = t.get("downlink", 0)

            # Пропускаем нулевые сборы — нет смысла писать пустые строки
            if up + down == 0:
                continue

            now = datetime.now(timezone.utc)

            # UPSERT в user_traffic: суммируем все счётчики.
            # ON CONFLICT (telegram_id) — атомарное приращение без race-condition
            # при одиночном джобе (если в будущем джоб станет параллельным,
            # достаточно этого же SQL — Postgres гарантирует атомарность UPDATE).
            await db.execute(
                """
                INSERT INTO user_traffic
                    (telegram_id, total_uplink_bytes, total_downlink_bytes,
                     total_bytes, period_bytes, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    total_uplink_bytes   = user_traffic.total_uplink_bytes   + EXCLUDED.total_uplink_bytes,
                    total_downlink_bytes = user_traffic.total_downlink_bytes + EXCLUDED.total_downlink_bytes,
                    total_bytes          = user_traffic.total_bytes          + EXCLUDED.total_bytes,
                    period_bytes         = user_traffic.period_bytes         + EXCLUDED.period_bytes,
                    updated_at           = EXCLUDED.updated_at
                """,
                telegram_id,
                up,
                down,
                up + down,
                up + down,
                now,
            )

            if write_periods:
                # period_start и period_end — оба равны моменту сбора.
                # Логика: каждый вызов collect_once — это «точка» во времени,
                # а не интервал с известным началом (начало неизвестно, потому что
                # агент сбрасывает счётчик, но не сообщает, с какого момента он
                # его копил). Если в будущем агент начнёт возвращать window_start,
                # period_start нужно будет заменить на это значение.
                await db.execute(
                    """
                    INSERT INTO traffic_usage
                        (telegram_id, device_key_id, period_start, period_end,
                         uplink_bytes, downlink_bytes, total_bytes, collected_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    telegram_id,
                    key_id,
                    now,   # period_start = момент сбора
                    now,   # period_end   = момент сбора (точечная запись)
                    up,
                    down,
                    up + down,
                    now,
                )

            processed += 1
            logger.debug(
                "Трафик собран: telegram_id=%d, up=%d, down=%d",
                telegram_id, up, down,
            )

        except Exception:
            logger.exception(
                "Ошибка при сборе трафика для telegram_id=%d (device_key_id=%s)",
                telegram_id, key_id,
            )
            # Продолжаем — один сбойный юзер не должен ломать весь джоб

    logger.info("collect_once завершён: обработано %d ненулевых подписок из %d", processed, len(active))
    return processed


async def get_user_total(telegram_id: int) -> dict:
    """
    Возвращает агрегированную статистику трафика для пользователя.

    :param telegram_id: идентификатор пользователя Telegram.
    :return: словарь с ключами total_uplink_bytes, total_downlink_bytes,
             total_bytes, period_bytes. Все значения — int (нули, если строки нет).
    """
    row = await db.fetchrow(
        """
        SELECT total_uplink_bytes, total_downlink_bytes, total_bytes, period_bytes
        FROM user_traffic
        WHERE telegram_id = $1
        """,
        telegram_id,
    )

    if row is None:
        return {
            "total_uplink_bytes": 0,
            "total_downlink_bytes": 0,
            "total_bytes": 0,
            "period_bytes": 0,
        }

    return {
        "total_uplink_bytes": row["total_uplink_bytes"],
        "total_downlink_bytes": row["total_downlink_bytes"],
        "total_bytes": row["total_bytes"],
        "period_bytes": row["period_bytes"],
    }


async def reset_period(telegram_id: int | None = None) -> None:
    """
    Обнуляет счётчик period_bytes.

    Используется, например, при смене расчётного периода или вручную
    (например, при продлении подписки, если нужно начать отсчёт заново).

    :param telegram_id: если передан — сбрасывает только этого пользователя;
                        если None — сбрасывает period_bytes для ВСЕХ пользователей.
    """
    now = datetime.now(timezone.utc)

    if telegram_id is not None:
        await db.execute(
            """
            UPDATE user_traffic
            SET period_bytes = 0, updated_at = $2
            WHERE telegram_id = $1
            """,
            telegram_id,
            now,
        )
        logger.info("period_bytes обнулён для telegram_id=%d", telegram_id)
    else:
        await db.execute(
            """
            UPDATE user_traffic
            SET period_bytes = 0, updated_at = $1
            """,
            now,
        )
        logger.info("period_bytes обнулён для всех пользователей")
