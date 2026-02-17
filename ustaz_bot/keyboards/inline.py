"""
Inline-клавиатуры для устаз-бота.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_queue_item_keyboard(consultation_id: int) -> InlineKeyboardMarkup:
    """Кнопки для элемента очереди: взять / пропустить."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Қабылдау",
                    callback_data=f"take:{consultation_id}",
                ),
                InlineKeyboardButton(
                    text="⏭ Өткізу",
                    callback_data=f"skip:{consultation_id}",
                ),
            ],
        ]
    )


def get_cancel_answer_keyboard(consultation_id: int) -> InlineKeyboardMarkup:
    """Кнопка отмены при ответе на вопрос."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Болдырмау",
                    callback_data=f"cancel_answer:{consultation_id}",
                ),
            ],
        ]
    )
