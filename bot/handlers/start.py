"""
bot/handlers/start.py — хендлер команды /start.

Регистрирует пользователя (или обновляет last_start_at),
инициализирует строки подписки и реферального прогресса,
привязывает реферера для новых пользователей и отправляет
приветственное сообщение.
"""

from aiogram import Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message

import bot.texts as texts
import bot.keyboards as keyboards
from bot.services import users, subscriptions, referrals

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    """
    Обработчик команды /start [deep-link].

    Deep-link (если передан) интерпретируется как telegram_id реферера —
    строка из цифр. Невалидный аргумент и само-реферирование игнорируются.
    """
    tg: int = message.from_user.id
    username: str | None = message.from_user.username
    first_name: str = message.from_user.first_name or ""

    # 1. Регистрация / обновление last_start_at
    is_new: bool = await users.register_or_touch(tg, username, first_name)

    # 2. Гарантируем наличие строк подписки и реферального прогресса
    await subscriptions.ensure_row(tg)
    await referrals.ensure_progress(tg)

    if is_new:
        # 3. Парсим реферера из deep-link аргумента
        referrer: int | None = None
        if command.args and command.args.isdigit():
            candidate = int(command.args)
            # Само-реферирование запрещено
            if candidate != tg:
                referrer = candidate

        # 4. Привязываем реферера (только для новых пользователей, 1 раз)
        await referrals.link_on_start(tg, referrer)

        # 5. Приветствие нового пользователя
        await message.answer(
            text=texts.WELCOME_NEW,
            reply_markup=keyboards.main_menu(),
            parse_mode="HTML",
        )
    else:
        # 6. Приветствие повторного пользователя
        await message.answer(
            text=texts.WELCOME_BACK,
            reply_markup=keyboards.main_menu(),
            parse_mode="HTML",
        )
