# -*- coding: utf-8 -*-
"""
Telegram bot - Foydalanuvchi paneli (admin ishlari veb-saytda: /admin -> sayt)
Ko'p tillilik: foydalanuvchi tiliga (Telegram profilidan) avtomatik moslashadi,
"menga moslash" desa yoki /til orqali tilni/yozuvni o'zi tanlaydi.

Muhit o'zgaruvchilari (Vercel -> Settings -> Environment Variables):
    BOT_TOKEN            - Telegram bot tokeni (@BotFather dan)
    ADMIN_LOGIN_ID       - admin panelga kirish uchun ID
    ADMIN_LOGIN_PASSWORD - admin panelga kirish uchun parol
    FIREBASE_DB_URL      - masalan: https://loyiha-nomi-default-rtdb.firebaseio.com
    FIREBASE_SECRET      - (ixtiyoriy) Firebase legacy database secret
    SITE_URL             - (ixtiyoriy) masalan https://oz-lek-bot.vercel.app
"""

import os
import re
import io
import json
import time
import base64
import secrets
import hashlib
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

TOKEN_TTL_SECONDS = 30 * 60


# --------------------------------------------------------------------------
# FIREBASE YORDAMCHI FUNKSIYALAR
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
# KIRILL <-> LOTIN (o'zbekcha qidiruv va ko'rsatish uchun)
# --------------------------------------------------------------------------

CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}

LAT_MULTI_TO_CYR = [
    ("o'", "ў"), ("oʻ", "ў"), ("o‘", "ў"), ("o`", "ў"),
    ("g'", "ғ"), ("gʻ", "ғ"), ("g‘", "ғ"), ("g`", "ғ"),
    ("yo", "ё"), ("yu", "ю"), ("ya", "я"),
    ("sh", "ш"), ("ch", "ч"), ("ng", "нг"), ("ts", "ц"),
]
LAT_SINGLE_TO_CYR = {
    "a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "ҳ",
    "i": "и", "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о",
    "p": "п", "q": "қ", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в",
    "x": "х", "y": "й", "z": "з",
}


def transliterate(text: str) -> str:
    """Kirillcha matnni lotinga o'giradi (qidiruv uchun normallashtirish, kichik harflarga tushiradi)."""
    text = text.lower()
    return "".join(CYR_TO_LAT.get(ch, ch) for ch in text)


def cyrillic_to_latin_display(text: str) -> str:
    """Kirillcha matnni lotinga o'giradi, katta-kichik harflarni imkon qadar saqlab qoladi."""
    if not text:
        return text
    out = []
    for ch in text:
        lower_ch = ch.lower()
        mapped = CYR_TO_LAT.get(lower_ch, ch)
        if ch.isupper() and mapped:
            mapped = mapped[0].upper() + mapped[1:] if len(mapped) > 1 else mapped.upper()
        out.append(mapped)
    return "".join(out)


def latin_to_cyrillic(text: str) -> str:
    """Lotincha o'zbek matnini kirillga o'giradi (ko'rsatish uchun, taxminiy)."""
    if not text:
        return text
    result = text.lower()
    for lat, cyr in LAT_MULTI_TO_CYR:
        result = result.replace(lat, cyr)
    result = "".join(LAT_SINGLE_TO_CYR.get(ch, ch) for ch in result)
    if result:
        result = result[0].upper() + result[1:]
    return result


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


def contains_cyrillic(text: str) -> bool:
    return bool(re.search(r"[\u0400-\u04FF]", text))


# --------------------------------------------------------------------------
# TARJIMA (bepul, ochiq Google Translate endpoint + Firebase kesh)
# --------------------------------------------------------------------------

def translate_google(text: str, target_lang: str, source_lang: str = "auto"):
    """(tarjima_matni, aniqlangan_manba_til) qaytaradi. Xato bo'lsa (None, None)."""
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": source_lang, "tl": target_lang, "dt": "t", "q": text},
            timeout=6,
        )
        r.raise_for_status()
        data = r.json()
        translated = "".join(seg[0] for seg in data[0] if seg[0])
        detected = data[2] if len(data) > 2 else None
        return translated, detected
    except Exception as e:
        print("Tarjima xatosi:", e)
        return None, None


