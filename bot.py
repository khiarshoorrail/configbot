import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
import database
from handlers import backup, buy, chat, mysubs, panels, referral, start


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not config.BOT_TOKEN or not config.ADMIN_ID:
        raise SystemExit("BOT_TOKEN و ADMIN_ID را در فایل .env تنظیم کن.")

    await database.init_db()
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
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
