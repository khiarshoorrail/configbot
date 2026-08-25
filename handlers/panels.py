import logging
from urllib.parse import urlparse

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database
import texts
from panels_api import PanelError, test_panel

router = Router()
log = logging.getLogger(__name__)

TYPE_LABELS = {"xui": "3x-ui", "marzban": "Marzban"}


class AddPanelStates(StatesGroup):
    choosing_type = State()
    asking_name = State()
    asking_base_url = State()
    asking_username = State()
    asking_password = State()
    asking_token = State()
    asking_inbound = State()
    asking_sub_url = State()


class EditPanelStates(StatesGroup):
    asking_value = State()


def admin_only(message: Message) -> bool:
    return message.from_user.id == config.ADMIN_ID


def panels_list_kb(panels: list) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for p in panels:
        status = "🟢" if p["enabled"] else "🔴"
        kb.button(
            text=texts.PANEL_ITEM.format(status=status, name=p["name"], type_label=TYPE_LABELS.get(p["type"], p["type"])),
            callback_data=f"panel:{p['id']}",
        )
    kb.adjust(1)
    kb.button(text="➕ افزودن پنل", callback_data="panel_add")
    kb.button(text="🔄 به‌روزرسانی", callback_data="panels")
    kb.adjust(1)
    return kb


def panel_details_kb(panel_id: int, enabled: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=("🚫 غیرفعال کن" if enabled else "✅ فعال کن"), callback_data=f"ptoggle:{panel_id}")
    kb.button(text="🔌 تست اتصال", callback_data=f"ptest:{panel_id}")
    kb.button(text="🗑 حذف", callback_data=f"pdel:{panel_id}")
    kb.adjust(2, 1)
    kb.button(text="🔙 بازگشت به لیست", callback_data="panels")
    kb.adjust(1)
    return kb


async def show_panels(target: Message | CallbackQuery) -> None:
    panels = await database.list_panels()
    if not panels:
        text = texts.PANELS_LIST_EMPTY
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ افزودن پنل", callback_data="panel_add")
        kb.adjust(1)
    else:
        text = texts.PANELS_LIST_HEADER
        kb = panels_list_kb(panels)

    send = target.answer if isinstance(target, Message) else target.message.edit_text
    await send(text, reply_markup=kb.as_markup())


@router.message(Command("panels"))
async def cmd_panels(message: Message, state: FSMContext) -> None:
    if not admin_only(message):
        return
    await state.clear()
    await show_panels(message)


@router.message(F.text == texts.BTN_PANELS)
async def btn_panels(message: Message, state: FSMContext) -> None:
    if not admin_only(message):
        await message.answer(texts.ADMIN_ONLY)
        return
    await state.clear()
    await show_panels(message)


