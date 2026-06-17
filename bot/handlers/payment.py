# bot/handlers/payment.py — FSM сценарий покупки / продления подписки
# Владеет: BuyFlow (choosing_tariff → payment_screen → entering_sender_name)
# Старт: кнопка BTN_BUY из дефолтного состояния (None).
# Бизнес-логика: docs/02-business-logic.md §5.

from decimal import Decimal

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import Message

import bot.texts as texts
import bot.keyboards as keyboards
from bot.states import BuyFlow
from bot.services import tariffs, settings, subscriptions, payments, users

router = Router()


# ---------------------------------------------------------------------------
# Вспомогательная функция отмены (переиспользуется в нескольких местах)
# ---------------------------------------------------------------------------

async def _cancel(message: Message, state: FSMContext) -> None:
    """Сбросить FSM и вернуть пользователя в главное меню."""
    await state.clear()
    await message.answer(texts.CANCELLED, reply_markup=keyboards.main_menu())


# ---------------------------------------------------------------------------
# Шаг 1: Старт сценария — нажатие BTN_BUY из дефолтного состояния
# ---------------------------------------------------------------------------

@router.message(StateFilter(None), F.text == texts.BTN_BUY)
async def handle_buy_start(message: Message, state: FSMContext) -> None:
    """
    Обработчик кнопки «Купить / Продлить» из главного меню.
    Загружает активные тарифы и предлагает выбрать один.
    """
    active = await tariffs.list_active()

    if not active:
        # Тарифы не настроены — информируем пользователя, остаёмся в главном меню
        await message.answer(
            "😕 К сожалению, сейчас нет доступных тарифов. Попробуйте позже.",
            reply_markup=keyboards.main_menu(),
        )
        return

    # Переходим к выбору тарифа
    await state.set_state(BuyFlow.choosing_tariff)
    await message.answer(
        texts.CHOOSE_TARIFF,
        reply_markup=keyboards.tariffs([t["title"] for t in active]),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Шаг 2: Выбор тарифа
# ---------------------------------------------------------------------------

@router.message(StateFilter(BuyFlow.choosing_tariff), F.text == texts.BTN_CANCEL)
async def handle_tariff_cancel(message: Message, state: FSMContext) -> None:
    """Отмена на экране выбора тарифа."""
    await _cancel(message, state)


@router.message(StateFilter(BuyFlow.choosing_tariff))
async def handle_tariff_chosen(message: Message, state: FSMContext) -> None:
    """
    Пользователь нажал кнопку с названием тарифа.
    Проверяем существование тарифа, сохраняем данные и показываем экран оплаты.
    """
    tariff = await tariffs.get_by_title(message.text or "")

    if tariff is None:
        # Ввод произвольного текста вместо кнопки — просим выбрать кнопкой
        active = await tariffs.list_active()
        await message.answer(
            "Пожалуйста, выберите тариф, нажав одну из кнопок ниже.",
            reply_markup=keyboards.tariffs([t["title"] for t in active]),
        )
        return

    # Сохраняем данные выбранного тарифа в FSM
    price_rub = tariff["price_rub"]
    await state.update_data(
        tariff_code=tariff["code"],
        amount=str(price_rub),          # сохраняем как строку (Decimal → str)
        duration_days=tariff["duration_days"],
        max_devices=tariff["max_devices"],
        title=tariff["title"],
    )

    # Загружаем реквизиты из настроек
    requisites = await settings.get("payment_requisites") or "Уточните реквизиты у поддержки."

    # Форматируем сумму: если целое — без дробной части
    amount_display = int(price_rub) if isinstance(price_rub, (Decimal, float)) and price_rub == int(price_rub) else price_rub

    await state.set_state(BuyFlow.payment_screen)
    await message.answer(
        texts.PAYMENT_SCREEN.format(amount=amount_display, requisites=requisites),
        reply_markup=keyboards.payment(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Шаг 3: Экран оплаты
# ---------------------------------------------------------------------------

@router.message(StateFilter(BuyFlow.payment_screen), F.text == texts.BTN_CANCEL)
async def handle_payment_cancel(message: Message, state: FSMContext) -> None:
    """Отмена на экране оплаты."""
    await _cancel(message, state)


@router.message(StateFilter(BuyFlow.payment_screen), F.text == texts.BTN_PAID)
async def handle_paid_pressed(message: Message, state: FSMContext) -> None:
    """
    Пользователь нажал «Я оплатил» — запрашиваем ФИО отправителя.
    """
    await state.set_state(BuyFlow.entering_sender_name)
    await message.answer(
        texts.ASK_SENDER_NAME,
        reply_markup=keyboards.cancel(),
        parse_mode="HTML",
    )


@router.message(StateFilter(BuyFlow.payment_screen))
async def handle_payment_unknown(message: Message, state: FSMContext) -> None:
    """Любой другой ввод на экране оплаты — подсказываем нажать кнопку."""
    await message.answer(
        "Пожалуйста, воспользуйтесь кнопками: нажмите «✅ Я оплатил» после перевода "
        "или «❌ Отменить» для возврата в меню.",
    )


# ---------------------------------------------------------------------------
# Шаг 4: Ввод ФИО отправителя — завершение сценария
# ---------------------------------------------------------------------------

@router.message(StateFilter(BuyFlow.entering_sender_name), F.text == texts.BTN_CANCEL)
async def handle_sender_name_cancel(message: Message, state: FSMContext) -> None:
    """Отмена на этапе ввода ФИО."""
    await _cancel(message, state)


@router.message(StateFilter(BuyFlow.entering_sender_name))
async def handle_sender_name(message: Message, state: FSMContext) -> None:
    """
    Пользователь ввёл ФИО отправителя.

    Алгоритм:
    1. Определяем kind: extension (есть активная подписка) или purchase.
    2. Создаём платёж через payments.create_and_apply — он же выдаёт/продлевает ключ.
    3. Отправляем пользователю статусное сообщение по outcome.
    4. Уведомляем платёжного администратора с inline-кнопками.
    5. Сбрасываем FSM.
    """
    sender_name: str = message.text or ""
    tg: int = message.from_user.id  # type: ignore[union-attr]

    data = await state.get_data()

    # --- Определяем тип операции ---
    kind = "extension" if await subscriptions.is_active(tg) else "purchase"

    # --- Парсим amount: asyncpg отдаёт Decimal ---
    raw_amount = data["amount"]  # уже str, но передаём as-is в сервис
    try:
        amount_value: Decimal = Decimal(raw_amount)
    except Exception:
        amount_value = Decimal(0)

    # --- Создаём заявку и применяем (выдача / продление ключа внутри сервиса) ---
    res = await payments.create_and_apply(
        telegram_id=tg,
        tariff_code=data["tariff_code"],
        amount_rub=amount_value,
        duration_days=data["duration_days"],
        max_devices=data["max_devices"],
        kind=kind,
        sender_name=sender_name,
    )

    outcome: str = res["outcome"]
    payment_id: int = res["payment_id"]

    # --- Формируем ответное сообщение пользователю по outcome ---
    if outcome == "active":
        # Покупка, оптимистично выдан ключ (добросовестный пользователь)
        user_text = texts.PAID_TRUSTED_OK
    elif outcome == "extended":
        # Продление — всегда оптимистично, показываем новую дату
        sub = await subscriptions.get(tg)
        expires_str = sub["expires_at"].strftime("%d.%m.%Y") if sub and sub.get("expires_at") else "—"
        user_text = texts.EXTENDED_OK.format(expires=expires_str)
    else:
        # outcome == "waiting" — недобросовестный пользователь, ожидание проверки
        user_text = texts.PAID_UNTRUSTED_WAIT

    await message.answer(user_text, reply_markup=keyboards.main_menu(), parse_mode="HTML")

    # --- Уведомление платёжного администратора ---
    admin_id: int = await settings.get_int("payment_admin_id", 0)
    if admin_id > 0:
        uname = await users.get_username(tg) or str(tg)

        # Форматируем сумму для отображения
        try:
            amount_decimal = Decimal(raw_amount)
            amount_display = str(int(amount_decimal)) if amount_decimal == amount_decimal.to_integral_value() else str(amount_decimal)
        except Exception:
            amount_display = raw_amount

        admin_text = texts.ADMIN_NEW_PAYMENT.format(
            username=uname,
            tariff=data["title"],
            amount=amount_display,
            sender_name=sender_name,
            kind=kind,
        )
        await message.bot.send_message(  # type: ignore[union-attr]
            admin_id,
            admin_text,
            reply_markup=keyboards.admin_payment(payment_id),
            parse_mode="HTML",
        )

    # --- Завершаем FSM ---
    await state.clear()
