import logging
import os
import shutil
import sqlite3
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import github_backup
import texts

router = Router()
log = logging.getLogger(__name__)

REQUIRED_TABLES = {"users", "referrals", "orders", "panels"}

ENV_PATH = ".env"


class ImportStates(StatesGroup):
    waiting_file = State()
    confirming = State()


def _admin_only(message: Message) -> bool:
    return message.from_user.id == config.ADMIN_ID


def _validate_db(path: str) -> dict | None:
    """اسکیمای فایل دیتابیس را چک می‌کند؛ تعداد رکوردها یا None برمی‌گرداند."""
    try:
        con = sqlite3.connect(path)
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = REQUIRED_TABLES - tables
            if missing:
                log.warning("import rejected: missing tables %s", missing)
                return None
            return {
                t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in sorted(REQUIRED_TABLES)
            }
        finally:
            con.close()
    except sqlite3.Error as e:
        log.warning("import rejected: bad sqlite: %s", e)
        return None


@router.message(Command("export"))
async def cmd_export(message: Message, bot: Bot) -> None:
    if not _admin_only(message):
        return
    await message.answer("📦 در حال آماده‌سازی فایل پشتیبان...")

    try:
        with open(config.DATABASE_PATH, "rb") as f:
            data = f.read()
    except OSError as e:
        await message.answer(f"⚠️ خواندن دیتابیس ممکن نشد: {e}")
        return

    stamp = time.strftime("%Y%m%d-%H%M%S")
    await bot.send_document(
        message.chat.id,
        BufferedInputFile(data, filename=f"bot-db-{stamp}.db"),
        caption="📦 فایل کامل دیتابیس (کاربران، سفارش‌ها، رفرال‌ها، پنل‌ها)",
    )

    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "rb") as f:
            env_data = f.read()
        await bot.send_document(
            message.chat.id,
            BufferedInputFile(env_data, filename=f"env-{stamp}.txt"),
            caption="🔐 فایل تنظیمات — شامل توکن ربات؛ در جای امن نگه دار.",
        )

    await message.answer(texts.EXPORT_HINT)


@router.message(Command("backup"))
async def cmd_backup(message: Message, state: FSMContext) -> None:
    if not _admin_only(message):
        return
    if not github_backup.backup_enabled():
        await message.answer(
            "⚠️ بکاپ گیت‌هاب فعال نیست.\n"
            "در تنظیمات این دو متغیر را ست کن:\n"
            "<code>GITHUB_BACKUP_REPO=username/repo</code>\n"
            "<code>GITHUB_TOKEN=ghp_...</code>"
        )
        return
    await message.answer("☁️ در حال آپلود پشتیبان روی گیت‌هاب...")
    try:
        url = await github_backup.upload_backup()
        await message.answer(f"✅ پشتیبان آپلود شد:\n{url}")
    except Exception as e:  # noqa: BLE001
        log.error("manual backup failed: %s", e)
        await message.answer(f"⚠️ آپلود ناموفق: {str(e)[:300]}")


@router.message(Command("import"))
async def cmd_import(message: Message, state: FSMContext) -> None:
    if not _admin_only(message):
        return
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_CANCEL, callback_data="import_cancel")
    kb.adjust(1)
    await state.set_state(ImportStates.waiting_file)
    await message.answer(texts.IMPORT_ASK, reply_markup=kb.as_markup())


@router.callback_query(F.data == "import_cancel")
async def cb_import_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("لغو شد.")
    await cb.answer()


@router.message(ImportStates.waiting_file, F.document)
async def receive_db_file(message: Message, state: FSMContext, bot: Bot) -> None:
    doc = message.document
    tmp_path = f"{config.DATABASE_PATH}.import-tmp"

    try:
        f = await bot.download(doc)
        with open(tmp_path, "wb") as out:
            out.write(f.read())
    except Exception:
        log.exception("download failed")
        await message.answer("⚠️ دریافت فایل شکست خورد. دوباره امتحان کن.")
        return

    stats = _validate_db(tmp_path)
    if stats is None:
        os.remove(tmp_path)
        await message.answer(texts.IMPORT_INVALID)
        return

    await state.update_data(tmp_path=tmp_path)
    await state.set_state(ImportStates.confirming)

    counts = "\n".join(f"• {name}: <b>{n}</b>" for name, n in stats.items())
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ بله، جایگزین کن", callback_data="import_ok")
    kb.button(text="❌ انصراف", callback_data="import_cancel")
    kb.adjust(2)
    await message.answer(
        texts.IMPORT_CONFIRM.format(counts=counts),
        reply_markup=kb.as_markup(),
    )


@router.callback_query(ImportStates.confirming, F.data == "import_ok")
async def cb_import_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    tmp_path = data.get("tmp_path")
    if not tmp_path or not os.path.exists(tmp_path):
        await state.clear()
        await cb.message.edit_text("⚠️ فایل موقت پیدا نشد. دوباره /import بزن.")
        await cb.answer()
        return

    backup_path = None
    if os.path.exists(config.DATABASE_PATH):
        backup_path = f"{config.DATABASE_PATH}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(config.DATABASE_PATH, backup_path)

    last_err = None
    for _ in range(10):  # روی ویندوز ممکن است اتصال کوتاهی هنوز باز باشد
        try:
            os.replace(tmp_path, config.DATABASE_PATH)
            last_err = None
            break
        except PermissionError as e:
            last_err = e
            time.sleep(0.2)
    if last_err:
        os.remove(tmp_path)
        await cb.message.edit_text(f"⚠️ جایگزینی ناموفق بود: {last_err}")
        await cb.answer()
        return

    await state.clear()

    stats = _validate_db(config.DATABASE_PATH) or {}
    counts = "\n".join(f"• {name}: <b>{n}</b>" for name, n in sorted(stats.items()))
    await cb.message.edit_text(
        texts.IMPORT_DONE.format(counts=counts, backup=(f"\n💾 نسخه قبلی: <code>{backup_path}</code>" if backup_path else ""))
    )
    log.info("database imported; backup at %s", backup_path)
    await cb.answer()
