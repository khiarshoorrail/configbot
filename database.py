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


async def update_panel(panel_id: int, **fields) -> None:
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
