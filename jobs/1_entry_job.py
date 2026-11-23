from __future__ import annotations

import json
import os
import sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import DEFAULT_LEVERAGE, LOT_SIZE, load_env

load_env()

from core.api_client import DeltaApiClient
from services.delta_calculator import DeltaCalculator
from services.notifier import TelegramNotifier
from services.order_manager import OrderManager

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")


def run():
    print("\n========================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RUNNING JOB 1: ENTRY & BRACKET SL")
    print("========================================================")

    notifier = TelegramNotifier()
    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    calc = DeltaCalculator(client)
    order_mgr = OrderManager(client, default_leverage=DEFAULT_LEVERAGE)

    lot_size = LOT_SIZE
    print(f"\n[1/3] Fetching 0-DTE 10-Delta Strikes (Lot Size: {lot_size})...")
    ce, pe = calc.get_10_delta_strikes(symbol="BTC", target_delta=0.10, lot_size=lot_size)

    if not ce or not pe:
        msg = "⚠️ [JOB 1 SKIPPED] Today's 0-DTE 10-Delta strikes not available or failed spread/depth filters. Skipping entry safely."
        print(msg)
        notifier.send_message(msg)
        return

    print(f"Selected CE: {ce['symbol']} (ID: {ce['id']})")
    print(f"Selected PE: {pe['symbol']} (ID: {pe['id']})")

    print(
        f"\n[2/3] Setting {DEFAULT_LEVERAGE}x Leverage + Executing Market Sell (Size: {lot_size}) + 100% Combo A Bracket SL..."
    )
    report = order_mgr.execute_strangle_with_dual_verification(ce_info=ce, pe_info=pe, size=lot_size)

    if not report.get("success"):
        print("\n❌ Entry or Bracket SL execution failed.")
        sys.exit(1)

    print("\n[3/3] Saving active state to data/state.json...")
    state_file = os.path.join(ROOT_DIR, "data", "state.json")
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    state_data = {
        "trade_date": datetime.now().strftime("%Y-%m-%d"),
        "entry_timestamp": datetime.now().isoformat(),
        "strategy": "COMBO_A",
        "sl_multiplier": 2.00,
        "trail_status": "ARMED",
        "product_ids": [ce["id"], pe["id"]],
        "ce": report["ce"],
        "pe": report["pe"],
        "status": "OPEN_PROTECTED",
    }

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)

    print(f"[SUCCESS] State saved to {state_file}")
    print("[FINISHED] Job 1 execution complete.\n")


if __name__ == "__main__":
    run()
