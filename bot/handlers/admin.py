"""
bot/handlers/admin.py — обработка решений платёжного администратора.

Обрабатывает inline-callback'и:
    pay:approve:<payment_id>  — подтвердить платёж
    pay:reject:<payment_id>   — отклонить платёж

Контракт callback_data зафиксирован в docs/03-modules-and-conflicts.md §3 и CLAUDE.md.
"""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery

import bot.texts as texts
from bot.services import settings
from bot.services import payments

logger = logging.getLogger(__name__)

router = Router()


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

async def _is_admin(callback: CallbackQuery) -> bool:
    """
    Проверяет, что пользователь — платёжный администратор.
    Если payment_admin_id == 0 — проверка пропускается (режим разработки).
    """
    admin_id: int = await settings.get_int("payment_admin_id", 0)
    if admin_id == 0:
        # Ограничение не выставлено — любой может (используется при отладке)
        return True
    return callback.from_user.id == admin_id


async def _safe_send(bot, chat_id: int, text: str) -> None:
    """
    Безопасная отправка сообщения: пользователь мог заблокировать бота.
    Ошибка пишется в лог, но не роняет хендлер.
    """
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as exc:
        logger.warning(
            "Не удалось отправить сообщение пользователю %d: %s",
            chat_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Хендлер: подтверждение платежа (pay:approve:<payment_id>)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("pay:approve:"))
async def handle_approve(callback: CallbackQuery) -> None:
    """Администратор нажал «Подтвердить» под заявкой на оплату."""

    # Проверка прав
    if not await _is_admin(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    payment_id: int = int(callback.data.split(":")[2])
    admin_id: int = callback.from_user.id

    # Вызов сервиса подтверждения платежа
    res: dict = await payments.approve(payment_id, admin_id)

    if not res["ok"]:
        # Заявка уже была обработана ранее (гонка двух нажатий)
        await callback.answer("Заявка уже обработана", show_alert=True)
        return

    buyer_id: int = res["buyer_telegram_id"]
    bot = callback.bot

    # Уведомить покупателя, только если он ждал подтверждения вручную
    if res.get("was_waiting"):
        await _safe_send(bot, buyer_id, texts.APPROVED_USER)

    # Реферальный бонус: уведомить реферера (если начислен)
    gift: dict | None = res.get("referral_gift")
    if gift:
        expires_str: str = gift["new_expires_at"].strftime("%d.%m.%Y")
        await _safe_send(
            bot,
            gift["referrer_id"],
            texts.REFERRAL_GIFT.format(expires=expires_str),
        )

    # Пометить сообщение администратора как обработанное
    try:
        original_text: str = (
            callback.message.text or callback.message.caption or ""
        )
        await callback.message.edit_text(
            original_text + "\n\n✅ <b>Подтверждено</b>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception as exc:
        logger.warning("Не удалось изменить сообщение администратора: %s", exc)
        # Попытка хотя бы убрать кнопки
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    await callback.answer("Подтверждено")


# ---------------------------------------------------------------------------
# Хендлер: отклонение платежа (pay:reject:<payment_id>)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("pay:reject:"))
async def handle_reject(callback: CallbackQuery) -> None:
    """Администратор нажал «Отклонить» под заявкой на оплату."""

    # Проверка прав
    if not await _is_admin(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    payment_id: int = int(callback.data.split(":")[2])
    admin_id: int = callback.from_user.id

    # Вызов сервиса отклонения платежа
    res: dict = await payments.reject(payment_id, admin_id)

    if not res["ok"]:
        # Заявка уже была обработана ранее
        await callback.answer("Заявка уже обработана", show_alert=True)
        return

    buyer_id: int = res["buyer_telegram_id"]
    bot = callback.bot

    # Текст уведомления зависит от типа платежа
    if res.get("kind") == "extension":
        user_text = texts.EXTENSION_REJECTED
    else:
        user_text = texts.REJECTED_USER

    await _safe_send(bot, buyer_id, user_text)

    # Пометить сообщение администратора как обработанное
    try:
        original_text: str = (
            callback.message.text or callback.message.caption or ""
        )
        await callback.message.edit_text(
            original_text + "\n\n❌ <b>Отклонено</b>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception as exc:
        logger.warning("Не удалось изменить сообщение администратора: %s", exc)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    await callback.answer("Отклонено")