@router.callback_query(F.data == "panels")
async def cb_panels(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer(texts.ADMIN_ONLY, show_alert=True)
        return
    await state.clear()
    await cb.message.delete()
    panels = await database.list_panels()
    if not panels:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ افزودن پنل", callback_data="panel_add")
        kb.adjust(1)
        await cb.message.answer(texts.PANELS_LIST_EMPTY, reply_markup=kb.as_markup())
    else:
        await cb.message.answer(texts.PANELS_LIST_HEADER, reply_markup=panels_list_kb(panels).as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("panel:"))
async def cb_panel_details(cb: CallbackQuery) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer()
        return
    panel_id = int(cb.data.split(":", 1)[1])
    p = await database.get_panel(panel_id)
    if not p:
        await cb.answer("پنل پیدا نشد.", show_alert=True)
        return
    await cb.message.edit_text(
        texts.PANEL_DETAILS.format(
            name=p["name"],
            type=TYPE_LABELS.get(p["type"], p["type"]),
            base_url=p["base_url"],
            username=(f"@{p['username']}" if p.get("username") else "—"),
            inbound=(str(p["inbound_id"]) if p.get("inbound_id") else "—"),
            sub_url=p["sub_base_url"],
            enabled=("🟢 فعال" if p["enabled"] else "🔴 غیرفعال"),
        ),
        reply_markup=panel_details_kb(p["id"], bool(p["enabled"])),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("ptoggle:"))
async def cb_panel_toggle(cb: CallbackQuery) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer()
        return
    panel_id = int(cb.data.split(":", 1)[1])
    p = await database.get_panel(panel_id)
    if not p:
        await cb.answer("پنل پیدا نشد.", show_alert=True)
        return
    await database.update_panel(panel_id, enabled=0 if p["enabled"] else 1)
    await cb_panel_details(cb)


@router.callback_query(F.data.startswith("ptest:"))
async def cb_panel_test(cb: CallbackQuery) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer()
        return
    panel_id = int(cb.data.split(":", 1)[1])
    p = await database.get_panel(panel_id)
    if not p:
        await cb.answer("پنل پیدا نشد.", show_alert=True)
        return
    await cb.answer(texts.TESTING_CONNECTION)
    try:
        detail = await test_panel(p)
        await cb.message.answer(texts.PANEL_TEST_OK.format(detail=detail))
    except (PanelError, Exception) as e:  # noqa: BLE001
        log.error("panel test failed (%s): %s", p["name"], e)
        await cb.message.answer(texts.PANEL_TEST_FAIL.format(error=str(e)[:400]))


@router.callback_query(F.data.startswith("pdel:"))
async def cb_panel_delete(cb: CallbackQuery) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer()
        return
    panel_id = int(cb.data.split(":", 1)[1])
    p = await database.get_panel(panel_id)
    if not p:
        await cb.answer("پنل پیدا نشد.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 بله، حذف کن", callback_data=f"pdelok:{panel_id}")
    kb.button(text="❌ انصراف", callback_data=f"panel:{panel_id}")
    kb.adjust(2)
    await cb.message.edit_text(texts.PANEL_DELETE_CONFIRM.format(name=p["name"]), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("pdelok:"))
async def cb_panel_delete_ok(cb: CallbackQuery) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer()
        return
    panel_id = int(cb.data.split(":", 1)[1])
    await database.delete_panel(panel_id)
    await cb.message.delete()
    panels = await database.list_panels()
    await cb.message.answer(
        texts.PANEL_DELETED + "\n\n" + (texts.PANELS_LIST_HEADER if panels else texts.PANELS_LIST_EMPTY),
        reply_markup=(panels_list_kb(panels).as_markup() if panels else None),
    )
    await cb.answer()


# --- افزودن پنل (FSM) ---
@router.callback_query(F.data == "panel_add")
async def cb_panel_add(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer()
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="3x-ui", callback_data="ptype:xui")
    kb.button(text="Marzban", callback_data="ptype:marzban")
    kb.adjust(2)
    kb.button(text="❌ انصراف", callback_data="panels")
    kb.adjust(1)
    await cb.message.edit_text(texts.ADD_CHOOSE_TYPE, reply_markup=kb.as_markup())
    await state.set_state(AddPanelStates.choosing_type)
    await cb.answer()


@router.callback_query(AddPanelStates.choosing_type, F.data.startswith("ptype:"))
async def cb_pick_type(cb: CallbackQuery, state: FSMContext) -> None:
    type_ = cb.data.split(":", 1)[1]
    await state.update_data(type=type_)
    await state.set_state(AddPanelStates.asking_name)
    await cb.message.edit_text(texts.ASK_PANEL_NAME)
    await cb.answer()


@router.message(AddPanelStates.asking_name, F.text)
async def ask_base_url(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(AddPanelStates.asking_base_url)
    await message.answer(texts.ASK_BASE_URL)


def _normalize_url(url: str) -> str | None:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    return url.rstrip("/")


@router.message(AddPanelStates.asking_base_url, F.text)
async def ask_credentials(message: Message, state: FSMContext) -> None:
    base_url = _normalize_url(message.text or "")
    if not base_url:
        await message.answer("⚠️ آدرس معتبر نیست. دوباره بفرست (مثلاً https://panel.example.com):")
        return
    await state.update_data(base_url=base_url)
    data = await state.get_data()
    if data["type"] == "marzban":
        await state.set_state(AddPanelStates.asking_username)
        await message.answer(texts.ASK_USERNAME)
    else:
        await state.set_state(AddPanelStates.asking_username)
        await message.answer(texts.ASK_USERNAME)


@router.message(AddPanelStates.asking_username, F.text)
async def ask_password(message: Message, state: FSMContext) -> None:
    await state.update_data(username=message.text.strip())
    await state.set_state(AddPanelStates.asking_password)
    await message.answer(texts.ASK_PASSWORD)


@router.message(AddPanelStates.asking_password, F.text)
async def after_password(message: Message, state: FSMContext) -> None:
    await state.update_data(password=message.text.strip())
    data = await state.get_data()
    if data["type"] == "marzban":
        await state.set_state(AddPanelStates.asking_sub_url)
        await message.answer(texts.ASK_SUB_URL)
    else:
        await state.set_state(AddPanelStates.asking_inbound)
        await message.answer(texts.ASK_INBOUND)


@router.message(AddPanelStates.asking_inbound, F.text)
async def ask_inbound(message: Message, state: FSMContext) -> None:
    try:
        inbound = int((message.text or "").strip())
    except ValueError:
        await message.answer("⚠️ فقط عدد بفرست (مثلاً 1):")
        return
    await state.update_data(inbound_id=inbound)
    await state.set_state(AddPanelStates.asking_sub_url)
    await message.answer(texts.ASK_SUB_URL)


@router.message(AddPanelStates.asking_sub_url, F.text)
async def finish_add(message: Message, state: FSMContext, bot: Bot) -> None:
    sub_url = _normalize_url(message.text or "")
    if not sub_url:
        await message.answer("⚠️ آدرس معتبر نیست. دوباره بفرست:")
        return

    data = await state.get_data()
    panel_id = await database.add_panel(
        name=data["name"],
        type_=data["type"],
        base_url=data["base_url"],
        sub_base_url=sub_url,
        username=data.get("username"),
        password=data.get("password"),
        inbound_id=data.get("inbound_id"),
    )
    panel = await database.get_panel(panel_id)
    await state.clear()

    await message.answer(texts.PANEL_ADDED.format(name=data["name"]))
    await message.answer("🔌 در حال تست اتصال...")
    try:
        detail = await test_panel(panel)
        await message.answer(texts.PANEL_TEST_OK.format(detail=detail))
    except (PanelError, Exception) as e:  # noqa: BLE001
        log.error("new panel test failed (%s): %s", panel["name"], e)
        await message.answer(
            texts.PANEL_TEST_FAIL.format(error=str(e)[:400])
            + "\n\nپنل ذخیره شد؛ می‌توانی بعداً از لیست پنل‌ها مشخصاتش را ویرایش یا دوباره تست کنی."
        )
