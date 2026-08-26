import aiosqlite

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    rewarded INTEGER DEFAULT 0,
    joined_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS referrals (
    invited_id INTEGER PRIMARY KEY,
    referrer_id INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    volume_key TEXT NOT NULL,
    duration_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting_receipt',
    sub_url TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    base_url TEXT NOT NULL,
    username TEXT,
    password TEXT,
    token TEXT,
    inbound_id INTEGER,
    sub_base_url TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plans (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    title TEXT NOT NULL,
    gb INTEGER DEFAULT 0,
    days INTEGER DEFAULT 0,
    price INTEGER DEFAULT 0,
    sort INTEGER DEFAULT 0,
    PRIMARY KEY (kind, key)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def upsert_user(user_id: int, username: str | None, full_name: str) -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name",
            (user_id, username, full_name),
        )
        await db.commit()


async def is_new_user(user_id: int) -> bool:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        row = await db.execute_fetchall("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        return not row


async def add_referral(referrer_id: int, invited_id: int) -> bool:
    """ثبت رفرال؛ فقط بار اول هر کاربر شمرده می‌شود."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, invited_id) VALUES (?, ?)",
            (referrer_id, invited_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def referral_count(referrer_id: int) -> int:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        rows = await db.execute_fetchall(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (referrer_id,)
        )
        return rows[0][0]


async def mark_rewarded(user_id: int) -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("UPDATE users SET rewarded=1 WHERE user_id=?", (user_id,))
        await db.commit()


async def is_rewarded(user_id: int) -> bool:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        rows = await db.execute_fetchall("SELECT rewarded FROM users WHERE user_id=?", (user_id,))
        return bool(rows and rows[0][0])


async def create_order(user_id: int, volume_key: str, duration_key: str) -> int:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute(
            "INSERT INTO orders (user_id, volume_key, duration_key, status) VALUES (?, ?, ?, 'awaiting_confirm')",
            (user_id, volume_key, duration_key),
        )
        await db.commit()
        return cur.lastrowid


async def get_order(order_id: int):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall("SELECT * FROM orders WHERE id=?", (order_id,))
        return dict(rows[0]) if rows else None


async def set_order_status(order_id: int, status: str, sub_url: str | None = None) -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("UPDATE orders SET status=?, sub_url=? WHERE id=?", (status, sub_url, order_id))
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall("SELECT * FROM users WHERE user_id=?", (user_id,))
        return dict(rows[0]) if rows else None


async def delivered_orders(user_id: int):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            "SELECT * FROM orders WHERE user_id=? AND status='delivered' ORDER BY id DESC", (user_id,)
        )
        return [dict(r) for r in rows]


# --- پنل‌ها ---

async def list_panels(only_enabled: bool = False):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM panels" + (" WHERE enabled=1" if only_enabled else "") + " ORDER BY id"
        rows = await db.execute_fetchall(q)
        return [dict(r) for r in rows]


async def get_panel(panel_id: int):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall("SELECT * FROM panels WHERE id=?", (panel_id,))
        return dict(rows[0]) if rows else None


async def add_panel(name: str, type_: str, base_url: str, sub_base_url: str,
                    username: str | None = None, password: str | None = None,
                    token: str | None = None, inbound_id: int | None = None) -> int:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cur = await db.execute(
            "INSERT INTO panels (name, type, base_url, username, password, token, inbound_id, sub_base_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, type_, base_url, username, password, token, inbound_id, sub_base_url),
        )
        await db.commit()
        return cur.lastrowid


PANEL_FIELDS = ("name", "type", "base_url", "username", "password",
                "token", "inbound_id", "sub_base_url", "enabled")


async def update_panel(panel_id: int, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in PANEL_FIELDS}
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(f"UPDATE panels SET {cols} WHERE id=?", (*fields.values(), panel_id))
        await db.commit()


async def delete_panel(panel_id: int) -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("DELETE FROM panels WHERE id=?", (panel_id,))
        await db.commit()


async def migrate_env_panel() -> bool:
    """اگر جدول پنل‌ها خالی باشد و env های XUI_* پر باشند، آن را وارد می‌کند."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        rows = await db.execute_fetchall("SELECT COUNT(*) FROM panels")
        if rows[0][0] > 0 or not config.XUI_BASE_URL:
            return False
    await add_panel(
        name="پنل پیش‌فرض",
        type_="xui",
        base_url=config.XUI_BASE_URL,
        username=config.XUI_USERNAME or None,
        password=config.XUI_PASSWORD or None,
        inbound_id=config.XUI_INBOUND_ID,
        sub_base_url=config.XUI_SUB_BASE_URL,
    )
    return True


# --- پلن‌های فروش (قابل ویرایش از وب) ---

async def seed_plans() -> None:
    from plans import SEED_VOLUMES, SEED_DURATIONS, SEED_UNLIMITED_DAY_PRICE

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        rows = await db.execute_fetchall("SELECT COUNT(*) FROM plans")
        if rows[0][0] == 0:
            for i, (key, v) in enumerate(SEED_VOLUMES.items()):
                await db.execute(
                    "INSERT INTO plans (kind, key, title, gb, sort) VALUES ('volume', ?, ?, ?, ?)",
                    (key, v["title"], v["gb"], i),
                )
            for i, (key, d) in enumerate(SEED_DURATIONS.items()):
                await db.execute(
                    "INSERT INTO plans (kind, key, title, days, price, sort) VALUES ('duration', ?, ?, ?, ?, ?)",
                    (key, d["title"], d["days"], d["price"], i),
                )
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('unlimited_day_price', ?)",
                (str(SEED_UNLIMITED_DAY_PRICE),),
            )
            await db.commit()


async def get_plans(kind: str):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            "SELECT * FROM plans WHERE kind=? ORDER BY sort", (kind,)
        )
        return [dict(r) for r in rows]


