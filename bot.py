import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
import database
import github_backup
from handlers import backup, buy, chat, mysubs, panels, referral, start

log = logging.getLogger(__name__)


async def daily_backup_loop(bot: Bot) -> None:
    """هر ۲۴ ساعت یک پشتیبان روی گیت‌هاب می‌گذارد."""
    while True:
        await asyncio.sleep(86400)
        if not github_backup.backup_enabled():
            continue
        try:
            url = await github_backup.upload_backup()
            log.info("daily backup ok: %s", url)
        except Exception as e:  # noqa: BLE001 — نبودن اینترنت یا API نباید ربات را بخواباند
            log.error("daily backup failed: %s", e)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not config.BOT_TOKEN or not config.ADMIN_ID:
        raise SystemExit("BOT_TOKEN و ADMIN_ID را در فایل .env تنظیم کن.")

    await database.init_db()
    await database.seed_plans()
    migrated = await database.migrate_env_panel()
    if migrated:
        logging.getLogger(__name__).info("پنل پیش‌فرض از .env وارد دیتابیس شد.")

    if config.PROXY_URL:
        bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            session=AiohttpSession(proxy=config.PROXY_URL),
        )
    else:
        bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    dp = Dispatcher(storage=MemoryStorage())

    # ترتیب مهم است: ریپلای ادمین قبل از هندلرهای عمومی چت
    dp.include_router(chat.router)
    dp.include_router(panels.router)
    dp.include_router(backup.router)
    dp.include_router(buy.router)
    dp.include_router(referral.router)
    dp.include_router(mysubs.router)
    dp.include_router(start.router)

    await bot.delete_webhook(drop_pending_updates=True)
    if config.ADMIN_WEB_ENABLED:
        from admin_web import start_admin_web

        await start_admin_web(bot)
    if github_backup.backup_enabled():
        asyncio.create_task(daily_backup_loop(bot))
        log.info("خودکار بکاپ روزانه روی گیت‌هاب فعال است.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
