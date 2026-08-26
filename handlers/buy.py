import logging
import secrets

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import app_settings
import config
import database
import plans
import services
import texts
from keyboards import (
    cancel_menu,
    durations_kb,
    main_menu_for,
    receipt_actions,
    volumes_kb,
)

router = Router()
log = logging.getLogger(__name__)


class BuyStates(StatesGroup):
    choosing_volume = State()
    choosing_duration = State()
    waiting_receipt = State()


@router.message(F.text == texts.BTN_BUY)
async def start_buy(message: Message, state: FSMContext) -> None:
    await state.set_state(BuyStates.choosing_volume)
    await message.answer(texts.CHOOSE_VOLUME, reply_markup=volumes_kb(await plans.get_volumes()).as_markup())


@router.message(F.text == texts.BTN_CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.MAIN_MENU.strip(), reply_markup=main_menu_for(message.from_user.id))


@router.callback_query(BuyStates.choosing_volume, F.data.startswith("vol:"))
async def pick_volume(cb: CallbackQuery, state: FSMContext) -> None:
    volume_key = cb.data.split(":", 1)[1]
    volumes = await plans.get_volumes()
    if volume_key not in volumes:
        await cb.answer()
        return
    await state.update_data(volume_key=volume_key)
    await state.set_state(BuyStates.choosing_duration)
    await cb.message.edit_text(
        texts.CHOOSE_DURATION, reply_markup=durations_kb(await plans.get_durations()).as_markup()
    )
    await cb.answer()


@router.callback_query(BuyStates.choosing_duration, F.data.startswith("dur:"))
async def pick_duration(cb: CallbackQuery, state: FSMContext) -> None:
    duration_key = cb.data.split(":", 1)[1]
    durations = await plans.get_durations()
    if duration_key not in durations:
        await cb.answer()
        return
    data = await state.get_data()
    volume_key = data["volume_key"]

    price = await plans.get_price(volume_key, duration_key)
    summary = await plans.order_summary(volume_key, duration_key)

    order_id = await database.create_order(cb.from_user.id, volume_key, duration_key)
    code = f"ORD-{order_id:04d}"
    await state.update_data(order_id=order_id, order_code=code)

    payment_template = await app_settings.text("txt_payment_info")
    await cb.message.edit_text(
        payment_template.format(
            summary=summary, price=price,
            card=await app_settings.card_number(),
            holder=await app_settings.card_holder(),
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
        await message.answer(texts.MAIN_MENU.strip(), reply_markup=main_menu_for(message.from_user.id))
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
    await message.answer(texts.MAIN_MENU.strip(), reply_markup=main_menu_for(message.from_user.id))


@router.callback_query(F.data.startswith("approve:"))
async def approve_order(cb: CallbackQuery, bot: Bot) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer("دسترسی نداری.", show_alert=True)
        return
    order_id = int(cb.data.split(":", 1)[1])
    result = await services.approve_order_core(bot, order_id)

    if result == "already":
        await cb.answer("این سفارش قبلاً پردازش شده.", show_alert=True)
        return
    if result.startswith("failed:"):
        err = result[7:]
        await cb.message.edit_reply_markup(reply_markup=None)
        if "هیچ پنلی" in err:
            try:
                await bot.send_message(config.ADMIN_ID, f"⚠️ ساخت کانفیگ سفارش {order_id} شکست خورد:\n{err}")
            except Exception:
                pass
        await cb.answer(f"خطا در ساخت کانفیگ: {err}", show_alert=True)
        return

    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("تأیید شد ✅")


@router.callback_query(F.data.startswith("reject:"))
async def reject_order(cb: CallbackQuery, bot: Bot) -> None:
    if cb.from_user.id != config.ADMIN_ID:
        await cb.answer("دسترسی نداری.", show_alert=True)
        return
    order_id = int(cb.data.split(":", 1)[1])
    result = await services.reject_order_core(bot, order_id)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("رد شد." if result == "ok" else "این سفارش قبلاً پردازش شده.")
