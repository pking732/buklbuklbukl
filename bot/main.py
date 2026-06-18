"""
Точка входа бота: long-polling Telegram + aiohttp-вебхук приёма экспирации + APScheduler.
Запуск на сервере: `python -m bot.main` (из /opt/buklbot).
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import bot.config as config
from bot import db, scheduler, webhook_server
from bot.handlers import admin, import_admin, menu, payment, start, tools

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Обязательные env уже проверяются в config при импорте (config.validate()).
    await db.init_pool()
    logger.info("DB pool initialized")

    bot = Bot(
        config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())
    # Порядок важен: непересекающиеся триггеры, но FSM payment раньше меню.
    dp.include_router(start.router)
    dp.include_router(tools.router)
    dp.include_router(import_admin.router)
    dp.include_router(payment.router)
    dp.include_router(menu.router)
    dp.include_router(admin.router)

    # aiohttp-вебхук для колбэка экспирации от VPS-агента (127.0.0.1).
    runner = await webhook_server.start_webhook(bot)

    # Фоновые джобы: напоминания + сбор трафика.
    sched = scheduler.setup_scheduler(bot)
    sched.start()
    logger.info("Scheduler started")

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    finally:
        logger.info("Shutting down...")
        sched.shutdown(wait=False)
        await runner.cleanup()
        await bot.session.close()
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
