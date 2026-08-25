import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

import config
import texts
from keyboards import chat_menu, main_menu

router = Router()
log = logging.getLogger(__name__)


class ChatStates(StatesGroup):
    chatting = State()


UID_IN_HEADER = re.compile(r"#(\d{4,})")


def extract_uid_from_header(text: str) -> int | None:
    m = UID_IN_HEADER.search(text or "")
    return int(m.group(1)) if m else None


# --- پاسخ ادمین (ریپلای روی پیام رله‌شده) ---
@router.message(F.from_user.id == config.ADMIN_ID, F.reply_to_message)
async def admin_reply(message: Message, bot: Bot) -> None:
    replied = message.reply_to_message
    target_uid = extract_uid_from_header(replied.caption or replied.text or "")
    if not target_uid:
        return
    body = message.text or ""
    try:
        await bot.send_message(target_uid, f"💬 {texts.SUPPORT_PREFIX}:\n{body}")
        await message.answer("✅ ارسال شد.")
    except Exception:
        log.exception("admin reply to %s failed", target_uid)
        await message.answer("⚠️ ارسال به کاربر شکست خورد.")


async def build_user_header(bot: Bot, user) -> str:
    """سربرگ کامل اطلاعات کاربر برای نمایش به ادمین."""
    import database

    u = await database.get_user(user.id)
    referrals = await database.referral_count(user.id)
    orders = await database.delivered_orders(user.id)
    username = f"@{user.username}" if user.username else "ندارد"
    joined = u["joined_at"][:10] if u and u.get("joined_at") else "—"
    return texts.NEW_USER_MESSAGE.format(
        ticket=user.id,
        name=user.full_name or "بی‌نام",
        uid=user.id,
        username=username,
        referrals=referrals,
        orders=len(orders),
        joined=joined,
    )


# --- سمت کاربر ---
@router.message(F.text == texts.BTN_SUPPORT)
async def start_chat(message: Message, state: FSMContext) -> None:
    await state.set_state(ChatStates.chatting)
    await message.answer(texts.CHAT_STARTED, reply_markup=chat_menu())


@router.message(F.text == texts.BTN_END_CHAT)
async def end_chat(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await message.answer(texts.CHAT_ENDED_USER, reply_markup=main_menu())
    try:
        await bot.send_message(config.ADMIN_ID, texts.USER_LEFT + f" #{message.from_user.id}")
    except Exception:
        pass


@router.message(StateFilter(ChatStates.chatting))
async def relay_to_admin(message: Message, bot: Bot) -> None:
    header = await build_user_header(bot, message.from_user)
    header += "\n" + texts.ADMIN_HINT_REPLY

    try:
        if message.photo:
            await bot.send_photo(config.ADMIN_ID, message.photo[-1].file_id, caption=header[:1024])
        elif message.video:
            await bot.send_video(config.ADMIN_ID, message.video.file_id, caption=header)
        elif message.document:
            await bot.send_document(config.ADMIN_ID, message.document.file_id, caption=header)
        elif message.voice:
            await bot.send_voice(config.ADMIN_ID, message.voice.file_id, caption=header)
        else:
            await bot.send_message(config.ADMIN_ID, header + "\n" + (message.text or ""))
    except Exception:
        log.exception("relay to admin failed")
        await message.answer("⚠️ الان نمی‌تونم پیامت رو برسونم. چند لحظه بعد دوباره امتحان کن.")
