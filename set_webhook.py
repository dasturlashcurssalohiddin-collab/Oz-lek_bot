"""
Bu skriptni o'z kompyuteringizda ishga tushiring (Vercel'ga yuklamang).
Vercel deploy bo'lgandan keyin, bot tokeningiz va Vercel URL manzilingizni
kiritib, quyidagi buyruqni terminalda bajaring:

    python set_webhook.py

Bu Telegram'ga "har bir yangi xabarni shu manzilga yubor" deb aytadi.
"""

import requests

BOT_TOKEN = "BOT_TOKEN_BU_YERGA"
VERCEL_URL = "https://sizning-loyiha.vercel.app"  # oxirida / bo'lmasin

resp = requests.get(
    f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
    params={"url": f"{VERCEL_URL}/api/webhook"},
)
print(resp.json())
