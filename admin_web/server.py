import logging
import secrets
import time

from aiohttp import web
from aiogram import Bot

import config
from admin_web.views import setup_routes

log = logging.getLogger(__name__)

# session token → {"csrf": ..., "expires": ...}
SESSIONS: dict[str, dict] = {}
SESSION_TTL = 12 * 3600

PUBLIC_PATHS = {"/login"}

# IP → [timestamp تلاش‌های ناموفق]
LOGIN_FAILURES: dict[str, list[float]] = {}
MAX_FAILURES = 5
FAILURE_WINDOW = 600

# توکن‌های یک‌بارمصرف ورود از تلگرام: token → expires
MAGIC_TOKENS: dict[str, float] = {}
MAGIC_TTL = 300
MAX_MAGIC_TOKENS = 3

SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "font-src https://cdn.jsdelivr.net; "
        "img-src 'self' data:"
    ),
}


def _cleanup() -> None:
    now = time.time()
    expired = [t for t, s in SESSIONS.items() if s["expires"] < now]
    for t in expired:
        del SESSIONS[t]
    cutoff = now - FAILURE_WINDOW
    for ip in list(LOGIN_FAILURES):
        LOGIN_FAILURES[ip] = [ts for ts in LOGIN_FAILURES[ip] if ts > cutoff]
        if not LOGIN_FAILURES[ip]:
            del LOGIN_FAILURES[ip]


def _client_ip(request: web.Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote or "?"


@web.middleware
async def security_middleware(request: web.Request, handler):
    response = await handler(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path

    # لینک یک‌بارمصرف تلگرامی — عمومی
    if path.startswith("/login/tk/"):
        return await handler(request)

    # CSRF برای همه POST های احرازشده (به‌جز خود login)
    if request.method == "POST" and path not in PUBLIC_PATHS:
        token = request.cookies.get("admin_session")
        form_csrf = ""
        if token and token in SESSIONS:
            form = await request.post()
            form_csrf = str(form.get("csrf", ""))
            request["form"] = form
        if not token or token not in SESSIONS or not secrets.compare_digest(form_csrf, SESSIONS[token]["csrf"]):
            raise web.HTTPForbidden(text="درخواست نامعتبر (CSRF).")

    if path in PUBLIC_PATHS:
        return await handler(request)

    token = request.cookies.get("admin_session")
    session = SESSIONS.get(token) if token else None
    if not session or session["expires"] < time.time():
        if token:
            SESSIONS.pop(token, None)
        raise web.HTTPFound("/login")

    return await handler(request)


def make_app(bot: Bot) -> web.Application:
    app = web.Application(middlewares=[security_middleware, auth_middleware],
                          client_max_size=1024 * 1024)
    app["bot"] = bot
    setup_routes(app)
    return app


async def start_admin_web(bot: Bot) -> None:
    if not config.ADMIN_WEB_PASSWORD:
        log.warning("وب‌پنل استارت نشد: ADMIN_WEB_PASSWORD در .env تنظیم نشده است.")
        return
    app = make_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.ADMIN_WEB_HOST, config.ADMIN_WEB_PORT)
    await site.start()
    log.info("وب‌پنل ادمین روی پورت %s فعال شد.", config.ADMIN_WEB_PORT)


# --- helpers استفاده‌شده توسط views ---

def login_allowed(ip: str) -> bool:
    _cleanup()
    return len(LOGIN_FAILURES.get(ip, [])) < MAX_FAILURES


def record_login_failure(ip: str) -> None:
    LOGIN_FAILURES.setdefault(ip, []).append(time.time())


def create_session() -> tuple[str, str]:
    """(session_token, csrf_token)"""
    _cleanup()
    token = secrets.token_hex(32)
    csrf = secrets.token_hex(32)
    SESSIONS[token] = {"csrf": csrf, "expires": time.time() + SESSION_TTL}
    return token, csrf


def get_csrf(token: str | None) -> str:
    if token and token in SESSIONS:
        return SESSIONS[token]["csrf"]
    return ""


def end_session(token: str | None) -> None:
    if token:
        SESSIONS.pop(token, None)


def check_password(password: str) -> bool:
    return bool(config.ADMIN_WEB_PASSWORD) and secrets.compare_digest(password, config.ADMIN_WEB_PASSWORD)


def create_magic_token() -> str | None:
    """توکن یک‌بارمصرف ورود (۵ دقیقه)؛ سقف ۳ توکن باز."""
    _cleanup()
    if len(MAGIC_TOKENS) >= MAX_MAGIC_TOKENS:
        return None
    token = secrets.token_hex(32)
    MAGIC_TOKENS[token] = time.time() + MAGIC_TTL
    return token


def consume_magic_token(token: str) -> bool:
    _cleanup()
    expires = MAGIC_TOKENS.pop(token, None)
    return bool(expires and expires >= time.time())