async def upsert_plan(kind: str, key: str, title: str, gb: int = 0, days: int = 0,
                      price: int = 0, sort: int = 99) -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO plans (kind, key, title, gb, days, price, sort) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(kind, key) DO UPDATE SET title=excluded.title, gb=excluded.gb, "
            "days=excluded.days, price=excluded.price, sort=excluded.sort",
            (kind, key, title, gb, days, price, sort),
        )
        await db.commit()


async def delete_plan(kind: str, key: str) -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("DELETE FROM plans WHERE kind=? AND key=?", (kind, key))
        await db.commit()


async def get_setting(key: str) -> str | None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        rows = await db.execute_fetchall("SELECT value FROM settings WHERE key=?", (key,))
        return rows[0][0] if rows else None


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


# --- کوئری‌های ادمین ---

async def list_users_stats(q: str = ""):
    """کاربران + تعداد رفرال + تعداد سفارش، با جستجو."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = ""
        params: list = []
        if q:
            where = "WHERE u.full_name LIKE ? OR u.username LIKE ? OR CAST(u.user_id AS TEXT) LIKE ?"
            params = [f"%{q}%"] * 3
        rows = await db.execute_fetchall(
            f"""
            SELECT u.*,
              (SELECT COUNT(*) FROM referrals r WHERE r.referrer_id=u.user_id) AS referrals,
              (SELECT COUNT(*) FROM orders o WHERE o.user_id=u.user_id AND o.status='delivered') AS orders_count
            FROM users u {where} ORDER BY u.joined_at DESC LIMIT 500
            """,
            params,
        )
        return [dict(r) for r in rows]


async def list_orders_admin(status: str = ""):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = ""
        params: list = []
        if status:
            where = "WHERE o.status=?"
            params = [status]
        rows = await db.execute_fetchall(
            f"""
            SELECT o.*, u.full_name, u.username
            FROM orders o LEFT JOIN users u ON u.user_id=o.user_id
            {where} ORDER BY o.id DESC LIMIT 300
            """,
            params,
        )
        return [dict(r) for r in rows]


async def stats_overview():
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        users_total = (await db.execute_fetchall("SELECT COUNT(*) FROM users"))[0][0]
        delivered_total = (
            await db.execute_fetchall("SELECT COUNT(*) FROM orders WHERE status='delivered'")
        )[0][0]
        pending = (
            await db.execute_fetchall("SELECT COUNT(*) FROM orders WHERE status='awaiting_confirm'")
        )[0][0]
        sales_today = (
            await db.execute_fetchall(
                "SELECT COUNT(*) FROM orders WHERE status='delivered' AND date(created_at)=date('now','localtime')"
            )
        )[0][0]
        return {
            "users": users_total,
            "delivered": delivered_total,
            "pending": pending,
            "sales_today": sales_today,
        }


async def get_all_user_ids():
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        rows = await db.execute_fetchall("SELECT user_id FROM users")
        return [r[0] for r in rows]


async def latest_orders(limit: int = 5):
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """
            SELECT o.*, u.full_name, u.username FROM orders o
            LEFT JOIN users u ON u.user_id=o.user_id
            ORDER BY o.id DESC LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in rows]
