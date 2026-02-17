"""
Inline-клавиатуры для бота.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import SUBSCRIPTION_PLANS, MSG_ASK_USTAZ_BUTTON


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


def get_ask_ustaz_keyboard(query_log_id: int) -> InlineKeyboardMarkup:
    """Кнопка 'Устазға сұрақ қою' под AI-ответом."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🕌 {MSG_ASK_USTAZ_BUTTON}",
                    callback_data=f"ask_ustaz:{query_log_id}",
                ),
            ],
        ]
    )


def get_ustaz_confirm_keyboard(query_log_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения отправки вопроса устазу."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Жіберу",
                    callback_data=f"confirm_ustaz:{query_log_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Болдырмау",
                    callback_data="cancel_ustaz",
                ),
            ],
        ]
    )
