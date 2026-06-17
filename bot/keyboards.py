# bot/keyboards.py — все клавиатуры бота (reply и inline)
# Тексты кнопок берутся исключительно из bot.texts (BTN_*).
# Динамические данные (тарифы) передаются аргументами — в БД не ходим.

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

import bot.texts as texts


def main_menu() -> ReplyKeyboardMarkup:
    """
    Главное меню — показывается после /start и после отмены любого действия.

    Раскладка:
        ряд 1: BTN_BUY
        ряд 2: BTN_MY_KEYS | BTN_EARN
        ряд 3: BTN_SUPPORT
    """
    builder = ReplyKeyboardBuilder()

    # Ряд 1 — покупка (одна широкая кнопка)
    builder.row(KeyboardButton(text=texts.BTN_BUY))

    # Ряд 2 — мои ключи и заработок рядом
    builder.row(
        KeyboardButton(text=texts.BTN_MY_KEYS),
        KeyboardButton(text=texts.BTN_EARN),
    )

    # Ряд 3 — поддержка
    builder.row(KeyboardButton(text=texts.BTN_SUPPORT))

    return builder.as_markup(resize_keyboard=True)


def cancel() -> ReplyKeyboardMarkup:
    """
    Клавиатура с единственной кнопкой «Отменить».
    Используется там, где пользователю нужен только выход без доп. действий.
    """
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=texts.BTN_CANCEL))
    return builder.as_markup(resize_keyboard=True)


def tariffs(tariff_titles: list[str]) -> ReplyKeyboardMarkup:
    """
    Список тарифов в виде reply-кнопок + кнопка «Отменить» последним рядом.

    Функция чистая: список подписей передаёт вызывающий хендлер
    (загрузка из services.tariffs — его ответственность).
    Каждый тариф — отдельный ряд (один тариф = одна широкая кнопка).

    Args:
        tariff_titles: список строк-подписей тарифов в порядке отображения.
    """
    builder = ReplyKeyboardBuilder()

    for title in tariff_titles:
        builder.row(KeyboardButton(text=title))

    # Кнопка отмены — всегда последним рядом
    builder.row(KeyboardButton(text=texts.BTN_CANCEL))

    return builder.as_markup(resize_keyboard=True)


def payment() -> ReplyKeyboardMarkup:
    """
    Экран оплаты: пользователь видит реквизиты и может подтвердить или отменить.

    Раскладка:
        ряд 1: BTN_PAID
        ряд 2: BTN_CANCEL
    """
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=texts.BTN_PAID))
    builder.row(KeyboardButton(text=texts.BTN_CANCEL))
    return builder.as_markup(resize_keyboard=True)


def referral_inline() -> InlineKeyboardMarkup:
    """
    Inline-клавиатура для экрана «Хочу заработать»:
    одна кнопка «Условия реферальной программы».

    callback_data: ref:terms
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_REF_TERMS,
        callback_data="ref:terms",
    )
    return builder.as_markup()


def admin_payment(payment_id: int) -> InlineKeyboardMarkup:
    """
    Inline-клавиатура уведомления администратора о новой заявке на оплату.
    Две кнопки в одном ряду: подтвердить и отклонить платёж.

    callback_data:
        подтвердить: pay:approve:{payment_id}
        отклонить:  pay:reject:{payment_id}

    Args:
        payment_id: первичный ключ записи в таблице payments.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Подтвердить",
            callback_data=f"pay:approve:{payment_id}",
        ),
        InlineKeyboardButton(
            text="❌ Отклонить",
            callback_data=f"pay:reject:{payment_id}",
        ),
    )
    return builder.as_markup()
