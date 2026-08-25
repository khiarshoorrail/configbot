import logging

from aiogram import F, Router
from aiogram.types import Message

import database
import plans
import texts
from keyboards import main_menu

router = Router()
log = logging.getLogger(__name__)


@router.message(F.text == texts.BTN_MY_SUBS)
async def my_subs(message: Message) -> None:
    orders = await database.delivered_orders(message.from_user.id)
    if not orders:
        await message.answer("هنوز اشتراک فعالی نداری. با دکمه «خرید اشتراک» شروع کن!", reply_markup=main_menu())
        return
    lines = ["📦 اشتراک‌های تو:\n"]
    for o in orders:
        vol = plans.VOLUMES.get(o["volume_key"], {}).get("title", "?")
        dur = plans.DURATIONS.get(o["duration_key"], {}).get("title", "?")
        lines.append(f"• {vol} — {dur}\n<code>{o['sub_url']}</code>\n")
    await message.answer("\n".join(lines), reply_markup=main_menu())
