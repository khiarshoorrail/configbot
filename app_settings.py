import logging
import time

import config
import database
import texts

log = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, str]] = {}
CACHE_TTL = 30.0


def invalidate_cache() -> None:
    _CACHE.clear()


async def _get(key: str, fallback: str = "") -> str:
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    val = await database.get_setting(key)
    if val is None or val == "":
        # fallback به env (فقط برای کلیدهای دارای معادل env) و بعد پیش‌فرض
        env_map = {
            "card_number": config.CARD_NUMBER,
            "card_holder": config.CARD_HOLDER,
            "referral_target": str(config.REFERRAL_TARGET),
            "referral_reward_gb": str(config.REFERRAL_REWARD_GB),
            "referral_reward_days": str(config.REFERRAL_REWARD_DAYS),
        }
        val = env_map.get(key, fallback)
    _CACHE[key] = (now, val)
    return val


async def _set(key: str, value: str) -> None:
    await database.set_setting(key, value)


async def _get_int(key: str, fallback: int) -> int:
    raw = await _get(key, str(fallback))
    try:
        return max(int(raw), 0)
    except ValueError:
        return fallback


# --- پرداخت ---
async def card_number() -> str:
    return await _get("card_number")


async def card_holder() -> str:
    return await _get("card_holder", "")


async def save_payment(card_number_: str, card_holder_: str) -> None:
    await _set("card_number", card_number_)
    await _set("card_holder", card_holder_)


# --- رفرال ---
async def referral_target() -> int:
    return await _get_int("referral_target", config.REFERRAL_TARGET or 10)


async def reward_gb() -> int:
    return await _get_int("referral_reward_gb", config.REFERRAL_REWARD_GB or 5)


async def reward_days() -> int:
    return await _get_int("referral_reward_days", config.REFERRAL_REWARD_DAYS or 30)


async def save_referral(target: int, gb: int, days: int) -> None:
    await _set("referral_target", str(max(target, 1)))
    await _set("referral_reward_gb", str(max(gb, 0)))
    await _set("referral_reward_days", str(max(days, 1)))


# --- پشتیبانی و دامنه ---
async def support_contact() -> str:
    return await _get("support_contact", texts.SUPPORT_DEFAULT_CONTACT)


async def panel_base_url() -> str:
    return (await _get("panel_base_url")).rstrip("/")


async def save_support(contact: str, base_url: str) -> None:
    await _set("support_contact", contact)
    await _set("panel_base_url", base_url.rstrip("/"))


# --- متن‌های ربات ---
TEXT_KEYS = ("txt_welcome", "txt_payment_info", "txt_order_confirmed",
             "txt_order_rejected", "txt_referral_info")

_TEXT_FALLBACKS = {
    "txt_welcome": texts.WELCOME,
    "txt_payment_info": texts.PAYMENT_INFO,
    "txt_order_confirmed": texts.ORDER_CONFIRMED,
    "txt_order_rejected": texts.ORDER_REJECTED,
    "txt_referral_info": texts.REFERRAL_INFO,
}


async def text(key: str) -> str:
    if key not in TEXT_KEYS:
        raise KeyError(f"unknown text key: {key}")
    return await _get(key, _TEXT_FALLBACKS[key])


async def all_texts() -> dict[str, str]:
    return {k: await text(k) for k in TEXT_KEYS}


async def save_text(key: str, value: str) -> None:
    if key not in TEXT_KEYS:
        raise KeyError(f"unknown text key: {key}")
    await _set(key, value.strip())
