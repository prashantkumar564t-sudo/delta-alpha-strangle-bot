from __future__ import annotations

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


def run():
    print("\n========================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RUNNING JOB 3: COMBO A COST TRAIL MONITOR")
    print("========================================================")

    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    order_mgr = OrderManager(client)
    res = order_mgr.monitor_and_update_cost_trail()
    print(f"[MONITOR RESULT] Status: {res.get('status')} | Details: {res.get('message', res)}")
    print("[FINISHED] Monitor job execution complete.\n")


if __name__ == "__main__":
    run()
