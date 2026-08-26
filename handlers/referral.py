import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

import app_settings
import config
import database
from keyboards import main_menu_for
from panels_api import AllPanelsFailedError, create_config_on_any_panel, gb_to_bytes

router = Router()
log = logging.getLogger(__name__)


@router.message(F.text == "🎁 دعوت دوستان")
async def show_referral(message: Message) -> None:
    bot_info = await message.bot.me()
    link = f"https://t.me/{bot_info.username}?start=ref{message.from_user.id}"
    count = await database.referral_count(message.from_user.id)
    target = await app_settings.referral_target()
    gb = await app_settings.reward_gb()
    days = await app_settings.reward_days()

    filled = min(count, target)
    bar = "🟩" * filled + "⬜" * (target - filled)

    template = await app_settings.text("txt_referral_info")
    await message.answer(
        template.format(link=link, count=count, target=target, bar=bar, gb=gb, days=days),
        reply_markup=main_menu_for(message.from_user.id),
    )


async def maybe_reward(bot: Bot, user_id: int) -> None:
    """بعد از هر رفرال جدید چک می‌کند که آیا جایزه صادر شود."""
    if await database.is_rewarded(user_id):
        return
    target = await app_settings.referral_target()
    count = await database.referral_count(user_id)
    if count < target:
        return

    gb = await app_settings.reward_gb()
    days = await app_settings.reward_days()

    await database.mark_rewarded(user_id)
    try:
        sub_url, _panel_name = await create_config_on_any_panel(gb_to_bytes(gb), days)
    except (AllPanelsFailedError, Exception) as e:  # noqa: BLE001 - پنل در دسترس نیست؛ جایزه بعداً دستی داده شود
        log.error("referral reward failed for %s: %s", user_id, e)
        await bot.send_message(
            config.ADMIN_ID,
            f"⚠️ صدور جایزه رفرالی برای کاربر {user_id} شکست خورد. دستی بررسی کن.",
        )
        return

    reward_template = (
        "🎉 تبریک! {target} دوست تو رو دعوت کردی.\n\n"
        "اشتراک رایگان {gb} گیگابایتی ({days} روزه) فعال شد!\n\n"
        "🔗 لینک اشتراک:\n<code>{sub_url}</code>\n\n"
        "راهنمای اتصال مثل قبل: لینک رو کپی کن و توی برنامه v2ray واردش کن."
    )
    await bot.send_message(
        user_id,
        reward_template.format(target=target, gb=gb, days=days, sub_url=sub_url),
    )
