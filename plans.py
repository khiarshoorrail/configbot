# پلن‌های فروش: کلید = (حجم گیگ، مدت ماه)
# 0-گیگ یعنی نامحدود. قیمت‌ها تومان هستند؛ اینجا راحت تغییر بده.

VOLUMES = {
    "vol_10": {"title": "۱۰ گیگابایت", "gb": 10},
    "vol_30": {"title": "۳۰ گیگابایت", "gb": 30},
    "vol_50": {"title": "۵۰ گیگابایت", "gb": 50},
    "vol_unlimited": {"title": "نامحدود", "gb": 0},
}

DURATIONS = {
    "dur_1": {"title": "۱ ماهه", "months": 1, "price": 90000},
    "dur_2": {"title": "۲ ماهه", "months": 2, "price": 160000},
    "dur_3": {"title": "۳ ماهه", "months": 3, "price": 210000},
}

PRICE_PER_UNLIMITED_MONTH = 150000


def get_price(volume_key: str, duration_key: str) -> int:
    vol = VOLUMES[volume_key]
    dur = DURATIONS[duration_key]
    if vol["gb"] == 0:
        return PRICE_PER_UNLIMITED_MONTH * dur["months"]
    return dur["price"]


def order_summary(volume_key: str, duration_key: str) -> str:
    vol = VOLUMES[volume_key]
    dur = DURATIONS[duration_key]
    price = get_price(volume_key, duration_key)
    return f"{vol['title']} — {dur['title']} — {price:,} تومان"
