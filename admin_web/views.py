import logging
import os

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


def render(template: str, **ctx) -> web.Response:
    ctx.setdefault("password_enabled", bool(config.ADMIN_WEB_PASSWORD))
    html = env.get_template(template).render(**ctx)
    return web.Response(text=html, content_type="text/html")


def _fmt_order(o: dict) -> dict:
    o = dict(o)
    o["status_label"] = STATUS_LABELS.get(o["status"], o["status"])
    return o


async def login_page(request: web.Request) -> web.Response:
    if not config.ADMIN_WEB_PASSWORD:
        raise web.HTTPFound("/")
    return render("login.html", error="")


async def login_post(request: web.Request) -> web.Response:
    form = await request.post()
    if auth.check_password(str(form.get("password", ""))):
        token = auth.create_session()
        resp = web.HTTPFound("/")
        resp.set_cookie("admin_session", token, httponly=True, samesite="Lax")
        return resp
    return render("login.html", error="رمز اشتباه است.")


async def logout(request: web.Request) -> web.Response:
    auth.end_session(request.cookies.get("admin_session"))
    resp = web.HTTPFound("/login")
    resp.del_cookie("admin_session")
    return resp


async def dashboard(request: web.Request) -> web.Response:
    stats = await database.stats_overview()
    msg = request.query.get("msg", "")
    err = request.query.get("err", "")
    return render("dashboard.html", stats=stats, msg=msg, err=err)


async def broadcast(request: web.Request) -> web.Response:
    form = await request.post()
    text = str(form.get("text", "")).strip()
    if not text:
        raise web.HTTPFound("/?err=" + "متن خالی است")
    bot: Bot = request.app["bot"]
    user_ids = await database.get_all_user_ids()
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, f"📢 {text}")
            sent += 1
        except Exception:
            log.warning("broadcast to %s failed", uid)
            failed += 1
    raise web.HTTPFound(f"/?msg={sent} نفر دریافت کردند، {failed} ناموفق")


async def users_page(request: web.Request) -> web.Response:
    q = request.query.get("q", "").strip()
    rows = await database.list_users_stats(q)
    return render("users.html", users=rows, q=q)


async def orders_page(request: web.Request) -> web.Response:
    status = request.query.get("status", "")
    rows = [_fmt_order(o) for o in await database.list_orders_admin(status)]
    msg = request.query.get("msg", "")
    return render(
        "orders.html",
        orders=rows,
        status=status,
        status_labels=STATUS_LABELS.items(),
        msg=msg,
    )


async def order_action(request: web.Request) -> web.Response:
    order_id = int(request.match_info["order_id"])
    action = request.match_info["action"]
    bot: Bot = request.app["bot"]
    if action == "approve":
        result = await approve_order_core(bot, order_id)
        msg = "تأیید و تحویل شد ✅" if result == "ok" else ("قبلاً پردازش شده" if result == "already" else result[7:])
        raise web.HTTPFound(f"/orders?msg={msg}")
    elif action == "reject":
        result = await reject_order_core(bot, order_id)
        raise web.HTTPFound("/orders?msg=" + ("رد شد" if result == "ok" else "قبلاً پردازش شده"))
    raise web.HTTPNotFound()


async def plans_page(request: web.Request) -> web.Response:
    volumes = await database.get_plans("volume")
    durations = await database.get_plans("duration")
    unlimited_price = await plans.get_unlimited_day_price()
    msg = request.query.get("msg", "")
    return render("plans.html", volumes=volumes, durations=durations,
                  unlimited_price=unlimited_price, msg=msg)


async def plan_save(request: web.Request) -> web.Response:
    form = await request.post()
    kind = request.match_info["kind"]
    key = str(form.get("key", "")).strip()
    title = str(form.get("title", "")).strip()
    if not key or not title:
        raise web.HTTPFound("/plans?msg=کلید و عنوان الزامی است")
    try:
        if kind == "volume":
            gb = int(form.get("gb") or 0)
            await database.upsert_plan("volume", key, title, gb=gb)
        else:
            days = int(form.get("days") or 0)
            price = int(form.get("price") or 0)
            await database.upsert_plan("duration", key, title, days=days, price=price)
    except ValueError:
        raise web.HTTPFound("/plans?msg=" + "اعداد نامعتبر است")
    raise web.HTTPFound("/plans?msg=" + "ذخیره شد")


async def plan_delete(request: web.Request) -> web.Response:
    kind = request.match_info["kind"]
    key = request.query.get("key", "")
    if key:
        await database.delete_plan(kind, key)
    raise web.HTTPFound("/plans?msg=" + "حذف شد")


