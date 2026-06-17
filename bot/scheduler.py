# bot/scheduler.py — фоновые джобы на APScheduler
# Запускается из main.py: scheduler = setup_scheduler(bot); scheduler.start()

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot.services import settings
from bot.services import subscriptions
from bot.services import traffic
import bot.texts as texts

logger = logging.getLogger(__name__)


async def reminder_job(bot: Bot) -> None:
    """
    Джоб напоминаний об истечении подписки (§8 docs/02-business-logic.md).

    Каждые 12 часов:
    - Читает из settings ключ expiry_reminder_hours (дефолт 24).
    - Запрашивает список подписок, истекающих в течение этого срока.
    - Отправляет каждому пользователю сообщение-напоминание.
    - При успешной отправке выставляет notified_expiring=True.
    - Ошибка по конкретному пользователю не прерывает обход.
    """
    hours = await settings.get_int("expiry_reminder_hours", 24)
    rows = await subscriptions.list_expiring(within_hours=hours)

    if not rows:
        logger.debug("reminder_job: нет подписок, истекающих в течение %d ч.", hours)
        return

    logger.info("reminder_job: найдено %d подписок для напоминания (окно %d ч.)", len(rows), hours)

    for row in rows:
        telegram_id: int = row["telegram_id"]
        expires_at = row["expires_at"]

        # Форматируем дату в удобный вид (дд.мм.гггг)
        expires_str = expires_at.strftime("%d.%m.%Y")

        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=texts.EXPIRY_REMINDER.format(expires=expires_str),
            )
            # Помечаем, что уведомление уже отправлено
            await subscriptions.set_notified(telegram_id, True)
            logger.debug("reminder_job: уведомление отправлено telegram_id=%d", telegram_id)
        except Exception as exc:
            # Логируем ошибку и продолжаем обход остальных пользователей
            logger.warning(
                "reminder_job: не удалось уведомить telegram_id=%d: %s",
                telegram_id,
                exc,
            )


async def traffic_job() -> None:
    """
    Джоб сбора трафика (§10 docs/02-business-logic.md).

    Каждый час вызывает traffic.collect_once() и логирует количество
    обработанных записей.
    """
    try:
        n = await traffic.collect_once()
        logger.info("traffic_job: обработано записей трафика: %d", n)
    except Exception as exc:
        logger.error("traffic_job: ошибка при сборе трафика: %s", exc)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """
    Создаёт и настраивает AsyncIOScheduler с двумя джобами.

    Джобы:
    - reminder_job — каждые 12 часов, передаёт bot как аргумент.
    - traffic_job  — каждый 1 час.

    Scheduler НЕ запускается здесь; вызов .start() — в main.py.

    :param bot: экземпляр aiogram Bot, передаётся в reminder_job.
    :return: настроенный AsyncIOScheduler.
    """
    scheduler = AsyncIOScheduler()

    # Напоминания об истечении подписки — раз в 12 часов
    scheduler.add_job(
        reminder_job,
        trigger=IntervalTrigger(hours=12),
        args=[bot],
        id="reminder_job",
        coalesce=True,
        max_instances=1,
    )

    # Сбор трафика — раз в 1 час
    scheduler.add_job(
        traffic_job,
        trigger=IntervalTrigger(hours=1),
        id="traffic_job",
        coalesce=True,
        max_instances=1,
    )

    logger.info(
        "setup_scheduler: зарегистрировано джобов: reminder_job (12 ч.), traffic_job (1 ч.)"
    )
    return scheduler
