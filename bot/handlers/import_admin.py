"""
Админский импорт существующих клиентов из Excel.

Поток:
  /import  -> (только платёжный админ) бот просит прислать .xlsx
  <документ> в состоянии ImportFlow.waiting_file -> парсинг + выдача доступа + сводка
"""
from __future__ import annotations

import io
import logging

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import bot.texts as texts
from bot import keyboards
from bot.states import ImportFlow
from bot.services import settings, import_clients

logger = logging.getLogger(__name__)
router = Router()


async def _is_admin(telegram_id: int) -> bool:
    admin_id = await settings.get_int("payment_admin_id", 0)
    return admin_id != 0 and telegram_id == admin_id


@router.message(Command("import"), StateFilter(None))
async def cmd_import(message: Message, state: FSMContext) -> None:
    """Старт импорта — только для платёжного администратора."""
    if not await _is_admin(message.from_user.id):  # type: ignore[union-attr]
        await message.answer(texts.IMPORT_NOT_ADMIN)
        return
    await state.set_state(ImportFlow.waiting_file)
    await message.answer(texts.IMPORT_ASK_FILE, reply_markup=keyboards.cancel())


@router.message(ImportFlow.waiting_file, F.text == texts.BTN_CANCEL)
async def import_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.IMPORT_CANCELLED, reply_markup=keyboards.main_menu())


@router.message(ImportFlow.waiting_file, F.document)
async def import_file(message: Message, state: FSMContext) -> None:
    """Приём .xlsx, парсинг и импорт."""
    doc = message.document
    name = (doc.file_name or "").lower()
    if not name.endswith(".xlsx"):
        await message.answer(texts.IMPORT_NOT_XLSX)
        return

    # Скачиваем файл в память
    buf = io.BytesIO()
    await message.bot.download(doc, destination=buf)
    content = buf.getvalue()

    await message.answer("⏳ Обрабатываю файл, это может занять время...")

    try:
        rows = import_clients.parse_xlsx(content)
    except Exception as e:  # noqa: BLE001
        logger.exception("import: ошибка парсинга")
        await message.answer(f"⚠️ Не удалось прочитать файл: {e}",
                             reply_markup=keyboards.main_menu())
        await state.clear()
        return

    summary = await import_clients.import_rows(rows)
    await state.clear()

    text = texts.IMPORT_DONE.format(**summary)
    # Покажем первые несколько ошибок, если были
    if summary["errors"]:
        sample = "\n".join(summary["errors"][:10])
        text += f"\n\n<b>Ошибки (первые 10):</b>\n<code>{sample}</code>"
    await message.answer(text, reply_markup=keyboards.main_menu())


@router.message(ImportFlow.waiting_file)
async def import_wrong_input(message: Message) -> None:
    """В состоянии ожидания файла прислали не документ."""
    await message.answer(texts.IMPORT_NOT_XLSX)
