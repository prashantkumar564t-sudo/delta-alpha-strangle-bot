import os
import json
import urllib.request
import urllib.parse
from typing import Optional

class TelegramNotifier:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = (bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = (chat_id or os.getenv("TELEGRAM_CHAT_ID", "")).strip()

    def send_message(self, text: str) -> bool:
        """Pure standard library (urllib) se Telegram par alert bhejta hai."""
        if not self.bot_token or not self.chat_id:
            print("[NOTIFIER WARN] Telegram credentials nahi mile. Console print only:")
            print(text)
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res = json.loads(response.read().decode("utf-8"))
                return res.get("ok", False)
        except Exception as e:
            print(f"[NOTIFIER ERROR] Telegram alert deliver nahi ho saka: {e}")
            return False