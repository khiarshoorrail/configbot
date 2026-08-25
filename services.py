import logging

from aiogram import Bot

import database
import plans
import texts
from panels_api import AllPanelsFailedError, create_config_on_any_panel, gb_to_bytes

log = logging.getLogger(__name__)


async def approve_order_core(bot: Bot, order_id: int) -> str:
    """تأیید سفارش و تحویل کانفیگ. خروجی: ok | already | failed:<پیام>"""
    order = await database.get_order(order_id)
    if not order or order["status"] != "awaiting_confirm":
        return "already"

    volumes = await plans.get_volumes()
    durations = await plans.get_durations()
    vol = volumes.get(order["volume_key"])
    dur = durations.get(order["duration_key"])
    if not vol or not dur:
        return "failed:پلن این سفارش دیگر وجود ندارد"

    try:
        sub_url, panel_name = await create_config_on_any_panel(gb_to_bytes(vol["gb"]), dur["days"])
    except AllPanelsFailedError as e:
        log.error("all panels failed for order %s: %s", order_id, e)
        return f"failed:هیچ پنلی در دسترس نبود: {str(e)[:200]}"
    except Exception as e:  # noqa: BLE001
        log.error("create_config failed for order %s: %s", order_id, e)
        return f"failed:{e}"

    await database.set_order_status(order_id, "delivered", sub_url)

    try:
        await bot.send_message(order["user_id"], texts.ORDER_CONFIRMED.format(sub_url=sub_url))
    except Exception:
        log.exception("could not deliver to user %s", order["user_id"])

    return "ok"


async def reject_order_core(bot: Bot, order_id: int) -> str:
    order = await database.get_order(order_id)
    if not order or order["status"] != "awaiting_confirm":
        return "already"
    await database.set_order_status(order_id, "rejected")
    try:
        await bot.send_message(order["user_id"], texts.ORDER_REJECTED)
    except Exception:
        log.exception("could not notify user %s", order["user_id"])
    return "ok"
