import logging
import os
from urllib.parse import quote

import jinja2
from aiohttp import web
from aiogram import Bot

import config
import database
import plans
from admin_web import server as auth
from panels_api import PanelError, test_panel
from services import approve_order_core, reject_order_core

log = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
    autoescape=True,
)

STATUS_LABELS = {
    "awaiting_confirm": "⏳ در انتظار تأیید",
    "delivered": "✅ تحویل‌شده",
    "rejected": "❌ ردشده",
}


def _safe_int(value, default=None) -> int:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def _flash(path: str, msg: str, err: bool = False) -> web.HTTPFound:
    key = "err" if err else "msg"
    sep = "&" if "?" in path else "?"
    raise web.HTTPFound(f"{path}{sep}{key}={quote(msg)}")


def _form(request: web.Request) -> dict:
    """فرم POST — میدل‌ور CSRF آن را قبلاً parse کرده است."""
    return request.get("form") or {}


def render(request: web.Request, template: str, **ctx) -> web.Response:
    ctx.setdefault("password_enabled", bool(config.ADMIN_WEB_PASSWORD))
    ctx.setdefault("csrf", auth.get_csrf(request.cookies.get("admin_session")))
    html = env.get_template(template).render(**ctx)
    return web.Response(text=html, content_type="text/html")


async def login_page(request: web.Request) -> web.Response:
    ip = auth._client_ip(request)
    if not auth.login_allowed(ip):
        return render(request, "login.html", error="تلاش‌های زیاد. ۱۰ دقیقه بعد امتحان کن.")
    return render(request, "login.html", error="")


async def login_post(request: web.Request) -> web.Response:
    ip = auth._client_ip(request)
    if not auth.login_allowed(ip):
        return render(request, "login.html", error="تلاش‌های زیاد. ۱۰ دقیقه بعد امتحان کن.")
    form = await request.post()
    if auth.check_password(str(form.get("password", ""))):
        token, csrf = auth.create_session()
        resp = web.HTTPFound("/")
        resp.set_cookie("admin_session", token, httponly=True, samesite="Lax",
                        secure=True, max_age=auth.SESSION_TTL)
        return resp
    auth.record_login_failure(ip)
    log.warning("failed admin login from %s", ip)
    return render(request, "login.html", error="رمز اشتباه است.")


async def logout(request: web.Request) -> web.Response:
    auth.end_session(request.cookies.get("admin_session"))
    resp = web.HTTPFound("/login")
    resp.del_cookie("admin_session")
    return resp


async def dashboard(request: web.Request) -> web.Response:
    stats = await database.stats_overview()
    msg = request.query.get("msg", "")
    err = request.query.get("err", "")
    return render(request, "dashboard.html", stats=stats, msg=msg, err=err)


async def broadcast(request: web.Request) -> web.Response:
    form = _form(request)
    text = str(form.get("text", "")).strip()
    if not text:
        _flash("/", "متن خالی است.", err=True)
    if len(text) > 4000:
        _flash("/", "متن بیش از حد طولانی است (حداکثر ۴۰۰۰ کاراکتر).", err=True)

    bot: Bot = request.app["bot"]
    user_ids = await database.get_all_user_ids()
    sent, failed = 0, 0
    for uid in user_ids:
        if uid == config.ADMIN_ID:
            continue
        try:
            await bot.send_message(uid, f"📢 {text}")
            sent += 1
        except Exception:
            log.warning("broadcast to %s failed", uid)
            failed += 1
    _flash("/", f"{sent} نفر دریافت کردند، {failed} ناموفق")


async def users_page(request: web.Request) -> web.Response:
    q = request.query.get("q", "").strip()[:100]
    rows = await database.list_users_stats(q)
    return render(request, "users.html", users=rows, q=q)


