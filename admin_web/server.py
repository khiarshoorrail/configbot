import logging
import secrets

from aiohttp import web
from aiogram import Bot

import config
from admin_web.views import setup_routes

log = logging.getLogger(__name__)

# session token های معتبر در حافظه
SESSIONS: set[str] = set()

PUBLIC_PATHS = {"/login"}


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if not config.ADMIN_WEB_PASSWORD:
        return await handler(request)
    path = request.path
    if path in PUBLIC_PATHS or request.cookies.get("admin_session") in SESSIONS:
        return await handler(request)
    if request.method == "POST" and path == "/login":
        return await handler(request)
    raise web.HTTPFound("/login")


def make_app(bot: Bot) -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app["bot"] = bot
    setup_routes(app)
    return app


async def start_admin_web(bot: Bot) -> None:
    app = make_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.ADMIN_WEB_HOST, config.ADMIN_WEB_PORT)
    await site.start()
    log.info("وب‌پنل ادمین روی http://%s:%s فعال شد", config.ADMIN_WEB_HOST, config.ADMIN_WEB_PORT)


def create_session() -> str:
    token = secrets.token_hex(32)
    SESSIONS.add(token)
    return token


def valid_session(token: str | None) -> bool:
    return bool(token and token in SESSIONS)


def end_session(token: str | None) -> None:
    if token:
        SESSIONS.discard(token)


def check_password(password: str) -> bool:
    return secrets.compare_digest(password, config.ADMIN_WEB_PASSWORD)