def translate_cached(text: str, target_lang: str) -> str:
    if not text:
        return text
    cache_key = f"translations/{target_lang}/{hashlib.md5(text.encode('utf-8')).hexdigest()}"
    cached = fb_get(cache_key)
    if isinstance(cached, dict) and cached.get("t"):
        return cached["t"]
    translated, _ = translate_google(text, target_lang, source_lang="auto")
    if translated:
        fb_set(cache_key, {"t": translated})
        return translated
    return text  # tarjima ishlamasa, asl matnni ko'rsatamiz


def display_text(source_text: str, lang: str, script: str) -> str:
    """Mahsulot nomi/tavsifini foydalanuvchi tiliga/yozuviga moslab qaytaradi.
    Manba matn lotin yoki kirill bo'lishidan qat'i nazar, kerakli tomonga o'giradi."""
    if not source_text:
        return source_text
    if lang == "uz":
        source_is_cyrillic = contains_cyrillic(source_text)
        if script == "cyrillic":
            return source_text if source_is_cyrillic else latin_to_cyrillic(source_text)
        else:  # lotin so'ralgan
            return cyrillic_to_latin_display(source_text) if source_is_cyrillic else source_text
    return translate_cached(source_text, lang)


BASE_STRINGS = {
    "menu_title": "🛍 Mahsulotlar ro'yxati:",
    "no_products": "Hozircha mahsulotlar mavjud emas.",
    "not_found": "🔍 Bunday mahsulot topilmadi.",
    "product_removed": "Bu mahsulot topilmadi (ehtimol o'chirilgan).",
    "adapted": "✅ Til sozlamangiz yangilandi.",
    "choose_lang": "Tilni tanlang:",
}


def ui(lang: str, script: str, key: str) -> str:
    return display_text(BASE_STRINGS[key], lang, script)


# --------------------------------------------------------------------------
# TIL ANIQLASH VA SOZLASH
# --------------------------------------------------------------------------

LANGUAGE_OPTIONS = [
    ("O'zbek (lotin)", "uz", "latin"),
    ("Ўзбек (кирилл)", "uz", "cyrillic"),
    ("Русский", "ru", "-"),
    ("English", "en", "-"),
    ("Deutsch", "de", "-"),
    ("Français", "fr", "-"),
    ("Español", "es", "-"),
    ("Türkçe", "tr", "-"),
    ("العربية", "ar", "-"),
    ("中文", "zh-CN", "-"),
    ("한국어", "ko", "-"),
    ("Tiếng Việt", "vi", "-"),
]

ADAPT_TRIGGERS = [
    "menga moslash", "moslash", "adapt", "adapt to me",
    "настрой", "подстрой", "anpassen", "адаптируй",
]


def default_lang_from_telegram(language_code: str):
    """Telegram profilidagi tildan boshlang'ich til/yozuvni aniqlaydi."""
    if not language_code:
        return "uz", "latin"
    code = language_code.lower().split("-")[0]
    if code == "uz":
        return "uz", "latin"
    return code, "-"


async def get_session_lang(chat_id: int, telegram_language_code: str):
    session = fb_get(f"sessions/{chat_id}") or {}
    lang = session.get("lang")
    script = session.get("script")
    if not lang:
        lang, script = default_lang_from_telegram(telegram_language_code)
        fb_update(f"sessions/{chat_id}", {"lang": lang, "script": script})
    return lang, script, session


# --------------------------------------------------------------------------
# TELEGRAM YORDAMCHILARI
# --------------------------------------------------------------------------

