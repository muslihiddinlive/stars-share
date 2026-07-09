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
)
from aiogram.enums import ParseMode

import db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("stars-share")

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPERADMIN_ID = int(os.environ["SUPERADMIN_ID"])
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID")  # optional: public transparency channel
DB_PATH = os.environ.get("DB_PATH", "stars_share.db")

FEE = 1  # 1 star per transfer goes to superadmin

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def fmt_user(user_id: int, username: str | None) -> str:
    return f"@{username}" if username else f"id:{user_id}"


async def announce(text: str):
    """Send a transparency message to the public log channel, if configured."""
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(int(LOG_CHANNEL_ID), text)
        except Exception as e:
            log.warning("Could not post to LOG_CHANNEL_ID: %s", e)


@dp.message(CommandStart())
async def start_handler(message: Message):
    db.upsert_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "⭐️ <b>Stars Share</b> ga xush kelibsiz!\n\n"
        "Bu bot orqali Telegram Stars'ni boshqa foydalanuvchilarga o'tkazishingiz mumkin.\n\n"
        "Buyruqlar:\n"
        "/topup &lt;miqdor&gt; — hisobingizni Stars bilan to'ldirish\n"
        "/balance — balansingizni ko'rish\n"
        "/send &lt;@username yoki ID&gt; &lt;miqdor&gt; — stars o'tkazish\n\n"
        "❗️ Qabul qiluvchi ham avval botga /start bosgan va kamida bir marta "
        "/topup qilgan bo'lishi kerak.\n"
        "Har bir o'tkazmadan 1 ⭐️ tizim (superadmin) foyda ulushi sifatida olinadi — "
        "bu haqda hamma xabardor bo'ladi, 100% shaffof."
    )


@dp.message(Command("topup"))
async def topup_handler(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
        await message.answer("Foydalanish: /topup 50  (50 ta stars bilan hisobni to'ldirish)")
        return

    amount = int(parts[1])
    db.upsert_user(message.from_user.id, message.from_user.username)

    prices = [LabeledPrice(label="Stars Share balans to'ldirish", amount=amount)]
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Balansni to'ldirish",
        description=f"{amount} ⭐️ hisobingizga qo'shiladi",
        payload=f"topup:{message.from_user.id}:{amount}",
        currency="XTR",  # Telegram Stars
        prices=prices,
    )


@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payload = message.successful_payment.invoice_payload
    try:
        _, user_id_str, amount_str = payload.split(":")
        user_id = int(user_id_str)
        amount = int(amount_str)
    except Exception:
        log.error("Bad payload: %s", payload)
        return

    db.credit_balance(user_id, amount, mark_paid=True)
    user = db.get_user(user_id)
    await message.answer(
        f"✅ To'lov qabul qilindi: {amount} ⭐️\n"
        f"Joriy balans: {user['balance']} ⭐️"
    )
    await announce(
        f"💰 {fmt_user(user_id, message.from_user.username)} hisobini {amount} ⭐️ ga to'ldirdi."
    )


@dp.message(Command("balance"))
async def balance_handler(message: Message):
    db.upsert_user(message.from_user.id, message.from_user.username)
    user = db.get_user(message.from_user.id)
    await message.answer(f"💼 Balansingiz: <b>{user['balance']} ⭐️</b>")


@dp.message(Command("send"))
async def send_handler(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Foydalanish: /send @username 10  yoki  /send 123456789 10")
        return

    target_raw, amount_raw = parts[1], parts[2]
    if not amount_raw.isdigit() or int(amount_raw) <= FEE:
        await message.answer(f"Miqdor {FEE} dan katta butun son bo'lishi kerak.")
        return
    amount = int(amount_raw)

    sender_id = message.from_user.id
    db.upsert_user(sender_id, message.from_user.username)

    # Resolve target
    if target_raw.startswith("@"):
        target = db.get_user_by_username(target_raw)
    elif target_raw.isdigit():
        target = db.get_user(int(target_raw))
    else:
        target = None

    if not target:
        await message.answer(
            "❌ Bu foydalanuvchi topilmadi. U avval botga /start bosishi kerak."
        )
        return

    if target["user_id"] == sender_id:
        await message.answer("❌ O'zingizga stars o'tkaza olmaysiz.")
        return

    if not target["has_paid"]:
        await message.answer(
            "❌ Qabul qiluvchi hali stars bosmagan (hisobini to'ldirmagan). "
            "U avval /topup qilishi kerak."
        )
        return

    if not db.debit_balance(sender_id, amount):
        await message.answer("❌ Balansingiz yetarli emas.")
        return

    net_amount = amount - FEE
    db.credit_balance(target["user_id"], net_amount)
    db.credit_balance(SUPERADMIN_ID, FEE)
    db.log_transaction(sender_id, target["user_id"], amount, FEE)

    sender_tag = fmt_user(sender_id, message.from_user.username)
    target_tag = fmt_user(target["user_id"], target["username"])

    await message.answer(
        f"✅ {amount} ⭐️ dan {net_amount} ⭐️ {target_tag} ga o'tkazildi.\n"
        f"🔹 {FEE} ⭐️ tizim ulushi sifatida olindi.\n"
        f"Yangi balansingiz: {db.get_user(sender_id)['balance']} ⭐️"
    )
    try:
        await bot.send_message(
            target["user_id"],
            f"🎉 Sizga {sender_tag} tomonidan {net_amount} ⭐️ o'tkazildi!\n"
            f"Yangi balansingiz: {db.get_user(target['user_id'])['balance']} ⭐️",
        )
    except Exception as e:
        log.warning("Could not notify recipient: %s", e)

    await announce(
        f"🔁 <b>Yangi o'tkazma</b>\n"
        f"Kimdan: {sender_tag}\n"
        f"Kimga: {target_tag}\n"
        f"Miqdor: {amount} ⭐️ (foydalanuvchiga {net_amount} ⭐️, tizimga {FEE} ⭐️)"
    )


@dp.message(Command("stats"))
async def stats_handler(message: Message):
    if message.from_user.id != SUPERADMIN_ID:
        await message.answer("❌ Bu buyruq faqat superadmin uchun.")
        return
    s = db.stats()
    await message.answer(
        "📊 <b>Statistika</b>\n"
        f"Foydalanuvchilar: {s['users']}\n"
        f"To'lov qilganlar: {s['paid_users']}\n"
        f"Jami o'tkazilgan hajm: {s['total_volume']} ⭐️\n"
        f"Jami tizim ulushi: {s['total_fees']} ⭐️"
    )


async def main():
    db.init_db(DB_PATH)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
