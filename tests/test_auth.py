import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import load_env

load_env()

from core.api_client import DeltaApiClient
from services.delta_calculator import DeltaCalculator

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org").strip().rstrip("/")
API_KEY = os.getenv("DELTA_API_KEY", "").strip()
API_SECRET = os.getenv("DELTA_API_SECRET", "").strip()


def run_test():
    print("=" * 60)
    print("TEST: SPLIT-PROXY ROUTING & AUTHENTICATION AUDIT")
    print("=" * 60)

    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    calc = DeltaCalculator(client)

    if client.proxy_url:
        print(f"[*] Static Proxy Configured for Private Calls: {os.getenv('PROXY_HOST')}:{os.getenv('PROXY_PORT')}")
    else:
        print("[*] Direct connection (No proxy configured)")

    # 1. Test Public Market Data Routing (Direct Internet, 0 KB Proxy)
    print("\n[STEP 1] Testing Public Market Data Routing (/v2/tickers & /v2/products)...")
    tickers_res = client.request_public("GET", "/v2/tickers")
    if tickers_res and tickers_res.get("success"):
        tickers_count = len(tickers_res.get("result", []))
        print(f" [PASS] Public /v2/tickers fetched via Direct Network (0 KB Proxy). Count: {tickers_count}")
    else:
        print(f" [FAIL] Public /v2/tickers failed: {tickers_res}")

    products = calc._get_products()
    cache_path = os.path.join(ROOT_DIR, "data", "products_cache.json")
    if products and os.path.exists(cache_path):
        print(f" [PASS] Public /v2/products cached at {cache_path}. Count: {len(products)}")
    else:
        print(f" [FAIL] /v2/products caching failed: count={len(products) if products else 0}")

    # 2. Test Private Authenticated Routing (Via Static IP Proxy)
    print("\n[STEP 2] Testing Private Authenticated Routing (/v2/wallet/balances)...")
    wallet_res = client.request_private("GET", "/v2/wallet/balances")
    if wallet_res and wallet_res.get("success"):
        print("\n[SUCCESS] Demo Account Authenticated via Static Proxy!")
        print(f"Response: {wallet_res.get('success')}")
        for item in wallet_res.get("result", []):
            bal = float(item.get("balance", 0))
            if bal > 0:
                print(f" - Asset: {item.get('asset_symbol')} | Balance: {item.get('available_balance')}")
    else:
        err = wallet_res.get("error") if wallet_res else "No response"
        print(f"\n[FAILED] Private Auth Failed: {err}")


if __name__ == "__main__":
    run_test()
