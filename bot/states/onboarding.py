"""
FSM-состояния для онбординга (язык → поиск города).
"""

from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    selecting_language = State()     # Выбор языка
    searching_city = State()         # Ввод названия города
    selecting_from_search = State()  # Выбор из результатов поиска