async def unlimited_price_save(request: web.Request) -> web.Response:
    form = await request.post()
    try:
        price = int(form.get("price") or 0)
    except ValueError:
        raise web.HTTPFound("/plans?msg=قیمت نامعتبر است")
    await database.set_setting("unlimited_day_price", str(price))
    raise web.HTTPFound("/plans?msg=" + "قیمت نامحدود ذخیره شد")


async def panels_page(request: web.Request) -> web.Response:
    panels = await database.list_panels()
    msg = request.query.get("msg", "")
    tested = request.query.get("tested", "")
    return render("panels.html", panels=panels, msg=msg, tested=tested)


async def panel_add(request: web.Request) -> web.Response:
    form = await request.post()
    name = str(form.get("name", "")).strip()
    type_ = str(form.get("type", "xui")).strip()
    base_url = str(form.get("base_url", "")).strip().rstrip("/")
    sub_url = str(form.get("sub_base_url", "")).strip().rstrip("/")
    username = str(form.get("username", "")).strip() or None
    password = str(form.get("password", "")).strip() or None
    inbound_raw = str(form.get("inbound_id", "")).strip()
    if not name or not base_url.startswith(("http://", "https://")) or not sub_url:
        raise web.HTTPFound("/panels?msg=" + "نام، آدرس (با http/https) و آدرس اشتراک الزامی است")
    try:
        inbound_id = int(inbound_raw) if inbound_raw else None
    except ValueError:
        raise web.HTTPFound("/panels?msg=اینباند باید عدد باشد")
    pid = await database.add_panel(name, type_, base_url, sub_url,
                                   username=username, password=password, inbound_id=inbound_id)
    # تست اتصال اولیه
    p = await database.get_panel(pid)
    try:
        detail = await test_panel(p)
        raise web.HTTPFound(f"/panels?msg={name}: {detail}")
    except (PanelError, Exception) as e:  # noqa: BLE001
        raise web.HTTPFound(f"/panels?msg={name} ذخیره شد اما تست ناموفق: {str(e)[:150]}")


async def panel_edit(request: web.Request) -> web.Response:
    pid = int(request.match_info["panel_id"])
    form = await request.post()
    fields = {}
    for src, dst in (("name", "name"), ("base_url", "base_url"), ("sub_base_url", "sub_base_url"),
                     ("username", "username"), ("password", "password")):
        val = str(form.get(src, "")).strip()
        fields[dst] = val or None
    inbound_raw = str(form.get("inbound_id", "")).strip()
    try:
        fields["inbound_id"] = int(inbound_raw) if inbound_raw else None
    except ValueError:
        raise web.HTTPFound("/panels?msg=اینباند باید عدد باشد")
    if not fields["base_url"]:
        del fields["base_url"]
    await database.update_panel(pid, **fields)
    raise web.HTTPFound("/panels?msg=" + "ذخیره شد")


async def panel_delete(request: web.Request) -> web.Response:
    await database.delete_panel(int(request.match_info["panel_id"]))
    raise web.HTTPFound("/panels?msg=" + "حذف شد")


async def panel_toggle(request: web.Request) -> web.Response:
    pid = int(request.match_info["panel_id"])
    p = await database.get_panel(pid)
    if p:
        await database.update_panel(pid, enabled=0 if p["enabled"] else 1)
    raise web.HTTPFound("/panels")


async def panel_test(request: web.Request) -> web.Response:
    p = await database.get_panel(int(request.match_info["panel_id"]))
    if not p:
        raise web.HTTPFound("/panels")
    try:
        detail = await test_panel(p)
        raise web.HTTPFound(f"/panels?tested={p['name']}: {detail}")
    except (PanelError, Exception) as e:  # noqa: BLE001
        raise web.HTTPFound(f"/panels?tested={p['name']}: ناموفق — {str(e)[:200]}")


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/login", login_page)
    app.router.add_post("/login", login_post)
    app.router.add_get("/logout", logout)
    app.router.add_get("/", dashboard)
    app.router.add_post("/broadcast", broadcast)
    app.router.add_get("/users", users_page)
    app.router.add_get("/orders", orders_page)
    app.router.add_post("/orders/{order_id}/{action}", order_action)
    app.router.add_get("/plans", plans_page)
    app.router.add_post("/plans/{kind}", plan_save)
    app.router.add_post("/plans-unlimited", unlimited_price_save)
    app.router.add_get("/plans-delete/{kind}", plan_delete)
    app.router.add_get("/panels", panels_page)
    app.router.add_post("/panels/add", panel_add)
    app.router.add_post("/panels/{panel_id}/edit", panel_edit)
    app.router.add_post("/panels/{panel_id}/delete", panel_delete)
    app.router.add_post("/panels/{panel_id}/toggle", panel_toggle)
    app.router.add_get("/panels/{panel_id}/test", panel_test)
