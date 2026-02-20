"""
Inline-клавиатуры для бота.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import SUBSCRIPTION_PLANS, KASPI_PAY_LINK, KASPI_PRICE_KZT
from core.messages import get_msg


def get_subscription_keyboard(lang: str = "kk") -> InlineKeyboardMarkup:
    """Клавиатура с тарифами подписки (Telegram Stars + Kaspi)."""
    buttons = []
    for plan_key, plan_info in SUBSCRIPTION_PLANS.items():
        price = plan_info["price"]
        label = plan_info.get("label", plan_key)
        buttons.append(
            [InlineKeyboardButton(text=f"⭐ {label} — {price} Stars", callback_data=f"subscribe:{plan_key}")]
        )
    # Kaspi кнопка (если настроена ссылка)
    if KASPI_PAY_LINK:
        buttons.append([InlineKeyboardButton(
            text=f"💳 Kaspi — {KASPI_PRICE_KZT} ₸",
            callback_data="kaspi_pay",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_answer_keyboard(
    suggestions: list[str] = None,
    query_log_id: int = 0,
    lang: str = "kk",
    is_uncertain: bool = False,
) -> InlineKeyboardMarkup:
    """
    Клавиатура под ответом ИИ:
    - Suggestions (кликабельные вопросы)
    - Устазға сұрақ (только если ИИ не уверен)
    - Календарь (всегда)
    """
    buttons = []

    # Кнопки-предложения (кликабельные — отправляют вопрос)
    if suggestions:
        for i, suggestion in enumerate(suggestions[:3]):
            btn_text = f"💡 {suggestion}"
            if len(btn_text) > 64:
                btn_text = btn_text[:61] + "..."
            buttons.append([
                InlineKeyboardButton(
                    text=btn_text,
                    callback_data=f"suggest:{i}",
                ),
            ])

    # Кнопка "Устазға сұрақ" — только когда ИИ не уверен
    if is_uncertain:
        if lang == "ru":
            ustaz_text = "🕌 Задать вопрос устазу (рекомендуем)"
        else:
            ustaz_text = "🕌 Устазға сұрақ қою (ұсынамыз)"
        buttons.append([
            InlineKeyboardButton(
                text=ustaz_text,
                callback_data=f"ask_ustaz:{query_log_id}",
            ),
        ])

    # Кнопка календаря — всегда
    cal_text = get_msg("btn_calendar", lang)
    buttons.append([
        InlineKeyboardButton(
            text=cal_text,
            callback_data="show_calendar",
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Legacy — для обратной совместимости
def get_ask_ustaz_keyboard(query_log_id: int, lang: str = "kk") -> InlineKeyboardMarkup:
    return get_answer_keyboard(query_log_id=query_log_id, lang=lang)


def get_suggestion_keyboard(
    suggestions: list[str], query_log_id: int, lang: str = "kk",
    show_ustaz: bool = False, is_uncertain: bool = False,
) -> InlineKeyboardMarkup:
    return get_answer_keyboard(
        suggestions=suggestions,
        query_log_id=query_log_id,
        lang=lang,
        is_uncertain=is_uncertain,
    )
