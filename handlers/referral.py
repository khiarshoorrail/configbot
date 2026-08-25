import logging
import os

from aiogram import Bot, F, Router
from aiogram.types import Message

import config
import database
import texts
from keyboards import main_menu
from panels_api import AllPanelsFailedError, create_config_on_any_panel, gb_to_bytes

router = Router()
log = logging.getLogger(__name__)


@router.message(F.text == texts.BTN_REFERRAL)
async def show_referral(message: Message) -> None:
    bot_info = await message.bot.me()
    link = f"https://t.me/{bot_info.username}?start=ref{message.from_user.id}"
    count = await database.referral_count(message.from_user.id)
    target = config.REFERRAL_TARGET

    filled = min(count, target)
    bar = "🟩" * filled + "⬜" * (target - filled)

    await message.answer(
        texts.REFERRAL_INFO.format(link=link, count=count, target=target, bar=bar,
                                   gb=config.REFERRAL_REWARD_GB, days=config.REFERRAL_REWARD_DAYS),
        reply_markup=main_menu(),
    )


async def maybe_reward(bot: Bot, user_id: int) -> None:
    """بعد از هر رفرال جدید چک می‌کند که آیا جایزه صادر شود."""
    if await database.is_rewarded(user_id):
        return
    count = await database.referral_count(user_id)
    if count < config.REFERRAL_TARGET:
        return

    await database.mark_rewarded(user_id)
    try:
        sub_url, _panel_name = await create_config_on_any_panel(
            gb_to_bytes(config.REFERRAL_REWARD_GB), config.REFERRAL_REWARD_DAYS
        )
    except (AllPanelsFailedError, Exception) as e:  # noqa: BLE001 - پنل در دسترس نیست؛ جایزه بعداً دستی داده شود
        log.error("referral reward failed for %s: %s", user_id, e)
        await bot.send_message(
            config.ADMIN_ID,
            f"⚠️ صدور جایزه رفرالی برای کاربر {user_id} شکست خورد. دستی بررسی کن.",
        )
        return

    await bot.send_message(
        user_id,
        texts.REFERRAL_REWARD_DELIVERED.format(
            target=config.REFERRAL_TARGET, gb=config.REFERRAL_REWARD_GB,
            days=config.REFERRAL_REWARD_DAYS, sub_url=sub_url,
        ),
    )
