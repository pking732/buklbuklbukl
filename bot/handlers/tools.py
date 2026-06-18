"""
Админская утилита: переслать боту сообщение -> получить Telegram ID отправителя.
Только для платёжного администратора. Работает в дефолтном состоянии (не мешает FSM).
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import (
    Message,
    MessageOriginUser,
    MessageOriginHiddenUser,
    MessageOriginChannel,
    MessageOriginChat,
)

from bot.services import settings

router = Router()


async def _is_admin(telegram_id: int) -> bool:
    admin_id = await settings.get_int("payment_admin_id", 0)
    return admin_id != 0 and telegram_id == admin_id


@router.message(StateFilter(None), F.forward_origin)
async def whois_forward(message: Message) -> None:
    """Пересланное сообщение -> ID источника (только админ)."""
    if not await _is_admin(message.from_user.id):  # type: ignore[union-attr]
        return  # обычным пользователям не отвечаем

    origin = message.forward_origin

    if isinstance(origin, MessageOriginUser):
        u = origin.sender_user
        uname = f"@{u.username}" if u.username else "—"
        await message.answer(
            f"👤 <b>Пользователь</b>\n"
            f"ID: <code>{u.id}</code>\n"
            f"Имя: {u.full_name}\n"
            f"Username: {uname}"
        )
    elif isinstance(origin, MessageOriginHiddenUser):
        await message.answer(
            "🙈 Пользователь скрыл аккаунт в настройках приватности — "
            f"ID недоступен.\nИмя в пересылке: {origin.sender_user_name}"
        )
    elif isinstance(origin, MessageOriginChannel):
        ch = origin.chat
        await message.answer(
            f"📢 <b>Канал</b>\nID: <code>{ch.id}</code>\nНазвание: {ch.title}"
        )
    elif isinstance(origin, MessageOriginChat):
        ch = origin.sender_chat
        await message.answer(
            f"👥 <b>Чат</b>\nID: <code>{ch.id}</code>\nНазвание: {ch.title}"
        )
    else:
        await message.answer("Не удалось определить источник пересылки.")
