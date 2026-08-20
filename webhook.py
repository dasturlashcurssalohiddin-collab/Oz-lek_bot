# -*- coding: utf-8 -*-
"""
Telegram bot - Admin panel + Foydalanuvchi panel
Vercel serverless funksiya sifatida ishlaydi (webhook orqali).

Muhit o'zgaruvchilari (Vercel -> Settings -> Environment Variables):
    BOT_TOKEN            - Telegram bot tokeni (@BotFather dan)
    ADMIN_LOGIN_ID       - admin panelga kirish uchun ID (o'zingiz o'ylab toping)
    ADMIN_LOGIN_PASSWORD - admin panelga kirish uchun parol
    FIREBASE_DB_URL      - masalan: https://loyiha-nomi-default-rtdb.firebaseio.com
    FIREBASE_SECRET      - Firebase legacy database secret
                            (Project Settings -> Service accounts -> Database secrets)
"""

import os
import re
import json
import asyncio
import difflib
from http.server import BaseHTTPRequestHandler

import requests
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup

# --------------------------------------------------------------------------
# SOZLAMALAR
# --------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_LOGIN_ID = os.environ.get("ADMIN_LOGIN_ID", "")
ADMIN_LOGIN_PASSWORD = os.environ.get("ADMIN_LOGIN_PASSWORD", "")

FIREBASE_DB_URL = os.environ.get("FIREBASE_DB_URL", "").rstrip("/")
FIREBASE_SECRET = os.environ.get("FIREBASE_SECRET", "")


# --------------------------------------------------------------------------
# FIREBASE YORDAMCHI FUNKSIYALAR (REST API orqali, doimiy saqlash uchun)
# --------------------------------------------------------------------------

def _fb_params():
    """FIREBASE_SECRET berilgan bo'lsa qo'shadi, bo'lmasa (masalan test mode
    rejimida) auth parametrisiz so'rov yuboradi."""
    return {"auth": FIREBASE_SECRET} if FIREBASE_SECRET else {}


