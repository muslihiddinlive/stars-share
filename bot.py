import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    LabeledPrice,
    PreCheckoutQuery,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode

import storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("stars-share")

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPERADMIN_ID = int(os.environ["SUPERADMIN_ID"])
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID")  # ixtiyoriy: shaffoflik uchun ochiq kanal

# Ma'lumot (balans) saqlanadigan supergroup - faqat bot va superadmin a'zo bo'lgan,
# botga admin huquqi (pin + fayl yuborish) berilgan yopiq guruh bo'lishi kerak.
STORAGE_CHAT_ID = int(os.environ["STORAGE_CHAT_ID"])
STORAGE_TOPIC_ID = int(os.environ["STORAGE_TOPIC_ID"]) if os.environ.get("STORAGE_TOPIC_ID") else None

FEE = 1
TOPUP_PRESETS = [10, 25, 50, 100]

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def fmt_user(user_id: int, username: str | None) -> str:
    return f"@{username}" if username else f"id:{user_id}"


async def announce(text: str):
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(int(LOG_CHANNEL_ID), text)
        except Exception as e:
            log.warning("LOG_CHANNEL_ID'ga yuborib bo'lmadi: %s", e)


async def notify_admin(text: str):
    try:
        await bot.send_message(SUPERADMIN_ID, text)
    except Exception as e:
        log.warning("Adminga xabar yuborib bo'lmadi: %s", e)


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💼 Balans", callback_data="menu:balance"),
         InlineKeyboardButton(text="💰 To'ldirish", callback_data="menu:topup")],
        [InlineKeyboardButton(text="📤 Yuborish", callback_data="menu:send"),
         InlineKeyboardButton(text="❓ Yordam", callback_data="menu:help")],
    ])


def topup_kb() -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text=f"{a} ⭐️", callback_data=f"topup:{a}") for a in TOPUP_PRESETS]
    return InlineKeyboardMarkup(inline_keyboard=[row, [InlineKeyboardButton(text="⬅️ Menyu", callback_data="menu:home")]])


def confirm_kb(sender_id: int, target_id: int, amount: int) -> InlineKeyboardMarkup:
    payload = f"{sender_id}:{target_id}:{amount}"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"cf:{payload}"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cx"),
    ]])


HELP_TEXT = (
    "⭐️ <b>Stars Share</b> ga xush kelibsiz!\n\n"
    "/topup &lt;miqdor&gt; — hisobingizni to'ldirish\n"
    "/balance — balansingizni ko'rish\n"
    "/send &lt;@username yoki ID&gt; &lt;miqdor&gt; — stars o'tkazish\n\n"
    "❗️ Qabul qiluvchi avval botga /start bosgan va kamida bir marta /topup qilgan bo'lishi kerak.\n"
    "Har bir o'tkazmadan 1 ⭐️ tizim ulushi olinadi — bu haqda hamma xabardor bo'ladi."
)


@dp.message(CommandStart())
async def start_handler(message: Message):
    async with storage.state_lock:
        storage.upsert_user(message.from_user.id, message.from_user.username)
        await storage._persist(bot, STORAGE_CHAT_ID, STORAGE_TOPIC_ID)
    await message.answer(HELP_TEXT, reply_markup=main_menu_kb())


@dp.callback_query(F.data == "menu:home")
async def menu_home(cb: CallbackQuery):
    await cb.message.edit_text(HELP_TEXT, reply_markup=main_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "menu:help")
async def menu_help(cb: CallbackQuery):
    await cb.message.edit_text(HELP_TEXT, reply_markup=main_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "menu:balance")
async def menu_balance(cb: CallbackQuery):
    user = storage.get_user(cb.from_user.id) or {"balance": 0}
    await cb.message.edit_text(f"💼 Balansingiz: <b>{user['balance']} ⭐️</b>", reply_markup=main_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "menu:topup")
async def menu_topup(cb: CallbackQuery):
    await cb.message.edit_text(
        "💰 Qancha stars bilan to'ldirmoqchisiz?\nBoshqa miqdor: <code>/topup 75</code>",
        reply_markup=topup_kb(),
    )
    await cb.answer()


