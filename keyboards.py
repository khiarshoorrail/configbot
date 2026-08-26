import config

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import texts


def main_menu(admin_menu: bool = False) -> ReplyKeyboardMarkup:
    rows = [list(row) for row in texts.MAIN_KEYBOARD_ROWS]
    if admin_menu:
        rows.append([texts.BTN_PANELS])
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=b) for b in row] for row in rows],
        resize_keyboard=True,
    )


def main_menu_for(user_id: int) -> ReplyKeyboardMarkup:
    """منوی اصلی با تشخیص خودکار ادمین — همه‌جا از این استفاده شود."""
    return main_menu(admin_menu=user_id == config.ADMIN_ID)


def chat_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=b) for b in row] for row in texts.CHAT_KEYBOARD_ROWS],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.BTN_CANCEL)]],
        resize_keyboard=True,
    )


def volumes_kb(volumes: dict) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for key, vol in volumes.items():
        kb.button(text=vol["title"], callback_data=f"vol:{key}")
    kb.adjust(2)
    return kb


def durations_kb(durations: dict) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for key, dur in durations.items():
        kb.button(text=dur["title"], callback_data=f"dur:{key}")
    kb.adjust(3)
    return kb


def receipt_actions(order_id: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تأیید پرداخت", callback_data=f"approve:{order_id}")
    kb.button(text="❌ رد", callback_data=f"reject:{order_id}")
    kb.adjust(2)
    return kb
