# Telegram bot — Admin panel + Foydalanuvchi panel

## Qanday ishlaydi

**Foydalanuvchi:**
- `/start` — mahsulotlar menyusi chiqadi (har qatorda bitta mahsulot nomi tugma bo'lib).
- Tugmani bossa — o'sha mahsulotning rasmi va ma'lumoti chiqadi.
- Tugma bosmasdan, to'g'ridan-to'g'ri yozuv orqali mahsulot nomini yozsa ham topib beradi —
  kirillcha yoki lotincha yozilishidan qat'iy nazar, va kichik xatoliklar (masalan bitta harf
  noto'g'ri yozilgan bo'lsa) ham muammo qilmaydi.

**Admin:**
- `/admin` — ID so'raladi, keyin parol so'raladi. To'g'ri kiritilsa, admin sifatida kiradi.
  Xavfsizlik uchun `/admin` buyrug'i va kiritilgan ID/parol xabarlari chatdan avtomatik o'chiriladi.
- Login qilingandan keyin sessiya davom etadi (qayta-qayta so'ralmaydi). Chiqish uchun `/logout`.
- `/ma'lumot` (yoki `/malumot`) — faqat admin uchun ishlaydi:
  1. Bot rasm so'raydi (fayl qilib yuborilsa ham, nusxalab joylashtirilsa ham qabul qilinadi)
  2. Keyin nom va ma'lumot so'raydi (birinchi qator — nomi, qolgani — tavsif)
  3. Hammasi to'g'ri bo'lsa: **"qabul bo'ldi✅"**
  4. Xato bo'lsa (masalan rasm o'rniga matn yuborilsa, nomi yoki tavsifi yo'q bo'lsa):
     **"qabul qilinmadi❌ <sababi>"**

Barcha mahsulotlar **Firebase Realtime Database**da saqlanadi — shuning uchun GitHub'dagi
kodni o'zgartirib qayta deploy qilsangiz ham, ma'lumotlar o'chib ketmaydi.

> **Muhim eslatma:** Telegram Bot API "foydalanuvchi ilovadan chiqib ketdimi" degan ma'lumotni
> umuman bermaydi — buni texnik jihatdan aniqlash imkonsiz. Shu sababli "ilovadan chiqib qayta
> kirganda qayta login so'ralsin" talabini aynan shu ko'rinishda amalga oshirib bo'lmaydi.
> Uning o'rniga men `/logout` buyrug'ini qo'shdim — admin xohlagan payti chiqishi mumkin,
> chiqmasa sessiya davom etadi.

---

## O'rnatish

### 1. Firebase loyihasi

1. [console.firebase.google.com](https://console.firebase.google.com) da yangi loyiha oching (yoki mavjudini ishlating).
2. **Build → Realtime Database → Create Database** (test rejimida boshlashingiz mumkin).
3. Database URL'ni nusxalang (masalan `https://loyiha-default-rtdb.firebaseio.com`).
4. **Project settings (⚙️) → Service accounts → Database secrets** bo'limidan "legacy secret"ni oling.

### 2. Bot yaratish

@BotFather orqali yangi bot yarating va tokenni oling.

### 3. GitHub

```bash
cd telegram-bot
git init
git add .
git commit -m "Telegram bot"
git branch -M main
git remote add origin https://github.com/dasturlashcurssalohiddin-collab/SIZNING_REPO.git
git push -u origin main
```

> `.env.example`dagi haqiqiy qiymatlarni hech qachon GitHub'ga push qilmang — ular faqat
> Vercel Environment Variables bo'limida bo'lishi kerak.

### 4. Vercel

1. [vercel.com](https://vercel.com) → **New Project** → GitHub repongizni tanlang → Import.
2. **Settings → Environment Variables** ga quyidagilarni qo'shing:
   - `BOT_TOKEN`
   - `ADMIN_LOGIN_ID`
   - `ADMIN_LOGIN_PASSWORD`
   - `FIREBASE_DB_URL`
   - `FIREBASE_SECRET`
3. Deploy tugagach, loyiha manzilingizni (masalan `https://tuxum-bot.vercel.app`) nusxalab oling.

### 5. Webhookni ulash

`set_webhook.py` faylida `BOT_TOKEN` va `VERCEL_URL`ni to'ldirib, o'z kompyuteringizda:

```bash
python set_webhook.py
```

Yoki brauzerda to'g'ridan-to'g'ri oching:

```
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://sizning-loyiha.vercel.app/api/webhook
```

### 6. Sinab ko'rish

Telegram'da botga `/start` yuboring. Muammo bo'lsa Vercel dashboard → Deployments → Logs
bo'limidan xatolikni ko'rishingiz mumkin.

---

## Fayllar tuzilishi

```
telegram-bot/
├── api/
│   └── webhook.py       # butun bot logikasi (bitta faylda — Vercel importi buzilmasligi uchun)
├── requirements.txt
├── vercel.json
├── .env.example
├── set_webhook.py
└── README.md
```