@dp.callback_query(F.data == "menu:send")
async def menu_send(cb: CallbackQuery):
    await cb.message.edit_text(
        "📤 <code>/send @username 10</code> yoki <code>/send 123456789 10</code>\n"
        "Yuborishdan oldin tasdiqlash so'raladi.",
        reply_markup=main_menu_kb(),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("topup:"))
async def topup_preset(cb: CallbackQuery):
    await send_invoice_to(cb.from_user.id, int(cb.data.split(":")[1]))
    await cb.answer()


async def send_invoice_to(user_id: int, amount: int):
    prices = [LabeledPrice(label="Stars Share balans to'ldirish", amount=amount)]
    await bot.send_invoice(
        chat_id=user_id, title="Balansni to'ldirish",
        description=f"{amount} ⭐️ hisobingizga qo'shiladi",
        payload=f"topup:{user_id}:{amount}", currency="XTR", prices=prices,
    )


@dp.message(Command("topup"))
async def topup_handler(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
        await message.answer("Foydalanish: /topup 50")
        return
    async with storage.state_lock:
        storage.upsert_user(message.from_user.id, message.from_user.username)
        await storage._persist(bot, STORAGE_CHAT_ID, STORAGE_TOPIC_ID)
    await send_invoice_to(message.from_user.id, int(parts[1]))


@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payload = message.successful_payment.invoice_payload
    charge_id = message.successful_payment.telegram_payment_charge_id
    try:
        _, user_id_str, amount_str = payload.split(":")
        user_id, amount = int(user_id_str), int(amount_str)
    except Exception:
        log.error("Noto'g'ri payload: %s", payload)
        await notify_admin(f"⚠️ Noto'g'ri to'lov payload: {payload!r}")
        return

    is_new = await storage.credit_from_payment(
        bot, STORAGE_CHAT_ID, STORAGE_TOPIC_ID, user_id, amount, charge_id
    )
    if not is_new:
        log.info("Takroriy to'lov e'tiborga olinmadi: charge_id=%s", charge_id)
        return

    user = storage.get_user(user_id)
    await message.answer(f"✅ To'lov qabul qilindi: {amount} ⭐️\nJoriy balans: {user['balance']} ⭐️", reply_markup=main_menu_kb())
    await announce(f"💰 {fmt_user(user_id, message.from_user.username)} hisobini {amount} ⭐️ ga to'ldirdi.")


@dp.message(Command("balance"))
async def balance_handler(message: Message):
    async with storage.state_lock:
        storage.upsert_user(message.from_user.id, message.from_user.username)
        await storage._persist(bot, STORAGE_CHAT_ID, STORAGE_TOPIC_ID)
    user = storage.get_user(message.from_user.id)
    await message.answer(f"💼 Balansingiz: <b>{user['balance']} ⭐️</b>", reply_markup=main_menu_kb())


@dp.message(Command("send"))
async def send_handler(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Foydalanish: /send @username 10")
        return
    target_raw, amount_raw = parts[1], parts[2]
    if not amount_raw.isdigit() or int(amount_raw) <= FEE:
        await message.answer(f"Miqdor {FEE} dan katta butun son bo'lishi kerak.")
        return
    amount = int(amount_raw)
    sender_id = message.from_user.id

    async with storage.state_lock:
        storage.upsert_user(sender_id, message.from_user.username)
        await storage._persist(bot, STORAGE_CHAT_ID, STORAGE_TOPIC_ID)

    if target_raw.startswith("@"):
        target = storage.get_user_by_username(target_raw)
    elif target_raw.isdigit():
        tid = int(target_raw)
        u = storage.get_user(tid)
        target = {"user_id": tid, **u} if u else None
    else:
        target = None

    if not target:
        await message.answer("❌ Bu foydalanuvchi topilmadi. U avval botga /start bosishi kerak.")
        return
    if target["user_id"] == sender_id:
        await message.answer("❌ O'zingizga stars o'tkaza olmaysiz.")
        return
    if not target["has_paid"]:
        await message.answer("❌ Qabul qiluvchi hali /topup qilmagan.")
        return

    sender = storage.get_user(sender_id)
    if sender["balance"] < amount:
        await message.answer("❌ Balansingiz yetarli emas.")
        return

    net_amount = amount - FEE
    target_tag = fmt_user(target["user_id"], target["username"])
    await message.answer(
        f"📤 <b>Tasdiqlang:</b>\n{amount} ⭐️ dan {net_amount} ⭐️ {target_tag} ga yuboriladi.\n"
        f"🔹 {FEE} ⭐️ tizim ulushi.\n\nDavom etasizmi?",
        reply_markup=confirm_kb(sender_id, target["user_id"], amount),
    )


@dp.callback_query(F.data == "cx")
async def cancel_send(cb: CallbackQuery):
    await cb.message.edit_text("❌ Bekor qilindi.")
    await cb.answer()


@dp.callback_query(F.data.startswith("cf:"))
async def confirm_send(cb: CallbackQuery):
    try:
        _, payload = cb.data.split(":", 1)
        sender_id, target_id, amount = (int(x) for x in payload.split(":"))
    except Exception:
        await cb.answer("Xatolik: noto'g'ri ma'lumot.", show_alert=True)
        return
    if cb.from_user.id != sender_id:
        await cb.answer("Bu tugma sizga tegishli emas.", show_alert=True)
        return

    await cb.answer("Ishlanmoqda...")
    result = await storage.transfer(
        bot, STORAGE_CHAT_ID, STORAGE_TOPIC_ID, sender_id, target_id, amount, FEE, SUPERADMIN_ID
    )

    if not result["ok"]:
        if result["reason"] == "insufficient_balance":
            await cb.message.edit_text("❌ Balansingiz yetarli emas.")
        else:
            await cb.message.edit_text(
                "⚠️ Texnik xatolik. Stars'ingiz o'zgarmadi, joyida qoldi. Superadminga xabar yuborildi."
            )
            await notify_admin(
                f"🚨 O'tkazma amalga oshmadi\nKimdan: id:{sender_id}\nKimga: id:{target_id}\n"
                f"Miqdor: {amount} ⭐️\nXato: {result.get('error')}\n"
                f"Stars asl egasida (id:{sender_id}) qoldi."
            )
        return

    net_amount = amount - FEE
    sender = storage.get_user(sender_id)
    target = storage.get_user(target_id)
    sender_tag = fmt_user(sender_id, cb.from_user.username)
    target_tag = fmt_user(target_id, target["username"])

    await cb.message.edit_text(
        f"✅ {amount} ⭐️ dan {net_amount} ⭐️ {target_tag} ga o'tkazildi.\n"
        f"Yangi balansingiz: {sender['balance']} ⭐️"
    )
    try:
        await bot.send_message(
            target_id,
            f"🎉 Sizga {sender_tag} tomonidan {net_amount} ⭐️ o'tkazildi!\nYangi balansingiz: {target['balance']} ⭐️",
        )
    except Exception as e:
        log.warning("Qabul qiluvchiga xabar yuborilmadi: %s", e)

    await announce(
        f"🔁 Yangi o'tkazma\nKimdan: {sender_tag}\nKimga: {target_tag}\n"
        f"Miqdor: {amount} ⭐️ (foydalanuvchiga {net_amount} ⭐️, tizimga {FEE} ⭐️)"
    )


@dp.message(Command("stats"))
async def stats_handler(message: Message):
    if message.from_user.id != SUPERADMIN_ID:
        await message.answer("❌ Bu buyruq faqat superadmin uchun.")
        return
    s = storage.stats()
    await message.answer(
        f"📊 Statistika\nFoydalanuvchilar: {s['users']}\nTo'lov qilganlar: {s['paid_users']}\n"
        f"Jami hajm: {s['total_volume']} ⭐️\nJami tizim ulushi: {s['total_fees']} ⭐️"
    )


async def main():
    await storage.load_state(bot, STORAGE_CHAT_ID, STORAGE_TOPIC_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
