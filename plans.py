# پلن‌های فروش حالا در دیتابیس ذخیره می‌شوند و از وب‌پنل ادمین قابل ویرایش‌اند.
# این مقادیر فقط برای seed اولیه (بار اول اجرا) استفاده می‌شوند.
# قیمت‌ها تومان؛ 0-گیگ یعنی نامحدود.

import database

SEED_VOLUMES = {
    "vol_10": {"title": "۱۰ گیگابایت", "gb": 10},
    "vol_30": {"title": "۳۰ گیگابایت", "gb": 30},
    "vol_50": {"title": "۵۰ گیگابایت", "gb": 50},
    "vol_unlimited": {"title": "نامحدود", "gb": 0},
}

SEED_DURATIONS = {
    "dur_10": {"title": "۱۰ روزه", "days": 10, "price": 35000},
    "dur_20": {"title": "۲۰ روزه", "days": 20, "price": 60000},
    "dur_30": {"title": "۱ ماهه (۳۰ روز)", "days": 30, "price": 90000},
}

SEED_UNLIMITED_DAY_PRICE = 5000


async def get_volumes() -> dict:
    rows = await database.get_plans("volume")
    return {r["key"]: {"title": r["title"], "gb": r["gb"]} for r in rows}


async def get_durations() -> dict:
    rows = await database.get_plans("duration")
    return {r["key"]: {"title": r["title"], "days": r["days"], "price": r["price"]} for r in rows}


async def get_unlimited_day_price() -> int:
    val = await database.get_setting("unlimited_day_price")
    try:
        return int(val) if val is not None else SEED_UNLIMITED_DAY_PRICE
    except ValueError:
        return SEED_UNLIMITED_DAY_PRICE


async def get_price(volume_key: str, duration_key: str) -> int:
    volumes = await get_volumes()
    durations = await get_durations()
    vol = volumes.get(volume_key)
    dur = durations.get(duration_key)
    if not vol or not dur:
        return 0
    if vol["gb"] == 0:
        return await get_unlimited_day_price() * dur["days"]
    return dur["price"]


async def order_summary(volume_key: str, duration_key: str) -> str:
    volumes = await get_volumes()
    durations = await get_durations()
    vol = volumes.get(volume_key, {})
    dur = durations.get(duration_key, {})
    price = await get_price(volume_key, duration_key)
    return f"{vol.get('title', '?')} — {dur.get('title', '?')} — {price:,} تومان"
