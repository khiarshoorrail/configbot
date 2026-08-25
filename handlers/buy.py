import logging
import secrets

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
import database
import plans
import texts
from keyboards import (
    cancel_menu,
    durations_kb,
    main_menu,
    receipt_actions,
    volumes_kb,
)
from panels_api import AllPanelsFailedError, create_config_on_any_panel, gb_to_bytes

router = Router()
log = logging.getLogger(__name__)


class BuyStates(StatesGroup):
    choosing_volume = State()
    choosing_duration = State()
    waiting_receipt = State()


@router.message(F.text == texts.BTN_BUY)
async def start_buy(message: Message, state: FSMContext) -> None:
    await state.set_state(BuyStates.choosing_volume)
    await message.answer(texts.CHOOSE_VOLUME, reply_markup=volumes_kb(plans.VOLUMES).as_markup())


@router.message(F.text == texts.BTN_CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.MAIN_MENU.strip(), reply_markup=main_menu())


@router.callback_query(BuyStates.choosing_volume, F.data.startswith("vol:"))
async def pick_volume(cb: CallbackQuery, state: FSMContext) -> None:
    volume_key = cb.data.split(":", 1)[1]
    if volume_key not in plans.VOLUMES:
        await cb.answer()
        return
    await state.update_data(volume_key=volume_key)
    await state.set_state(BuyStates.choosing_duration)
    await cb.message.edit_text(texts.CHOOSE_DURATION, reply_markup=durations_kb(plans.DURATIONS).as_markup())
    await cb.answer()


@router.callback_query(BuyStates.choosing_duration, F.data.startswith("dur:"))
async def pick_duration(cb: CallbackQuery, state: FSMContext) -> None:
    duration_key = cb.data.split(":", 1)[1]
    if duration_key not in plans.DURATIONS:
        await cb.answer()
        return
    data = await state.get_data()
    volume_key = data["volume_key"]

    price = plans.get_price(volume_key, duration_key)
    summary = plans.order_summary(volume_key, duration_key)

    order_id = await database.create_order(cb.from_user.id, volume_key, duration_key)
    code = f"ORD-{order_id:04d}"
    await state.update_data(order_id=order_id, order_code=code)

    await cb.message.edit_text(
        texts.PAYMENT_INFO.format(
            summary=summary, price=price, card=config.CARD_NUMBER, holder=config.CARD_HOLDER
        )
        + "\n\n"
        + texts.ORDER_CODE.format(code=code),
    )
    await state.set_state(BuyStates.waiting_receipt)
    await cb.answer()


@router.message(StateFilter(BuyStates.waiting_receipt), F.photo | F.text)
async def receive_receipt(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        await state.clear()
        await message.answer(texts.MAIN_MENU.strip(), reply_markup=main_menu())
        return

    from handlers.chat import build_user_header

    header = await build_user_header(bot, message.from_user)
    header += f"\n🧾 کد سفارش: {data.get('order_code')}\n\n"

    try:
        if message.photo:
            await bot.send_photo(
                config.ADMIN_ID, message.photo[-1].file_id, caption=header[:1024],
                reply_markup=receipt_actions(order_id).as_markup(),
            )
        else:
            await bot.send_message(
                config.ADMIN_ID, header + (message.text or ""), reply_markup=receipt_actions(order_id).as_markup(),
                parse_mode="HTML",
            )
    except Exception:
        log.exception("failed to relay receipt for order %s", order_id)
        await message.answer("⚠️ خطا در ارسال به پشتیبانی. چند لحظه بعد دوباره امتحان کن.")
        return

    await message.answer(texts.RECEIPT_RECEIVED)
    await state.clear()
    await message.answer(texts.MAIN_MENU.strip(), reply_markup=main_menu())


@router.callback_query(F.data.startswith("approve:"))
async def approve_order(cb: CallbackQuery, bot: Bot) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer("دسترسی نداری.", show_alert=True)
        return
    order_id = int(cb.data.split(":", 1)[1])
    order = await database.get_order(order_id)
    if not order or order["status"] not in ("awaiting_confirm",):
        await cb.answer("این سفارش قبلاً پردازش شده.", show_alert=True)
        return

    vol = plans.VOLUMES[order["volume_key"]]
    dur = plans.DURATIONS[order["duration_key"]]

    try:
        sub_url, panel_name = await create_config_on_any_panel(gb_to_bytes(vol["gb"]), dur["months"] * 30)
    except AllPanelsFailedError as e:
        log.error("all panels failed for order %s: %s", order_id, e)
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("هیچ پنلی در دسترس نبود. جزئیات در لاگ.", show_alert=True)
        try:
            await bot.send_message(config.ADMIN_ID, f"⚠️ ساخت کانفیگ سفارش {order_id} روی همه پنل‌ها شکست خورد:\n{e}")
        except Exception:
            pass
        return
    except Exception as e:  # noqa: BLE001
        log.error("create_config failed for order %s: %s", order_id, e)
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer(f"خطا در ساخت کانفیگ: {e}", show_alert=True)
        return

    await database.set_order_status(order_id, "delivered", sub_url)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("تأیید شد ✅")

    try:
        await bot.send_message(order["user_id"], texts.ORDER_CONFIRMED.format(sub_url=sub_url))
    except Exception:
        log.exception("could not deliver to user %s", order["user_id"])


@router.callback_query(F.data.startswith("reject:"))
async def reject_order(cb: CallbackQuery, bot: Bot) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer("دسترسی نداری.", show_alert=True)
        return
    order_id = int(cb.data.split(":", 1)[1])
    order = await database.get_order(order_id)
    if not order or order["status"] != "awaiting_confirm":
        await cb.answer("این سفارش قبلاً پردازش شده.", show_alert=True)
        return
    await database.set_order_status(order_id, "rejected")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("رد شد.")
    try:
        await bot.send_message(order["user_id"], texts.ORDER_REJECTED)
    except Exception:
        log.exception("could not notify user %s", order["user_id"])
