import logging

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

import config
import database
import texts
from keyboards import main_menu

router = Router()
log = logging.getLogger(__name__)


def _menu_for(user_id: int) -> str:
    return texts.MAIN_MENU


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    user = message.from_user
    await database.upsert_user(user.id, user.username, user.full_name or "")

    payload = command.args or ""
    if payload.startswith("ref"):
        try:
            referrer_id = int(payload[3:])
        except ValueError:
            referrer_id = 0
        if referrer_id and referrer_id != user.id:
            # هر کاربر فقط یک بار می‌تواند معرفی شود (یکتا بودن invited_id در جدول)
            counted = await database.add_referral(referrer_id, user.id)
            if counted:
                log.info("referral: %s invited %s", referrer_id, user.id)
                from handlers.referral import maybe_reward

                await maybe_reward(message.bot, referrer_id)
                await message.answer(texts.INVITED_BY)

    await message.answer(
        texts.WELCOME.format(name=user.first_name or "") + texts.MAIN_MENU,
        reply_markup=main_menu(admin_menu=user.id == config.ADMIN_ID),
    )


@router.message(F.text == texts.BTN_BACK_MAIN)
async def back_to_main(message: Message) -> None:
    await message.answer(texts.MAIN_MENU.strip(), reply_markup=main_menu())
