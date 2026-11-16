from __future__ import annotations

import json
import os
import sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import load_env

load_env()

from core.api_client import DeltaApiClient
from services.notifier import TelegramNotifier
from services.order_manager import OrderManager

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")


def run():
    print("\n========================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RUNNING JOB 2: AUTO SQUARE-OFF (05:15 PM)")
    print("========================================================")

    notifier = TelegramNotifier()
    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    order_mgr = OrderManager(client)

    state_file = os.path.join(ROOT_DIR, "data", "state.json")
    target_pids: list[int] | None = None
    state_data: dict = {}

    # Extract active target product IDs from state.json for blast-radius isolation
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            if state_data.get("product_ids"):
                target_pids = [int(pid) for pid in state_data["product_ids"]]
            else:
                pids = []
                ce_id = state_data.get("ce", {}).get("product_id")
                pe_id = state_data.get("pe", {}).get("product_id")
                if ce_id:
                    pids.append(int(ce_id))
                if pe_id:
                    pids.append(int(pe_id))
                if pids:
                    target_pids = pids
        except Exception as e:
            print(f"[STATE WARN] Could not read product_ids from state.json: {e}")

    if target_pids:
        print(f"[*] Target Product IDs for Square-Off (Isolated Blast-Radius): {target_pids}")
    else:
        print("[*] No target product IDs found in state.json; scoping to all active BTC strategy positions.")

    # 1. Cleanup pending bracket orders and close active positions with retry
    result = order_mgr.square_off_with_retry(
        target_product_ids=target_pids,
        max_retries=3,
        retry_delay=4,
    )
    is_flat = result.get("success", False)
    closed = result.get("closed_positions", [])
    remaining = result.get("remaining_positions", [])

    # 2. Update state.json
    if os.path.exists(state_file):
        try:
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
            f"📊 Positions Closed: {len(closed)}\n\n" + "\n".join(status_lines) + "\n\n"
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
            "*Remaining Open Positions:*\n" + "\n".join(rem_lines) + "\n\n"
            "👉 *PLEASE LOG IN TO DELTA EXCHANGE AND CLOSE MANUALLY IMMEDIATELY!*"
        )
        print("\n" + emergency_msg + "\n")
        notifier.send_message(emergency_msg)
        sys.exit(1)


if __name__ == "__main__":
    run()
