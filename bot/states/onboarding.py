"""
FSM-состояния для онбординга (поиск города + язык).
"""

from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    searching_city = State()        # Ввод названия города
    selecting_from_search = State()  # Выбор из результатов поиска
    selecting_language = State()     # Выбор языка