async def try_delete(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        print("Xabarni o'chirib bo'lmadi:", e)


async def track_message(chat_id: int, message_id: int):
    """Bot yuborgan xabarni keyinroq o'chirish uchun eslab qolamiz."""
    fb_update(f"sessions/{chat_id}/msgs", {str(message_id): True})


async def clear_tracked_history(bot: Bot, chat_id: int):
    """Til o'zgarganda: botning avval yuborgan xabarlarini (menyu, mahsulotlar) o'chiradi."""
    session = fb_get(f"sessions/{chat_id}") or {}
    msgs = session.get("msgs") or {}
    for mid in msgs.keys():
        try:
            await try_delete(bot, chat_id, int(mid))
        except Exception:
            pass
    fb_update(f"sessions/{chat_id}", {"msgs": None})


async def tracked_send_message(bot: Bot, chat_id: int, text: str, **kwargs):
    msg = await bot.send_message(chat_id, text, **kwargs)
    await track_message(chat_id, msg.message_id)
    return msg


async def tracked_send_photo(bot: Bot, chat_id: int, photo, **kwargs):
    msg = await bot.send_photo(chat_id, photo, **kwargs)
    await track_message(chat_id, msg.message_id)
    return msg


def build_menu(products: dict, lang: str, script: str):
    if not products:
        return None
    rows = [
        [InlineKeyboardButton(display_text(p.get("name", key), lang, script), callback_data=key)]
        for key, p in products.items()
    ]
    return InlineKeyboardMarkup(rows)


def build_lang_menu():
    rows = []
    row = []
    for label, lang, script in LANGUAGE_OPTIONS:
        row.append(InlineKeyboardButton(label, callback_data=f"setlang:{lang}:{script}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


async def send_menu(bot: Bot, chat_id: int, lang: str, script: str):
    products = fb_get("products") or {}
    kb = build_menu(products, lang, script)
    if kb:
        await tracked_send_message(bot, chat_id, ui(lang, script, "menu_title"), reply_markup=kb)
    else:
        await tracked_send_message(bot, chat_id, ui(lang, script, "no_products"))


MESSAGE_LIMIT = 4096
CAPTION_LIMIT = 1024


async def send_long_text(bot: Bot, chat_id: int, text: str):
    for i in range(0, len(text), MESSAGE_LIMIT):
        await tracked_send_message(bot, chat_id, text[i:i + MESSAGE_LIMIT])


async def send_product(bot: Bot, chat_id: int, product: dict, lang: str, script: str):
    name = display_text(product.get("name", ""), lang, script)
    desc = display_text(product.get("description", ""), lang, script)
    caption = f"{name}\n\n{desc}"
    image_b64 = product.get("image_base64")

    if image_b64:
        try:
            photo_bytes = base64.b64decode(image_b64)
            photo_file = io.BytesIO(photo_bytes)
            photo_file.name = "product.jpg"

            if len(caption) <= CAPTION_LIMIT:
                await tracked_send_photo(bot, chat_id, photo_file, caption=caption)
            else:
                await tracked_send_photo(bot, chat_id, photo_file, caption=name)
                await send_long_text(bot, chat_id, desc)
            return
        except Exception as e:
            print("Rasm yuborishda xato:", e)
            await send_long_text(bot, chat_id, f"{caption}\n\n(⚠️)")
            return

    await send_long_text(bot, chat_id, caption)


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
    telegram_lang_code = update.effective_user.language_code if update.effective_user else None

    # --- Callback (menyu tugmasi yoki til tanlash) ---
    if update.callback_query:
        cq = update.callback_query
        chat_id = cq.message.chat_id
        data = cq.data or ""

        if data.startswith("setlang:"):
            _, lang, script = data.split(":")
            fb_update(f"sessions/{chat_id}", {"lang": lang, "script": script})
            await cq.answer()
            await clear_tracked_history(bot, chat_id)
            await tracked_send_message(bot, chat_id, ui(lang, script, "adapted"))
            await send_menu(bot, chat_id, lang, script)
            return

        lang, script, _ = await get_session_lang(chat_id, telegram_lang_code)
        products = fb_get("products") or {}
        product = products.get(data)
        await cq.answer()
        if product:
            await send_product(bot, chat_id, product, lang, script)
        else:
            await tracked_send_message(bot, chat_id, ui(lang, script, "product_removed"))
        return

    message = update.message
    if not message:
        return

    chat_id = message.chat_id
    text = (message.text or message.caption or "").strip()

    session = fb_get(f"sessions/{chat_id}") or {}
    is_admin = bool(session.get("admin", False))  # endi ishlatilmaydi, kelajakda kerak bo'lishi mumkin
    step = session.get("step")

    # ---------------- BUYRUQLAR ----------------

    if text.startswith("/start"):
        fb_update(f"sessions/{chat_id}", {"step": None})
        lang, script, _ = await get_session_lang(chat_id, telegram_lang_code)
        await send_menu(bot, chat_id, lang, script)
        return

    if text.startswith("/til") or text.startswith("/language") or text.startswith("/язык"):
        lang, script, _ = await get_session_lang(chat_id, telegram_lang_code)
        await tracked_send_message(bot, chat_id, ui(lang, script, "choose_lang"), reply_markup=build_lang_menu())
        return

    if text.startswith("/admin"):
        prompt = await bot.send_message(chat_id, "🔑 Admin ID kiriting:")
        fb_set(f"sessions/{chat_id}", {"step": "await_id", "prompt_msg_id": prompt.message_id})
        await try_delete(bot, chat_id, message.message_id)
        return

    if text.startswith("/logout"):
        fb_set(f"sessions/{chat_id}", {"admin": False, "step": None})
        await bot.send_message(chat_id, "Admin sessiyasi tugatildi.")
        return

    # ---------------- LOGIN BOSQICHLARI ----------------

    if step == "await_id":
        prompt = await bot.send_message(chat_id, "🔒 Parolni kiriting:")
        # oldingi "ID kiriting" xabarini o'chiramiz
        old_prompt_id = session.get("prompt_msg_id")
        if old_prompt_id:
            await try_delete(bot, chat_id, old_prompt_id)
        fb_update(f"sessions/{chat_id}", {
            "step": "await_password",
            "temp_id": text,
            "prompt_msg_id": prompt.message_id,
        })
        await try_delete(bot, chat_id, message.message_id)
        return

    if step == "await_password":
        entered_id = session.get("temp_id", "")
        # "Parolni kiriting" xabarini o'chiramiz
        old_prompt_id = session.get("prompt_msg_id")
        if old_prompt_id:
            await try_delete(bot, chat_id, old_prompt_id)

        if entered_id == ADMIN_LOGIN_ID and text == ADMIN_LOGIN_PASSWORD:
            fb_set(f"sessions/{chat_id}", {"step": None})
            await send_admin_link(bot, chat_id, request_host)
        else:
            fb_set(f"sessions/{chat_id}", {"step": None})
            await bot.send_message(chat_id, "❌ ID yoki parol noto'g'ri.")
        await try_delete(bot, chat_id, message.message_id)
        return

    # ---------------- "MENGA MOSLASH" TRIGGERI ----------------

    if text and not text.startswith("/"):
        normalized = text.lower()
        if any(trigger in normalized for trigger in ADAPT_TRIGGERS):
            _, detected = translate_google(text, "en", source_lang="auto")
            if detected:
                new_script = "cyrillic" if (detected == "uz" and contains_cyrillic(text)) else "latin"
                fb_update(f"sessions/{chat_id}", {"lang": detected, "script": new_script})
                await clear_tracked_history(bot, chat_id)
                await tracked_send_message(bot, chat_id, ui(detected, new_script, "adapted"))
                await send_menu(bot, chat_id, detected, new_script)
                return

    # ---------------- ODDIY MATN -> MAHSULOT QIDIRISH ----------------

    if text and not text.startswith("/"):
        lang, script, _ = await get_session_lang(chat_id, telegram_lang_code)
        products = fb_get("products") or {}

        match_key = find_best_product(text, products)
        if not match_key and lang != "uz":
            # Foydalanuvchi o'z tilida qidirgan bo'lishi mumkin - o'zbekchaga tarjima qilib qayta urinamiz
            translated_query, _ = translate_google(text, "uz", source_lang="auto")
            if translated_query:
                match_key = find_best_product(translated_query, products)

        if match_key:
            await send_product(bot, chat_id, products[match_key], lang, script)
        else:
            await tracked_send_message(bot, chat_id, ui(lang, script, "not_found"))
        return


async def send_admin_link(bot: Bot, chat_id: int, request_host: str):
    token = secrets.token_urlsafe(24)

    site_url = get_site_url(request_host)
    if not site_url:
        await bot.send_message(chat_id, "❌ Sayt manzili sozlanmagan (SITE_URL).")
        return

    link = f"{site_url}/admin?token={token}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔐 Admin panelni ochish", url=link)]])
    msg = await bot.send_message(chat_id, "✅ Tasdiqlandi. Admin panelni oching:", reply_markup=kb)

    # chat_id va message_id ni ham saqlaymiz - sayt ochilganda shu xabar avtomatik o'chadi
    fb_set(f"admin_tokens/{token}", {
        "created": int(time.time() * 1000),
        "chat_id": chat_id,
        "message_id": msg.message_id,
    })


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
