import os
import sys
import json
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

# .env loader (Pure Python)
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
from services.delta_calculator import DeltaCalculator
from services.order_manager import OrderManager
from services.notifier import TelegramNotifier

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")

def run():
    print(f"\n========================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RUNNING JOB 1: ENTRY & BRACKET SL")
    print(f"========================================================")

    notifier = TelegramNotifier()
    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    calc = DeltaCalculator(client)
    order_mgr = OrderManager(client)

    print("\n[1/3] Fetching 10-Delta Strikes...")
    ce, pe = calc.get_10_delta_strikes(symbol="BTC", target_delta=0.10)

    if not ce or not pe:
        msg = "❌ [JOB 1 FAILED] 10-Delta strikes fetch nahi ho sake."
        print(msg)
        notifier.send_message(msg)
        sys.exit(1)

    print(f"Selected CE: {ce['symbol']} (ID: {ce['id']})")
    print(f"Selected PE: {pe['symbol']} (ID: {pe['id']})")

    lot_size = int(os.getenv("LOT_SIZE", "1"))
    print(f"\n[2/3] Executing Market Sell (Size: {lot_size}) + 10s Wait + 75% Bracket SL...")
    report = order_mgr.execute_strangle_with_dual_verification(ce_info=ce, pe_info=pe, size=lot_size)

    if not report.get("success"):
        print("\n❌ Entry or Bracket SL execution failed.")
        sys.exit(1)

    print("\n[3/3] Saving active state to data/state.json...")
    state_file = os.path.join(ROOT_DIR, "data", "state.json")
    state_data = {
        "trade_date": datetime.now().strftime("%Y-%m-%d"),
        "entry_timestamp": datetime.now().isoformat(),
        "ce": report["ce"],
        "pe": report["pe"],
        "status": "OPEN_PROTECTED"
    }

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)

    print(f"[SUCCESS] State saved to {state_file}")
    print("[FINISHED] Job 1 execution complete.\n")

if __name__ == "__main__":
    run()