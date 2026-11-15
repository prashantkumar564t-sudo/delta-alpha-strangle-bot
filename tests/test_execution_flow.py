import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import load_env
load_env()

from core.api_client import DeltaApiClient
from services.delta_calculator import DeltaCalculator
from services.order_manager import OrderManager

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")

def test_dry_run_pipeline():
    print("=" * 60)
    print("TEST: DRY-RUN SELECTION & TICK-SIZE MATH PIPELINE")
    print("=" * 60)

    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    calc = DeltaCalculator(client)
    order_mgr = OrderManager(client)

    print("\n[STEP 1] Fetching active 10-Delta strikes for BTC (with 0.07-0.13 bounds)...")
    ce, pe = calc.get_10_delta_strikes(symbol="BTC", target_delta=0.10)

    if not ce or not pe:
        print("[ERROR] 10-Delta strikes fetch nahi ho sake.")
        sys.exit(1)

    print(f"\n[STEP 2] Selected Strike Verification:")
    print(f" CE: {ce['symbol']} (ID: {ce['id']})")
    print(f"     • Strike: {ce['strike_price']} | Delta: {ce['delta']} (Abs: {ce['abs_delta']:.4f})")
    print(f"     • Tick Size: {ce['tick_size']} | Mark Price: {ce['mark_price']} USD")
    print(f"     • Bid: {ce['best_bid']} | Ask: {ce['best_ask']}")
    print(f" PE: {pe['symbol']} (ID: {pe['id']})")
    print(f"     • Strike: {pe['strike_price']} | Delta: {pe['delta']} (Abs: {pe['abs_delta']:.4f})")
    print(f"     • Tick Size: {pe['tick_size']} | Mark Price: {pe['mark_price']} USD")
    print(f"     • Bid: {pe['best_bid']} | Ask: {pe['best_ask']}")

    # 1. Delta Bounds Verification (0.07 <= abs_delta <= 0.13)
    ce_safe = (0.07 <= ce["abs_delta"] <= 0.13)
    pe_safe = (0.07 <= pe["abs_delta"] <= 0.13)
    print(f"\n[STEP 3] Safety Bounds Check (0.07 <= |Delta| <= 0.13):")
    print(f" • CE Safe ({ce['abs_delta']:.4f}): {'PASS ✅' if ce_safe else 'FAIL ❌'}")
    print(f" • PE Safe ({pe['abs_delta']:.4f}): {'PASS ✅' if pe_safe else 'FAIL ❌'}")

    # 2. Stop-Loss Tick-Size Rounding Simulation
    print(f"\n[STEP 4] Static 75% SL Tick-Size Rounding Simulation:")
    ce_sim_entry = ce["mark_price"]
    pe_sim_entry = pe["mark_price"]
    ce_raw_sl = ce_sim_entry * 1.75
    pe_raw_sl = pe_sim_entry * 1.75
    ce_rounded_sl = order_mgr._round_to_tick_size(ce_raw_sl, ce["tick_size"])
    pe_rounded_sl = order_mgr._round_to_tick_size(pe_raw_sl, pe["tick_size"])

    print(f" • CE (Sim Entry {ce_sim_entry} USD): Raw 75% = {ce_raw_sl:.4f} -> Rounded = {ce_rounded_sl} (Tick: {ce['tick_size']})")
    print(f" • PE (Sim Entry {pe_sim_entry} USD): Raw 75% = {pe_raw_sl:.4f} -> Rounded = {pe_rounded_sl} (Tick: {pe['tick_size']})")

    if ce_safe and pe_safe:
        print("\n>>> [DRY-RUN RESULT: 100% PASSED] All parameters within safety bounds! <<<")
    else:
        print("\n>>> [DRY-RUN RESULT: FAILED] Safety bounds violated! <<<")
        sys.exit(1)

if __name__ == "__main__":
    test_dry_run_pipeline()
