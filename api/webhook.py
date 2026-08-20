# -*- coding: utf-8 -*-
"""
Telegram bot - Foydalanuvchi paneli (admin ishlari veb-saytda: /admin -> sayt)

Muhit o'zgaruvchilari (Vercel -> Settings -> Environment Variables):
    BOT_TOKEN            - Telegram bot tokeni (@BotFather dan)
    ADMIN_LOGIN_ID       - admin panelga kirish uchun ID
    ADMIN_LOGIN_PASSWORD - admin panelga kirish uchun parol
    FIREBASE_DB_URL      - masalan: https://loyiha-nomi-default-rtdb.firebaseio.com
    FIREBASE_SECRET      - (ixtiyoriy) Firebase legacy database secret
    SITE_URL             - (ixtiyoriy) masalan https://oz-lek-bot.vercel.app
                            berilmasa, so'rov domeni avtomatik ishlatiladi
"""

import os
import re
import io
import json
import time
import base64
import secrets
import asyncio
import difflib
from http.server import BaseHTTPRequestHandler

import requests
from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

# --------------------------------------------------------------------------
# SOZLAMALAR
# --------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_LOGIN_ID = os.environ.get("ADMIN_LOGIN_ID", "")
ADMIN_LOGIN_PASSWORD = os.environ.get("ADMIN_LOGIN_PASSWORD", "")
SITE_URL_ENV = os.environ.get("SITE_URL", "").rstrip("/")

FIREBASE_DB_URL = os.environ.get("FIREBASE_DB_URL", "").rstrip("/")
FIREBASE_SECRET = os.environ.get("FIREBASE_SECRET", "")

TOKEN_TTL_SECONDS = 30 * 60  # admin havolasi 30 daqiqa amal qiladi


# --------------------------------------------------------------------------
# FIREBASE YORDAMCHI FUNKSIYALAR (REST API orqali, doimiy saqlash uchun)
# --------------------------------------------------------------------------

def _fb_params():
    return {"auth": FIREBASE_SECRET} if FIREBASE_SECRET else {}


def fb_get(path):
    try:
        r = requests.get(f"{FIREBASE_DB_URL}/{path}.json", params=_fb_params(), timeout=8)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Firebase GET xato:", e)
        return None


def fb_set(path, data):
    try:
        r = requests.put(f"{FIREBASE_DB_URL}/{path}.json", params=_fb_params(), json=data, timeout=8)
        r.raise_for_status()
        return True
    except Exception as e:
        print("Firebase SET xato:", e)
        return False


def fb_update(path, data):
    try:
        r = requests.patch(f"{FIREBASE_DB_URL}/{path}.json", params=_fb_params(), json=data, timeout=8)
        r.raise_for_status()
        return True
    except Exception as e:
        print("Firebase UPDATE xato:", e)
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
    if not text:
        return ""
    text = transliterate(text)
    return re.sub(r"[^a-z0-9]", "", text.lower())


def find_best_product(user_text: str, products: dict, threshold: float = 0.7):
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
    image_b64 = product.get("image_base64")

    if image_b64:
        try:
            photo_bytes = base64.b64decode(image_b64)
            photo_file = io.BytesIO(photo_bytes)
            photo_file.name = "product.jpg"
            await bot.send_photo(chat_id, photo_file, caption=caption)
            return
        except Exception as e:
            print("Rasm yuborishda xato:", e)
            await bot.send_message(chat_id, f"{caption}\n\n(⚠️ rasmni yuborib bo'lmadi)")
            return

    await bot.send_message(chat_id, caption)


def get_site_url(request_host: str) -> str:
    if SITE_URL_ENV:
        return SITE_URL_ENV
    if request_host:
        return f"https://{request_host}"
    return ""


# --------------------------------------------------------------------------
# ASOSIY LOGIKA
# --------------------------------------------------------------------------

async def handle_update(bot: Bot, update: Update, request_host: str):
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
            await send_admin_link(bot, chat_id, request_host)
        else:
            fb_set(f"sessions/{chat_id}", {"admin": False, "step": "await_id"})
            await bot.send_message(chat_id, "🔑 Admin ID kiriting:")
        await try_delete(bot, chat_id, message.message_id)
        return

    if text.startswith("/logout"):
        fb_set(f"sessions/{chat_id}", {"admin": False, "step": None})
        await bot.send_message(chat_id, "Admin sessiyasi tugatildi.")
        return

    # ---------------- LOGIN BOSQICHLARI ----------------

    if step == "await_id":
        fb_update(f"sessions/{chat_id}", {"step": "await_password", "temp_id": text})
        await bot.send_message(chat_id, "🔒 Parolni kiriting:")
        await try_delete(bot, chat_id, message.message_id)
        return

    if step == "await_password":
        entered_id = session.get("temp_id", "")
        if entered_id == ADMIN_LOGIN_ID and text == ADMIN_LOGIN_PASSWORD:
            fb_set(f"sessions/{chat_id}", {"admin": True, "step": None})
            await send_admin_link(bot, chat_id, request_host)
        else:
            fb_set(f"sessions/{chat_id}", {"admin": False, "step": None})
            await bot.send_message(chat_id, "❌ ID yoki parol noto'g'ri.")
        await try_delete(bot, chat_id, message.message_id)
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


async def send_admin_link(bot: Bot, chat_id: int, request_host: str):
    token = secrets.token_urlsafe(24)
    fb_set(f"admin_tokens/{token}", {"created": int(time.time() * 1000)})

    site_url = get_site_url(request_host)
    if not site_url:
        await bot.send_message(chat_id, "❌ Sayt manzili sozlanmagan (SITE_URL).")
        return

    link = f"{site_url}/admin?token={token}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔐 Admin panelni ochish", url=link)]])
    await bot.send_message(chat_id, "✅ Tasdiqlandi. Admin panelni oching:", reply_markup=kb)


# --------------------------------------------------------------------------
# VERCEL ENTRYPOINT
# --------------------------------------------------------------------------

async def process(data: dict, request_host: str):
    bot = Bot(token=BOT_TOKEN)
    async with bot:
        update = Update.de_json(data, bot)
        if update:
            await handle_update(bot, update, request_host)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body or b"{}")
            request_host = self.headers.get("Host", "")
            asyncio.run(process(data, request_host))
        except Exception as e:
            print("Webhook xatolik:", e)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot ishlayapti.")
