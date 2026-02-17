"""
Inline-клавиатуры для бота.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import SUBSCRIPTION_PLANS, MSG_ASK_USTAZ_BUTTON


def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с тарифами подписки."""
    buttons = []
    for plan_key, plan_info in SUBSCRIPTION_PLANS.items():
        price = plan_info["price"]
        currency = plan_info["currency"]
        days = plan_info["days"]

        if plan_key == "monthly":
            label = f"Месячная — {price} {currency}"
        elif plan_key == "yearly":
            label = f"Годовая — {price} {currency}"
        else:
            label = f"{plan_key} — {price} {currency} ({days} дн.)"

        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"subscribe:{plan_key}")]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_subscription_keyboard(plan_key: str) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения подписки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить оплату",
                    callback_data=f"confirm_sub:{plan_key}",
                ),
            ],
            [
                InlineKeyboardButton(text="Отмена", callback_data="cancel_sub"),
            ],
        ]
    )


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
