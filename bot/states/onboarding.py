"""
FSM-состояния для онбординга (геолокация/поиск города + язык).
"""

from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    waiting_location = State()       # Ожидаем геолокацию или текстовый ввод
    confirming_city = State()        # Подтверждение найденного города
    selecting_from_search = State()  # Выбор из результатов поиска
    selecting_language = State()     # Выбор языка
