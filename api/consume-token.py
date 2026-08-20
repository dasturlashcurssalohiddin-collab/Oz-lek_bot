# -*- coding: utf-8 -*-
"""
Admin havolasi ochilganda chaqiriladi: tokenni tekshiradi, Telegram'dagi
"Admin panelni oching" xabarini o'chiradi, so'ng tokenni bazadan o'chiradi.

GET /api/consume-token?token=XXXX -> {"ok": true/false}
"""

import os
import json
import time
import asyncio
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests
from telegram import Bot

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
FIREBASE_DB_URL = os.environ.get("FIREBASE_DB_URL", "").rstrip("/")
FIREBASE_SECRET = os.environ.get("FIREBASE_SECRET", "")
TOKEN_TTL_SECONDS = 30 * 60


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


def fb_delete(path):
    try:
        r = requests.delete(f"{FIREBASE_DB_URL}/{path}.json", params=_fb_params(), timeout=8)
        r.raise_for_status()
        return True
    except Exception as e:
        print("Firebase DELETE xato:", e)
        return False


async def consume(token: str) -> bool:
    record = fb_get(f"admin_tokens/{token}")
    if not record or not record.get("created"):
        return False

    valid = (time.time() * 1000 - record["created"]) <= TOKEN_TTL_SECONDS * 1000

    chat_id = record.get("chat_id")
    message_id = record.get("message_id")
    if chat_id and message_id:
        bot = Bot(token=BOT_TOKEN)
        async with bot:
            try:
                await bot.delete_message(chat_id, message_id)
            except Exception as e:
                print("Xabarni o'chirib bo'lmadi:", e)

    fb_delete(f"admin_tokens/{token}")
    return valid


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        token = (query.get("token") or [None])[0]

        ok = False
        if token:
            try:
                ok = asyncio.run(consume(token))
            except Exception as e:
                print("consume-token xato:", e)

        body = json.dumps({"ok": ok}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
