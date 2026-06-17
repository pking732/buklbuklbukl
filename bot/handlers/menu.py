# bot/handlers/menu.py — хендлеры главного меню (Поддержка, Мои ключи, Хочу заработать)
# Все message-хендлеры зарегистрированы ТОЛЬКО для дефолтного состояния (StateFilter(None)),
# чтобы не конфликтовать с FSM сценария покупки (payment.py).

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery

import bot.config as config
import bot.texts as texts
import bot.keyboards as keyboards
from bot.services import settings
from bot.services import subscriptions
from bot.services import referrals

router = Router()


@router.message(F.text == texts.BTN_SUPPORT, StateFilter(None))
async def handle_support(message: Message) -> None:
    """Хендлер кнопки «Поддержка» — показывает контакт менеджера из настроек."""
    username: str | None = await settings.get("support_username")
    await message.answer(
        texts.SUPPORT_MSG.format(username=username),
        parse_mode="HTML",
    )


@router.message(F.text == texts.BTN_MY_KEYS, StateFilter(None))
async def handle_my_keys(message: Message) -> None:
    """Хендлер кнопки «Мои ключи» — показывает активную подписку или сообщение об отсутствии."""
    tg: int = message.from_user.id
    sub = await subscriptions.get(tg)

    # Проверяем наличие активной подписки с URL ключа
    if sub and sub["status"] == "active" and sub["sub_url"]:
        expires_at = sub["expires_at"]

        # Форматируем дату окончания подписки; если None — ставим прочерк
        if expires_at is not None:
            try:
                expires: str = expires_at.strftime("%d.%m.%Y")
            except AttributeError:
                # expires_at уже строка или нестандартный тип — используем как есть
                expires = str(expires_at)
        else:
            expires = "—"

        await message.answer(
            texts.MY_KEYS_ACTIVE.format(sub_url=sub["sub_url"], expires=expires),
            parse_mode="HTML",
        )
    else:
        await message.answer(texts.MY_KEYS_NONE, parse_mode="HTML")


@router.message(F.text == texts.BTN_EARN, StateFilter(None))
async def handle_earn(message: Message) -> None:
    """Хендлер кнопки «Хочу заработать» — показывает реферальную программу."""
    tg: int = message.from_user.id

    # Получаем прогресс реферальной программы пользователя
    prog: dict = await referrals.get_progress(tg)

    # Формируем персональную реферальную ссылку
    link: str = f"https://t.me/{config.BOT_USERNAME}?start={tg}"

    await message.answer(
        texts.REFERRAL_SCREEN.format(
            link=link,
            progress=prog["confirmed_count"],
            threshold=prog["threshold"],
            bonus=prog["bonus"],
        ),
        reply_markup=keyboards.referral_inline(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "ref:terms")
async def handle_ref_terms(callback: CallbackQuery) -> None:
    """Callback-хендлер инлайн-кнопки «Условия реферальной программы»."""
    # Берём текст условий из настроек БД
    terms: str | None = await settings.get("referral_terms")
    await callback.message.answer(terms or "", parse_mode="HTML")
    await callback.answer()