async def orders_page(request: web.Request) -> web.Response:
    status = request.query.get("status", "")
    if status not in ("", *STATUS_LABELS):
        status = ""
    rows = []
    for o in await database.list_orders_admin(status):
        o = dict(o)
        o["status_label"] = STATUS_LABELS.get(o["status"], o["status"])
        rows.append(o)
    msg = request.query.get("msg", "")
    return render(request, "orders.html", orders=rows, status=status,
                  status_labels=STATUS_LABELS.items(), msg=msg)


async def order_action(request: web.Request) -> web.Response:
    order_id = _safe_int(request.match_info["order_id"])
    action = request.match_info["action"]
    if order_id is None or action not in ("approve", "reject"):
        raise web.HTTPNotFound()

    bot: Bot = request.app["bot"]
    if action == "approve":
        result = await approve_order_core(bot, order_id)
        if result == "ok":
            _flash("/orders", "تأیید و تحویل شد ✅")
        elif result == "already":
            _flash("/orders", "قبلاً پردازش شده", err=True)
        else:
            _flash("/orders", result[7:], err=True)
    else:
        result = await reject_order_core(bot, order_id)
        if result == "ok":
            _flash("/orders", "رد شد")
        else:
            _flash("/orders", "قبلاً پردازش شده", err=True)


async def plans_page(request: web.Request) -> web.Response:
    volumes = await database.get_plans("volume")
    durations = await database.get_plans("duration")
    unlimited_price = await plans.get_unlimited_day_price()
    msg = request.query.get("msg", "")
    return render(request, "plans.html", volumes=volumes, durations=durations,
                  unlimited_price=unlimited_price, msg=msg)


async def plan_save(request: web.Request) -> web.Response:
    kind = request.match_info["kind"]
    if kind not in ("volume", "duration"):
        raise web.HTTPNotFound()
    form = _form(request)
    key = str(form.get("key", "")).strip()[:40]
    title = str(form.get("title", "")).strip()[:80]
    if not key or not title:
        _flash("/plans", "کلید و عنوان الزامی است.", err=True)
    try:
        if kind == "volume":
            gb = max(_safe_int(form.get("gb"), 0), 0)
            await database.upsert_plan("volume", key, title, gb=gb)
        else:
            days = max(_safe_int(form.get("days"), 0), 0)
            price = max(_safe_int(form.get("price"), 0), 0)
            await database.upsert_plan("duration", key, title, days=days, price=price)
    except Exception as e:  # noqa: BLE001
        log.error("plan_save failed: %s", e)
        _flash("/plans", "خطا در ذخیره.", err=True)
    _flash("/plans", "ذخیره شد ✅")


async def plan_delete(request: web.Request) -> web.Response:
    kind = request.match_info["kind"]
    if kind not in ("volume", "duration"):
        raise web.HTTPNotFound()
    form = _form(request)
    key = str(form.get("key", "")).strip()[:40]
    if key:
        await database.delete_plan(kind, key)
    _flash("/plans", "حذف شد.")


async def unlimited_price_save(request: web.Request) -> web.Response:
    form = _form(request)
    price = _safe_int(form.get("price"))
    if price is None or price < 0:
        _flash("/plans", "قیمت نامعتبر است.", err=True)
    await database.set_setting("unlimited_day_price", str(price))
    _flash("/plans", "قیمت نامحدود ذخیره شد ✅")


async def panels_page(request: web.Request) -> web.Response:
    panels = await database.list_panels()
    msg = request.query.get("msg", "")
    tested = request.query.get("tested", "")
    return render(request, "panels.html", panels=panels, msg=msg, tested=tested)


