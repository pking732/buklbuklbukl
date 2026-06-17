"""
webhook_server.py — aiohttp-сервер для приёма колбэка экспирации от VPS-агента.

Агент делает: POST <EXPIRE_CALLBACK_URL> {deviceKeyId: "..."} + Authorization: Bearer <VPS_AGENT_TOKEN>
Сервер слушает config.WEBHOOK_HOST:config.WEBHOOK_PORT, путь /agent/expire.
"""

import logging

from aiohttp import web
from aiogram import Bot

import bot.config as config
from bot.services import vps_agent
from bot.services import subscriptions
import bot.texts as texts

logger = logging.getLogger(__name__)


async def handle_expire(request: web.Request) -> web.Response:
    """
    Обрабатывает POST /agent/expire от VPS-агента.

    Ожидает:
      - Заголовок Authorization: Bearer <VPS_AGENT_TOKEN>
      - Тело JSON: {"deviceKeyId": "..."}

    Действия:
      1. Проверка токена авторизации.
      2. Извлечение deviceKeyId из тела запроса.
      3. Получение telegram_id по deviceKeyId.
      4. Обновление статуса подписки на 'expired'.
      5. Уведомление пользователя в Telegram.
    """
    # Проверяем заголовок Authorization
    auth_header = request.headers.get("Authorization", "")
    expected_token = f"Bearer {config.VPS_AGENT_TOKEN}"
    if auth_header != expected_token:
        logger.warning("Неверный токен авторизации от %s", request.remote)
        return web.json_response({"error": "unauthorized"}, status=401)

    # Читаем JSON-тело запроса
    try:
        data = await request.json()
    except Exception:
        logger.warning("Не удалось разобрать JSON тело запроса от %s", request.remote)
        return web.json_response({"error": "invalid json"}, status=400)

    device_key_id: str | None = data.get("deviceKeyId")
    if not device_key_id:
        logger.warning("Отсутствует поле deviceKeyId в запросе от %s", request.remote)
        return web.json_response({"error": "missing deviceKeyId"}, status=400)

    try:
        # Получаем telegram_id по device_key_id
        telegram_id: int = vps_agent.telegram_id_from_key(device_key_id)

        # Помечаем подписку как истёкшую (единственная точка смены статуса)
        await subscriptions.mark_expired(telegram_id)

        # Уведомляем пользователя; игнорируем ошибку если бот заблокирован
        bot: Bot = request.app["bot"]
        try:
            await bot.send_message(telegram_id, texts.SUB_EXPIRED)
        except Exception as send_err:
            # Пользователь мог заблокировать бота — логируем, но не падаем
            logger.warning(
                "Не удалось отправить уведомление пользователю %s: %s",
                telegram_id,
                send_err,
            )

        logger.info("Подписка пользователя %s успешно помечена как истёкшая", telegram_id)
        return web.json_response({"ok": True})

    except Exception as err:
        # Любая внутренняя ошибка — логируем и возвращаем 500, сервер не роняем
        logger.exception("Ошибка обработки колбэка экспирации для %s: %s", device_key_id, err)
        return web.json_response({"error": "internal server error"}, status=500)


def build_app(bot: Bot) -> web.Application:
    """
    Создаёт aiohttp-приложение, регистрирует маршруты и кладёт Bot в app-контекст.

    Args:
        bot: Экземпляр aiogram Bot, используется для отправки уведомлений пользователям.

    Returns:
        Настроенный экземпляр web.Application.
    """
    app = web.Application()

    # Сохраняем бот в контексте приложения — доступен из обработчиков через request.app["bot"]
    app["bot"] = bot

    # Регистрируем единственный маршрут для колбэка экспирации
    app.router.add_post("/agent/expire", handle_expire)

    return app


async def start_webhook(bot: Bot) -> web.AppRunner:
    """
    Запускает aiohttp-сервер на config.WEBHOOK_HOST:config.WEBHOOK_PORT.

    Создаёт приложение через build_app, поднимает AppRunner + TCPSite.
    Возвращает runner, чтобы main.py мог вызвать await runner.cleanup() при завершении.

    Args:
        bot: Экземпляр aiogram Bot для передачи в приложение.

    Returns:
        Запущенный web.AppRunner — сохрани и вызови runner.cleanup() при остановке.
    """
    app = build_app(bot)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, config.WEBHOOK_HOST, config.WEBHOOK_PORT)
    await site.start()

    logger.info(
        "Webhook-сервер запущен на http://%s:%s/agent/expire",
        config.WEBHOOK_HOST,
        config.WEBHOOK_PORT,
    )

    return runner
