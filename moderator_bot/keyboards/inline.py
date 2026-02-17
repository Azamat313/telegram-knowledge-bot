"""
Inline-клавиатуры для модератор-бота.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_ticket_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Кнопки для тикета: взять / пропустить."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Жауап беру",
                    callback_data=f"mod_take:{ticket_id}",
                ),
                InlineKeyboardButton(
                    text="⏭ Өткізу",
                    callback_data=f"mod_skip:{ticket_id}",
                ),
            ],
        ]
    )


def get_cancel_ticket_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Кнопка отмены при ответе на тикет."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Болдырмау",
                    callback_data=f"mod_cancel:{ticket_id}",
                ),
            ],
        ]
    )