async def panel_add(request: web.Request) -> web.Response:
    form = _form(request)
    name = str(form.get("name", "")).strip()[:60]
    type_ = str(form.get("type", "xui")).strip()
    base_url = str(form.get("base_url", "")).strip().rstrip("/")
    sub_url = str(form.get("sub_base_url", "")).strip().rstrip("/")
    username = str(form.get("username", "")).strip()[:100] or None
    password = str(form.get("password", "")).strip()[:200] or None
    inbound_id = _safe_int(form.get("inbound_id"))

    if type_ not in ("xui", "marzban") or not name:
        _flash("/panels", "نام یا نوع نامعتبر است.", err=True)
    if not base_url.startswith(("http://", "https://")) or not sub_url.startswith(("http://", "https://")):
        _flash("/panels", "آدرس باید با http:// یا https:// شروع شود.", err=True)

    pid = await database.add_panel(name, type_, base_url, sub_url,
                                   username=username, password=password, inbound_id=inbound_id)
    p = await database.get_panel(pid)
    try:
        detail = await test_panel(p)
        _flash("/panels", f"«{name}» ذخیره شد — {detail} ✅")
    except (PanelError, Exception) as e:  # noqa: BLE001
        log.warning("new panel test failed (%s): %s", name, e)
        _flash("/panels", f"«{name}» ذخیره شد اما تست اتصال ناموفق بود: {str(e)[:150]}", err=True)


async def panel_edit(request: web.Request) -> web.Response:
    pid = _safe_int(request.match_info["panel_id"])
    if pid is None:
        raise web.HTTPNotFound()
    form = _form(request)
    fields = {}
    for src, dst, limit in (("name", "name", 60), ("base_url", "base_url", 300),
                            ("sub_base_url", "sub_base_url", 300),
                            ("username", "username", 100), ("password", "password", 200)):
        val = str(form.get(src, "")).strip()[:limit]
        fields[dst] = val or None
    inbound_id = _safe_int(form.get("inbound_id"))
    if inbound_id == "":
        inbound_id = None
    fields["inbound_id"] = inbound_id
    if not fields["base_url"]:
        del fields["base_url"]
    await database.update_panel(pid, **fields)
    _flash("/panels", "ذخیره شد ✅")


async def panel_delete(request: web.Request) -> web.Response:
    pid = _safe_int(request.match_info["panel_id"])
    if pid is not None:
        await database.delete_panel(pid)
    _flash("/panels", "حذف شد.")


async def panel_toggle(request: web.Request) -> web.Response:
    pid = _safe_int(request.match_info["panel_id"])
    if pid is None:
        raise web.HTTPNotFound()
    p = await database.get_panel(pid)
    if p:
        await database.update_panel(pid, enabled=0 if p["enabled"] else 1)
    raise web.HTTPFound("/panels")


async def panel_test(request: web.Request) -> web.Response:
    pid = _safe_int(request.match_info["panel_id"])
    p = await database.get_panel(pid) if pid is not None else None
    if not p:
        raise web.HTTPNotFound()
    try:
        detail = await test_panel(p)
        _flash("/panels", f"تست «{p['name']}»: {detail} ✅")
    except (PanelError, Exception) as e:  # noqa: BLE001
        _flash("/panels", f"تست «{p['name']}» ناموفق: {str(e)[:200]}", err=True)


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/login", login_page)
    app.router.add_post("/login", login_post)
    app.router.add_post("/logout", logout)
    app.router.add_get("/", dashboard)
    app.router.add_post("/broadcast", broadcast)
    app.router.add_get("/users", users_page)
    app.router.add_get("/orders", orders_page)
    app.router.add_post("/orders/{order_id}/{action}", order_action)
    app.router.add_get("/plans", plans_page)
    app.router.add_post("/plans/{kind}", plan_save)
    app.router.add_post("/plans-unlimited", unlimited_price_save)
    app.router.add_post("/plans-delete/{kind}", plan_delete)
    app.router.add_get("/panels", panels_page)
    app.router.add_post("/panels/add", panel_add)
    app.router.add_post("/panels/{panel_id}/edit", panel_edit)
    app.router.add_post("/panels/{panel_id}/delete", panel_delete)
    app.router.add_post("/panels/{panel_id}/toggle", panel_toggle)
    app.router.add_post("/panels/{panel_id}/test", panel_test)
