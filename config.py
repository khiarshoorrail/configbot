import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

CARD_NUMBER = os.getenv("CARD_NUMBER", "")
CARD_HOLDER = os.getenv("CARD_HOLDER", "")

REFERRAL_TARGET = int(os.getenv("REFERRAL_TARGET", "10"))
REFERRAL_REWARD_GB = int(os.getenv("REFERRAL_REWARD_GB", "5"))
REFERRAL_REWARD_DAYS = int(os.getenv("REFERRAL_REWARD_DAYS", "30"))

XUI_BASE_URL = os.getenv("XUI_BASE_URL", "").rstrip("/")
XUI_USERNAME = os.getenv("XUI_USERNAME", "")
XUI_PASSWORD = os.getenv("XUI_PASSWORD", "")
XUI_INBOUND_ID = int(os.getenv("XUI_INBOUND_ID", "1"))
XUI_SUB_BASE_URL = os.getenv("XUI_SUB_BASE_URL", "").rstrip("/")

DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")

# پروکسی SOCKS5 برای اجرا در ایران (مثلاً socks5://127.0.0.1:10808)
PROXY_URL = os.getenv("PROXY_URL", "")

# وب‌پنل ادمین (عمومی — روی Railway هم قابل استفاده؛ رمز اجباری است)
ADMIN_WEB_ENABLED = os.getenv("ADMIN_WEB_ENABLED", "") == "1"
ADMIN_WEB_HOST = os.getenv("ADMIN_WEB_HOST", "0.0.0.0")
ADMIN_WEB_PORT = int(os.getenv("PORT") or os.getenv("ADMIN_WEB_PORT") or "8080")
ADMIN_WEB_PASSWORD = os.getenv("ADMIN_WEB_PASSWORD", "")
