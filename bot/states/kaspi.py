"""
FSM-состояния для Kaspi-оплаты.
"""

from aiogram.fsm.state import State, StatesGroup


class KaspiPaymentStates(StatesGroup):
    waiting_for_receipt = State()  # Ждём фото чека
