import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

# .env loader (Zero dependency)
ENV_PATH = os.path.join(ROOT_DIR, ".env")
if os.path.exists(ENV_PATH):
    for enc in ["utf-8-sig", "utf-8"]:
        try:
            with open(ENV_PATH, "r", encoding=enc) as f:
                content = f.read()
            break
        except UnicodeError:
            continue
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip("'\"")

from services.notifier import TelegramNotifier

def run_telegram_test():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    print("Checking Telegram Configuration...")
    print(f"Bot Token: {'Configured (' + bot_token[:8] + '...)' if bot_token else 'MISSING'}")
    print(f"Chat ID:   {chat_id if chat_id else 'MISSING'}\n")

    if not bot_token or not chat_id:
        print("[ERROR] Kripya pehle .env file me TELEGRAM_BOT_TOKEN aur TELEGRAM_CHAT_ID daalein.")
        return

    notifier = TelegramNotifier()
    test_msg = (
        "🚀 *Delta Alpha Strangle Bot — Test Alert*\n\n"
        "✅ Telegram notifier successfully connected!\n"
        "🕒 Time: 10-Nov-2026\n"
        "📱 Environment: Pure Standard Library (No external dependencies)"
    )

    print("Sending test message to Telegram...")
    success = notifier.send_message(test_msg)

    if success:
        print("\n[SUCCESS] Message successfully delivered to Telegram!")
    else:
        print("\n[FAILED] Message send nahi hua. Token/Chat ID ya internet connection check karein.")

if __name__ == "__main__":
    run_telegram_test()