def fb_get(path):
    """Firebase'dan ma'lumot o'qish. Topilmasa None qaytaradi."""
    try:
        r = requests.get(
            f"{FIREBASE_DB_URL}/{path}.json",
            params=_fb_params(),
            timeout=8,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Firebase GET xato:", e)
        return None


def fb_set(path, data):
    """To'liq yozish/almashtirish (PUT)."""
    try:
        r = requests.put(
            f"{FIREBASE_DB_URL}/{path}.json",
            params=_fb_params(),
            json=data,
            timeout=8,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print("Firebase SET xato:", e)
        return False


def fb_update(path, data):
    """Faqat berilgan maydonlarni yangilash, qolganini saqlab qolish (PATCH)."""
    try:
        r = requests.patch(
            f"{FIREBASE_DB_URL}/{path}.json",
            params=_fb_params(),
            json=data,
            timeout=8,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print("Firebase UPDATE xato:", e)
        return False


def fb_delete(path):
    try:
        r = requests.delete(
            f"{FIREBASE_DB_URL}/{path}.json",
            params=_fb_params(),
            timeout=8,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print("Firebase DELETE xato:", e)
        return False


# --------------------------------------------------------------------------
# KIRILL <-> LOTIN NORMALLASHTIRISH VA FUZZY QIDIRUV
# --------------------------------------------------------------------------

CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}


def transliterate(text: str) -> str:
    text = text.lower()
    return "".join(CYR_TO_LAT.get(ch, ch) for ch in text)


def normalize_for_match(text: str) -> str:
    """Kirill/lotin farqini va tinish belgilarini yo'qotib, taqqoslash uchun tayyorlaydi."""
    if not text:
        return ""
    text = transliterate(text)
    text = re.sub(r"[^a-z0-9]", "", text.lower())
    return text


def find_best_product(user_text: str, products: dict, threshold: float = 0.7):
    """Kirill/lotin farqi va xatoliklarga chidamli qidiruv. Topilsa key qaytaradi."""
    query = normalize_for_match(user_text)
    if not query or not products:
        return None

    best_key, best_ratio = None, 0.0
    for key, p in products.items():
        candidate = normalize_for_match(p.get("name", ""))
        if not candidate:
            continue
        ratio = difflib.SequenceMatcher(None, query, candidate).ratio()
        if query in candidate or candidate in query:
            ratio = max(ratio, 0.85)
        if ratio > best_ratio:
            best_ratio, best_key = ratio, key

    return best_key if best_ratio >= threshold else None


# --------------------------------------------------------------------------
# VALIDATSIYA
# --------------------------------------------------------------------------

def validate_product(name: str, description: str):
    """None qaytarsa - to'g'ri. Aks holda sabab matnini qaytaradi."""
    if not name:
        return "mahsulot nomi kiritilmagan."
    if len(name) > 60:
        return "mahsulot nomi juda uzun (60 belgidan oshmasin)."
    if not description:
        return "mahsulot haqida ma'lumot kiritilmagan."
    if len(description) < 5:
        return "ma'lumot juda qisqa yozilgan."
    return None


# --------------------------------------------------------------------------
# TELEGRAM YORDAMCHILARI
# --------------------------------------------------------------------------

async def try_delete(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        print("Xabarni o'chirib bo'lmadi:", e)


def build_menu(products: dict):
    if not products:
        return None
    rows = [
        [InlineKeyboardButton(p.get("name", key), callback_data=key)]
        for key, p in products.items()
    ]
    return InlineKeyboardMarkup(rows)


async def send_product(bot: Bot, chat_id: int, product: dict):
    caption = f"{product.get('name', '')}\n\n{product.get('description', '')}"
    photo_id = product.get("photo_file_id")
    if photo_id:
        await bot.send_photo(chat_id, photo_id, caption=caption)
    else:
        await bot.send_message(chat_id, caption)


# --------------------------------------------------------------------------
# ASOSIY LOGIKA
# --------------------------------------------------------------------------

async def handle_update(bot: Bot, update: Update):
    # --- Callback (menyudagi tugma bosilganda) ---
    if update.callback_query:
        cq = update.callback_query
        chat_id = cq.message.chat_id
        products = fb_get("products") or {}
        product = products.get(cq.data)
        await cq.answer()
        if product:
            await send_product(bot, chat_id, product)
        else:
            await bot.send_message(chat_id, "Bu mahsulot topilmadi (ehtimol o'chirilgan).")
        return

    message = update.message
    if not message:
        return

    chat_id = message.chat_id
    text = (message.text or message.caption or "").strip()

    session = fb_get(f"sessions/{chat_id}") or {}
    is_admin = bool(session.get("admin", False))
    step = session.get("step")

    # ---------------- BUYRUQLAR ----------------

    if text.startswith("/start"):
        fb_update(f"sessions/{chat_id}", {"step": None})
        products = fb_get("products") or {}
        kb = build_menu(products)
        if kb:
            await bot.send_message(chat_id, "🛍 Mahsulotlar ro'yxati:", reply_markup=kb)
        else:
            await bot.send_message(chat_id, "Hozircha mahsulotlar mavjud emas.")
        return

    if text.startswith("/admin"):
        if is_admin:
            await bot.send_message(
                chat_id, "✅ Siz allaqachon admin sifatida kirgansiz.\nChiqish uchun /logout yozing."
            )
        else:
            fb_set(f"sessions/{chat_id}", {"admin": False, "step": "await_id"})
            await bot.send_message(chat_id, "🔑 Admin ID kiriting:")
        await try_delete(bot, chat_id, message.message_id)
        return

    if text.startswith("/logout"):
        fb_set(f"sessions/{chat_id}", {"admin": False, "step": None})
        await bot.send_message(chat_id, "Admin sessiyasi tugatildi.")
        return

    if text.startswith("/bekor"):
        fb_update(f"sessions/{chat_id}", {"step": None})
        await bot.send_message(chat_id, "Bekor qilindi.")
        return

    if text.startswith("/ma'lumot") or text.startswith("/malumot"):
        if not is_admin:
            await bot.send_message(chat_id, "❌ Bu buyruq faqat admin uchun.")
            return
        fb_update(f"sessions/{chat_id}", {"step": "await_photo"})
        await bot.send_message(
            chat_id,
            "📷 Mahsulot rasmini yuboring.\n"
            "(Fayl qilib tashlasangiz ham, nusxalab joylashtirsangiz ham bo'ladi.)",
        )
        return

    # ---------------- BOSQICHLAR (LOGIN VA MA'LUMOT KIRITISH) ----------------

    if step == "await_id":
        fb_update(f"sessions/{chat_id}", {"step": "await_password", "temp_id": text})
        await bot.send_message(chat_id, "🔒 Parolni kiriting:")
        await try_delete(bot, chat_id, message.message_id)
        return

    if step == "await_password":
        entered_id = session.get("temp_id", "")
        if entered_id == ADMIN_LOGIN_ID and text == ADMIN_LOGIN_PASSWORD:
            fb_set(f"sessions/{chat_id}", {"admin": True, "step": None})
            await bot.send_message(chat_id, "✅ Admin sifatida kirdingiz.")
        else:
            fb_set(f"sessions/{chat_id}", {"admin": False, "step": None})
            await bot.send_message(chat_id, "❌ ID yoki parol noto'g'ri.")
        await try_delete(bot, chat_id, message.message_id)
        return

    if step == "await_photo" and is_admin:
        file_id = None
        if message.photo:
            file_id = message.photo[-1].file_id
        elif message.document and (message.document.mime_type or "").startswith("image/"):
            file_id = message.document.file_id

        if not file_id:
            await bot.send_message(chat_id, "qabul qilinmadi❌ bu rasm emas. Iltimos, rasm yuboring.")
            return

        fb_update(f"sessions/{chat_id}", {"step": "await_text", "temp_photo": file_id})
        await bot.send_message(
            chat_id,
            "✏️ Endi mahsulot nomi va ma'lumotini yuboring.\n"
            "Birinchi qatorga NOMI, keyingi qator(lar)ga TAVSIFI yoziladi.\n\n"
            "Masalan:\nGo'sh tuxumi\nDala tovug'idan, 1 dona 1500 so'm, bugungi kunda yig'ilgan.",
        )
        return

    if step == "await_text" and is_admin:
        parts = text.split("\n", 1)
        name = parts[0].strip() if parts else ""
        description = parts[1].strip() if len(parts) > 1 else ""

        reason = validate_product(name, description)
        if reason:
            await bot.send_message(chat_id, f"qabul qilinmadi❌ {reason}")
            return

        key = normalize_for_match(name)
        if not key:
            await bot.send_message(chat_id, "qabul qilinmadi❌ mahsulot nomi noto'g'ri.")
            return

        ok = fb_set(
            f"products/{key}",
            {
                "name": name,
                "description": description,
                "photo_file_id": session.get("temp_photo"),
            },
        )
        fb_update(f"sessions/{chat_id}", {"step": None, "temp_photo": None})

        if ok:
            await bot.send_message(chat_id, "qabul bo'ldi✅")
        else:
            await bot.send_message(chat_id, "qabul qilinmadi❌ bazaga yozishda xatolik yuz berdi, birozdan keyin qayta urinib ko'ring.")
        return

    # ---------------- ODDIY MATN -> MAHSULOT QIDIRISH ----------------

    if text and not text.startswith("/"):
        products = fb_get("products") or {}
        match_key = find_best_product(text, products)
        if match_key:
            await send_product(bot, chat_id, products[match_key])
        else:
            await bot.send_message(chat_id, "🔍 Bunday mahsulot topilmadi.")
        return


# --------------------------------------------------------------------------
# VERCEL ENTRYPOINT
# --------------------------------------------------------------------------

async def process(data: dict):
    bot = Bot(token=BOT_TOKEN)
    async with bot:
        update = Update.de_json(data, bot)
        if update:
            await handle_update(bot, update)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body or b"{}")
            asyncio.run(process(data))
        except Exception as e:
            print("Webhook xatolik:", e)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot ishlayapti.")
