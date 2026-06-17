# bot/states.py — FSM состояния для aiogram 3
# Контракт имён: docs/04-data-contract.md §4

from aiogram.fsm.state import State, StatesGroup


class BuyFlow(StatesGroup):
    """Сценарий покупки / продления подписки (§5 docs/02-business-logic.md)."""

    # Пользователь видит список тарифов и выбирает один
    choosing_tariff = State()

    # Пользователь видит экран оплаты (сумма + реквизиты) и ждёт кнопки «Я оплатил»
    payment_screen = State()

    # Пользователь вводит ФИО отправителя платежа в свободном тексте
    entering_sender_name = State()
