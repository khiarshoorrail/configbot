# پلن‌های فروش: کلید = (حجم گیگ، مدت روز)
# 0-گیگ یعنی نامحدود. قیمت‌ها تومان هستند؛ اینجا راحت تغییر بده.

VOLUMES = {
    "vol_10": {"title": "۱۰ گیگابایت", "gb": 10},
    "vol_30": {"title": "۳۰ گیگابایت", "gb": 30},
    "vol_50": {"title": "۵۰ گیگابایت", "gb": 50},
    "vol_unlimited": {"title": "نامحدود", "gb": 0},
}

# حداکثر مدت مجاز: ۳۰ روز
DURATIONS = {
    "dur_10": {"title": "۱۰ روزه", "days": 10, "price": 35000},
    "dur_20": {"title": "۲۰ روزه", "days": 20, "price": 60000},
    "dur_30": {"title": "۱ ماهه (۳۰ روز)", "days": 30, "price": 90000},
}

PRICE_PER_UNLIMITED_DAY = 5000


def get_price(volume_key: str, duration_key: str) -> int:
    vol = VOLUMES[volume_key]
    dur = DURATIONS[duration_key]
    if vol["gb"] == 0:
        return PRICE_PER_UNLIMITED_DAY * dur["days"]
    return dur["price"]


def order_summary(volume_key: str, duration_key: str) -> str:
    vol = VOLUMES[volume_key]
    dur = DURATIONS[duration_key]
    price = get_price(volume_key, duration_key)
    return f"{vol['title']} — {dur['title']} — {price:,} تومان"
