import os
import sys

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
from services.delta_calculator import DeltaCalculator
from services.order_manager import OrderManager

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")

def test_full_pipeline():
    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    calc = DeltaCalculator(client)
    order_mgr = OrderManager(client)

    print("Fetching active 10-Delta strikes for BTC...")
    ce, pe = calc.get_10_delta_strikes(symbol="BTC", target_delta=0.10)

    if not ce or not pe:
        print("[ERROR] Strikes fetch nahi ho paye.")
        return

    print(f"\nTargeting:")
    print(f" CE: {ce['symbol']} (ID: {ce['id']})")
    print(f" PE: {pe['symbol']} (ID: {pe['id']})")

    # Run Strangle with 10s rest and dual verification
    order_mgr.execute_strangle_with_dual_verification(ce_info=ce, pe_info=pe, size=1)

if __name__ == "__main__":
    test_full_pipeline()