# Stars Share

Telegram Stars P2P transfer bot. Foydalanuvchilar bir-biriga Telegram Stars
o'tkaza oladi. Har bir o'tkazmadan 1 ⭐️ tizim (superadmin) ulushi sifatida
olinadi, qolgani to'liq qabul qiluvchiga boradi. Har bir tranzaksiya
shaffoflik uchun ikkala tomonga (va, agar sozlangan bo'lsa, ommaviy kanalga)
e'lon qilinadi.

## Muhim eslatma (arxitektura)

Telegram Bot API orqali botlar foydalanuvchilardan Stars **qabul qilishi**
mumkin (invoice orqali), lekin botning o'zi ikkita oddiy foydalanuvchi
o'rtasida haqiqiy Stars balansini bevosita o'tkaza olmaydi — bunday ochiq
API yo'q. Shu sababli bu bot **ichki hisob-kitob (ledger)** tizimi bilan
ishlaydi:

1. Foydalanuvchi `/topup` orqali botga real Stars to'laydi → bu miqdor
   uning ichki balansiga qo'shiladi.
2. `/send` orqali ichki balansdan ichki balansga o'tkazma qilinadi (real
   vaqtda hech qanday Stars ko'chib o'tmaydi, faqat ma'lumotlar bazasidagi
   raqamlar o'zgaradi).
3. Superadmin xohlagan vaqtda o'z ichki balansini botning umumiy Stars
   hisobidan yechib olishi mumkin (Telegram bot to'lovlar paneli orqali).

Bu — Stars uchun eng ko'p ishlatiladigan naqd pul o'rnini bosuvchi (in-app
currency) yondashuv, xuddi o'yin ichidagi tanga tizimlari kabi.

## O'rnatish

```bash
pip install -r requirements.txt
cp .env.example .env   # va qiymatlarni to'ldiring
export $(cat .env | xargs)
python bot.py
```

## Environment o'zgaruvchilari

| Nomi | Tavsif |
|---|---|
| `BOT_TOKEN` | BotFather'dan olingan bot tokeni |
| `SUPERADMIN_ID` | Superadminning Telegram user ID raqami |
| `LOG_CHANNEL_ID` | (ixtiyoriy) Shaffoflik uchun har bir tranzaksiya e'lon qilinadigan kanal/guruh ID |
| `DB_PATH` | SQLite fayl yo'li (standart: `stars_share.db`) |

## Buyruqlar

- `/start` — ro'yxatdan o'tish
- `/topup <miqdor>` — Stars orqali balansni to'ldirish
- `/balance` — joriy balansni ko'rish
- `/send <@username yoki ID> <miqdor>` — boshqa foydalanuvchiga stars o'tkazish
- `/stats` — (faqat superadmin) umumiy statistika

## Render'ga deploy qilish

Render'da **Background Worker** yoki **Web Service** sifatida deploy
qiling (polling rejimida ishlaydi, webhook shart emas). Environment
Variables bo'limiga yuqoridagi jadvaldagi qiymatlarni kiriting.

⚠️ SQLite fayli Render'ning ephemeral disk tizimida deploy qilinganda har
qayta deploy'da **o'chib ketadi**. Productionda ishlatish uchun Render
Disk (persistent disk) qo'shing yoki PostgreSQL kabi tashqi DB'ga
o'tkazing.
