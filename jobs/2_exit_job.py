import os
import sys
import json
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

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

from core.api_client import DeltaApiClient
from services.order_manager import OrderManager
from services.notifier import TelegramNotifier

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")

def run():
    print(f"\n========================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RUNNING JOB 2: AUTO SQUARE-OFF (05:15 PM)")
    print(f"========================================================")

    notifier = TelegramNotifier()
    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    order_mgr = OrderManager(client)

    # 1. Cleanup all open orders and close positions with retry
    result = order_mgr.square_off_with_retry(max_retries=3, retry_delay=4)
    is_flat = result.get("success", False)
    closed = result.get("closed_positions", [])
    remaining = result.get("remaining_positions", [])

    # 2. Update state.json
    state_file = os.path.join(ROOT_DIR, "data", "state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            state_data["status"] = "CLOSED" if is_flat else "FAILED_EXIT"
            state_data["exit_timestamp"] = datetime.now().isoformat()
            state_data["closed_count"] = len(closed)
            state_data["remaining_count"] = len(remaining)
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            print(f"[STATE WARN] Could not update state.json: {e}")

    # 3. Telegram Alert
    status_lines = []
    if closed:
        for c in closed:
            status_lines.append(f"• `{c.get('symbol')}` : Market {c.get('side', 'Buy').capitalize()} (Closed)")
    else:
        status_lines.append("• No open positions remaining (Already SL hit during the day)")

    if is_flat:
        msg = (
            "🏁 *DELTA ALPHA STRANGLE — SQUARE-OFF COMPLETE*\n\n"
            f"🕒 Time: `{datetime.now().strftime('%H:%M:%S IST')}`\n"
            f"🧹 Pending Orders: Cancelled (Verified 0)\n"
            f"📊 Positions Closed: {len(closed)}\n\n"
            + "\n".join(status_lines) + "\n\n"
            "🛡️ *Status:* Flat (Zero Overnight Risk Verified ✅)"
        )
        print("\n" + msg + "\n")
        notifier.send_message(msg)
        print("[FINISHED] Job 2 execution complete.\n")
    else:
        rem_lines = [f"• `{r.get('product_symbol', r.get('product_id'))}`: Size {r.get('size')}" for r in remaining]
        emergency_msg = (
            "🚨🚨 *[CRITICAL EMERGENCY] AUTO SQUARE-OFF FAILED!* 🚨🚨\n\n"
            f"🕒 Time: `{datetime.now().strftime('%H:%M:%S IST')}`\n"
            "⚠️ Positions still remain open after 3 square-off retries!\n"
            "⏰ 17:30 IST Settlement is in 15 minutes!\n\n"
            "*Remaining Open Positions:*\n"
            + "\n".join(rem_lines) + "\n\n"
            "👉 *PLEASE LOG IN TO DELTA EXCHANGE AND CLOSE MANUALLY IMMEDIATELY!*"
        )
        print("\n" + emergency_msg + "\n")
        notifier.send_message(emergency_msg)
        sys.exit(1)

if __name__ == "__main__":
    run()