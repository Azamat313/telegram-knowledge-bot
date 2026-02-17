"""
Inline-клавиатуры для бота.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import SUBSCRIPTION_PLANS
from core.messages import get_msg


def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с тарифами подписки (Telegram Stars)."""
    buttons = []
    for plan_key, plan_info in SUBSCRIPTION_PLANS.items():
        price = plan_info["price"]
        label = plan_info.get("label", plan_key)
        buttons.append(
            [InlineKeyboardButton(text=f"⭐ {label} — {price} Stars", callback_data=f"subscribe:{plan_key}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_ask_ustaz_keyboard(query_log_id: int, lang: str = "kk") -> InlineKeyboardMarkup:
    """Кнопка 'Устазға сұрақ' под AI-ответом."""
    btn_text = get_msg("btn_ask_ustaz", lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=btn_text,
                    callback_data=f"ask_ustaz:{query_log_id}",
                ),
            ],
        ]
    )


def get_uncertain_keyboard(query_log_id: int, lang: str = "kk") -> InlineKeyboardMarkup:
    """Кнопка 'Устазға сұрақ' — заметная, когда ИИ не уверен в ответе."""
    if lang == "ru":
        btn_text = "🕌 Задать вопрос устазу (рекомендуем)"
    else:
        btn_text = "🕌 Устазға сұрақ қою (ұсынамыз)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=btn_text,
                    callback_data=f"ask_ustaz:{query_log_id}",
                ),
            ],
        ]
    )


def get_suggestion_keyboard(
    suggestions: list[str], query_log_id: int, lang: str = "kk",
    show_ustaz: bool = False, is_uncertain: bool = False,
) -> InlineKeyboardMarkup:
    """
    Клавиатура с предложениями 'Білесіз бе?' и кнопкой устаза.

    suggestions: список текстовых предложений (макс 3)
    show_ustaz: показать кнопку устаза (всегда)
    is_uncertain: если True, кнопка устаза заметнее
    """
    buttons = []

    # Кнопки-предложения
    for i, suggestion in enumerate(suggestions[:3]):
        # Обрезаем текст для кнопки (макс 64 символа)
        btn_text = f"💡 {suggestion}"
        if len(btn_text) > 64:
            btn_text = btn_text[:61] + "..."
        buttons.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"suggest:{i}",
            ),
        ])

    # Кнопка "Устазға сұрақ"
    if is_uncertain:
        if lang == "ru":
            ustaz_text = "🕌 Задать вопрос устазу (рекомендуем)"
        else:
            ustaz_text = "🕌 Устазға сұрақ қою (ұсынамыз)"
    else:
        ustaz_text = get_msg("btn_ask_ustaz", lang)

    buttons.append([
        InlineKeyboardButton(
            text=ustaz_text,
            callback_data=f"ask_ustaz:{query_log_id}",
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
