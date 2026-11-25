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
from services.order_manager import OrderManager

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")


def run() -> None:
    load_env()
    base_url = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
    api_key = os.getenv("DELTA_API_KEY", "")
    api_secret = os.getenv("DELTA_API_SECRET", "")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Fast Pre-Flight Check (Zero-Proxy Bandwidth Guard):
    # Exit immediately with 0 network calls if strategy is flat, inactive, or already trailed/closed.
    state_file = os.path.join(ROOT_DIR, "data", "state.json")
    if not os.path.exists(state_file):
        print(f"[{now_str}] [MONITOR FAST-EXIT] No data/state.json found (Flat/Idle). 0 proxy calls consumed.")
        return

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state_data = json.load(f)
    except Exception as e:
        print(f"[{now_str}] [MONITOR WARN] Error reading state.json: {e}")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    if state_data.get("trade_date") and state_data.get("trade_date") != today_str:
        print(
            f"[{now_str}] [MONITOR FAST-EXIT] state.json date ({state_data.get('trade_date')}) is not today ({today_str}). 0 proxy calls consumed."
        )
        return

    if state_data.get("status") in ("CLOSED", "FAILED_EXIT"):
        print(f"[{now_str}] [MONITOR FAST-EXIT] Strategy status is {state_data.get('status')}. 0 proxy calls consumed.")
        return

    if state_data.get("trail_status") in ("TRAILED", "BOTH_CLOSED"):
        print(
            f"[{now_str}] [MONITOR FAST-EXIT] trail_status is {state_data.get('trail_status')} (Bracket SL active on exchange). 0 proxy calls consumed."
        )
        return

    print("\n========================================================")
    print(f"[{now_str}] RUNNING JOB 3: COMBO A COST TRAIL MONITOR (ACTIVE POSITION)")
    print("========================================================")

    client = DeltaApiClient(api_key, api_secret, base_url)
    order_mgr = OrderManager(client)
    res = order_mgr.monitor_and_update_cost_trail(state_file_path=state_file)
    print(f"[MONITOR RESULT] Status: {res.get('status')} | Details: {res.get('message', res)}")
    print("[FINISHED] Monitor job execution complete.\n")


if __name__ == "__main__":
    run()
