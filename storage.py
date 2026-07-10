import asyncio
import json
import logging

from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaDocument

log = logging.getLogger("stars-share.storage")

STATE_FILENAME = "stars_share_state.json"

# Butun bot bo'ylab BITTA lock: barcha balans o'zgarishlari shu orqali
# navbatlashtiriladi (Render'da bot bitta process/polling instansiya sifatida
# ishlaydi degan taxmin bilan — agar kelajakda birdan ortiq instansiya
# ishlatsangiz, bu lock yetarli bo'lmaydi, tashqi lock kerak bo'ladi).
state_lock = asyncio.Lock()

_state: dict = {"users": {}, "stats": {"total_volume": 0, "total_fees": 0}}
_pinned_message_id: int | None = None


def _default_state() -> dict:
    return {"users": {}, "stats": {"total_volume": 0, "total_fees": 0}}


async def load_state(bot: Bot, storage_chat_id: int, storage_topic_id: int | None = None):
    """Bot ishga tushganda supergroup'dagi pinned fayldan holatni tiklaydi."""
    global _state, _pinned_message_id
    try:
        chat = await bot.get_chat(storage_chat_id)
        pinned = chat.pinned_message
        if pinned and pinned.document:
            file = await bot.get_file(pinned.document.file_id)
            buf = await bot.download_file(file.file_path)
            _state = json.loads(buf.read().decode("utf-8"))
            _pinned_message_id = pinned.message_id
            log.info("State tiklandi: pinned message_id=%s", _pinned_message_id)
            return
    except Exception as e:
        log.warning("Pinned state topilmadi/o'qib bo'lmadi (birinchi ishga tushishmi?): %s", e)

    # Birinchi marta ishga tushmoqda - bo'sh state yaratamiz va saqlaymiz.
    _state = _default_state()
    await _persist(bot, storage_chat_id, storage_topic_id)


async def _persist(bot: Bot, storage_chat_id: int, storage_topic_id: int | None):
    """Joriy _state'ni supergroup'dagi pinned faylga yozadi (yaratadi yoki tahrirlaydi)."""
    global _pinned_message_id
    data = json.dumps(_state, ensure_ascii=False, indent=2).encode("utf-8")
    doc = BufferedInputFile(data, filename=STATE_FILENAME)

    if _pinned_message_id is None:
        kwargs = {"message_thread_id": storage_topic_id} if storage_topic_id else {}
        msg = await bot.send_document(
            chat_id=storage_chat_id,
            document=doc,
            caption="⚠️ Stars Share bot state fayli. QO'LDA O'CHIRMANG.",
            **kwargs,
        )
        await bot.pin_chat_message(storage_chat_id, msg.message_id, disable_notification=True)
        _pinned_message_id = msg.message_id
    else:
        await bot.edit_message_media(
            chat_id=storage_chat_id,
            message_id=_pinned_message_id,
            media=InputMediaDocument(media=doc, caption="⚠️ Stars Share bot state fayli."),
        )


def get_user(user_id: int) -> dict | None:
    return _state["users"].get(str(user_id))


def upsert_user(user_id: int, username: str | None):
    key = str(user_id)
    if key not in _state["users"]:
        _state["users"][key] = {"username": username, "balance": 0, "has_paid": False}
    else:
        _state["users"][key]["username"] = username


def get_user_by_username(username: str) -> dict | None:
    username = username.lstrip("@").lower()
    for uid, u in _state["users"].items():
        if (u.get("username") or "").lower() == username:
            return {"user_id": int(uid), **u}
    return None


async def credit_from_payment(
    bot: Bot, storage_chat_id: int, storage_topic_id: int | None,
    user_id: int, amount: int, charge_id: str,
) -> bool:
    """Idempotent: bir xil charge_id ikki marta hisoblanmaydi."""
    async with state_lock:
        seen = _state.setdefault("_seen_charges", {})
        if charge_id in seen:
            return False
        key = str(user_id)
        u = _state["users"].setdefault(key, {"username": None, "balance": 0, "has_paid": False})
        u["balance"] += amount
        u["has_paid"] = True
        seen[charge_id] = True
        try:
            await _persist(bot, storage_chat_id, storage_topic_id)
        except Exception:
            # Persist muvaffaqiyatsiz bo'lsa - xotiradagi o'zgarishni ham qaytaramiz,
            # aks holda restart bo'lganda bu kredit yo'qolib qoladi (persist bo'lmagani uchun),
            # lekin joriy sessiyada foydalanuvchi balansni ko'rib qoladi - bu yolg'on holat.
            u["balance"] -= amount
            seen.pop(charge_id, None)
            raise
        return True


async def transfer(
    bot: Bot, storage_chat_id: int, storage_topic_id: int | None,
    from_id: int, to_id: int, amount: int, fee: int, admin_id: int,
) -> dict:
    """
    Atomik o'tkazma: state_lock butun process ichida boshqa har qanday
    balans o'zgarishini shu tugagunga qadar kutib turadi (race condition yo'q).
    Persist muvaffaqiyatsiz bo'lsa - xotiradagi o'zgarish ORTGA qaytariladi,
    ya'ni foydalanuvchiga hech narsa yo'qolmagandek ko'rinadi va bu haqiqat -
    tashqi (pinned fayldagi) holat o'zgarmagan bo'ladi.
    """
    async with state_lock:
        from_key, to_key, admin_key = str(from_id), str(to_id), str(admin_id)
        sender = _state["users"].get(from_key)
        if not sender or sender["balance"] < amount:
            return {"ok": False, "reason": "insufficient_balance"}

        net = amount - fee
        # Snapshot - xato bo'lsa qaytarish uchun
        snap_sender = sender["balance"]
        snap_target = _state["users"].get(to_key, {}).get("balance", 0)
        snap_admin = _state["users"].get(admin_key, {}).get("balance", 0)

        sender["balance"] -= amount
        target = _state["users"].setdefault(to_key, {"username": None, "balance": 0, "has_paid": False})
        target["balance"] += net
        admin_u = _state["users"].setdefault(admin_key, {"username": None, "balance": 0, "has_paid": True})
        admin_u["balance"] += fee
        _state["stats"]["total_volume"] += amount
        _state["stats"]["total_fees"] += fee

        try:
            await _persist(bot, storage_chat_id, storage_topic_id)
        except Exception as e:
            # ROLLBACK - tashqi holat o'zgarmagani uchun xotirani ham qaytaramiz
            sender["balance"] = snap_sender
            target["balance"] = snap_target
            admin_u["balance"] = snap_admin
            _state["stats"]["total_volume"] -= amount
            _state["stats"]["total_fees"] -= fee
            return {"ok": False, "reason": "error", "error": str(e)}

        return {"ok": True}


def stats() -> dict:
    users = _state["users"]
    return {
        "users": len(users),
        "paid_users": sum(1 for u in users.values() if u.get("has_paid")),
        "total_volume": _state["stats"]["total_volume"],
        "total_fees": _state["stats"]["total_fees"],
    }
